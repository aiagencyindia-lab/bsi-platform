"""Queue worker: claim an observation, query the engine, store, extract."""

import json
import logging
import random
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlsplit

from bsi_core import models as m
from bsi_core.alerts import payload
from bsi_core.alerts import scan as scan_alerts
from bsi_core.competitors import _entities_and_hosts, owner_of
from bsi_core.config import get_settings
from bsi_core.crawl import (
    BROWSER_UA,
    PAUSE_SECONDS,
    Audit,
    Fetch,
    Response,
    audit_domain,
    http_fetch,
)
from bsi_core.db import system_session, tenant_session
from bsi_core.entity import audit_entity
from bsi_core.extraction import Extractor
from bsi_core.gaps import clusters
from bsi_core.impact import close_window
from bsi_core.judge import JUDGE_PRICES, JUDGES, generate
from bsi_core.metrics import Filters
from bsi_core.pages import WEIGHTS_VERSION, Target, normalize_url, parse, score
from bsi_core.providers.base import EngineAdapter
from bsi_core.providers.gemini import GeminiGroundingAdapter
from bsi_core.recommend import refresh
from bsi_core.rivals import (
    OutOfTime,
    Snapshot,
    snapshot_domain,
    with_deadline,
)
from bsi_core.scheduling import budget_fits, enqueue_job, run_schedule
from bsi_core.storage import LocalRawStore, RawStore
from bsi_core.suggest import (
    COMPETITOR_JOB_MICROS,
    EMBED_PRICES,
    LABEL_JOB_MICROS,
    PROMPT_JOB_MICROS,
    embed,
    suggest_competitors,
    suggest_prompts,
)
from sqlalchemy import Text, cast, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

log = logging.getLogger("bsi.worker")
MAX_ATTEMPTS = 3
# Wait before attempt 2 and 3. Vertex quotas reset per minute, so the two
# waits together must outlast one window; jitter spreads out a burst.
BACKOFF_SECONDS = (15, 60)
JITTER = 0.2
STALE_RESET_SECONDS = 300
SCHEDULE_CHECK_SECONDS = 60
# Worst case: 60 sections x 2,000 chars ~= 60 x ~520 tokens ~= 31k tokens
# of gemini-embedding-001 at $0.15/M ~= 4,700 micros, rounded up.
PAGE_JOB_MICROS = 5_000
# Under claim_job's 10-minute stale cutoff; a domain cut short is not
# stored and stays due for the next hourly pass.
RIVAL_JOB_SECONDS = 420
RIVAL_UPSERT_CHUNK = 2_000  # 8 binds a row: far under the 65,535 limit
CITED_URLS_CAP = 10
# Waits before delivery attempts 2..5; after the fifth failure the alert
# is given up and keeps its last error.
BACKOFF_DELIVERY = (60, 300, 1800, 7200)
MAX_DELIVERY_ATTEMPTS = 5
WEBHOOK_UA = "bsi-platform-alerts/1.0"  # a machine POST, not a browser


class Poster(Protocol):
    def __call__(
        self,
        url: str,
        user_agent: str,
        *,
        method: str,
        body: bytes,
        content_type: str,
    ) -> Response: ...


# What a suggestion job reserves before it spends (spec §5).
JOB_ESTIMATES = {
    "suggest_prompts": PROMPT_JOB_MICROS,
    "suggest_competitors": COMPETITOR_JOB_MICROS,
    "label_prompts": LABEL_JOB_MICROS,
    "audit_crawl": 0,  # HTTP only: no model, no spend
    "optimize_url": PAGE_JOB_MICROS,
    "crawl_rivals": 0,  # HTTP only: no model, no spend
}


class ExtractorLike(Protocol):
    def prepare(self, org_id: uuid.UUID, obs_id: uuid.UUID) -> Any: ...

    def write(self, s: Session, obs: m.Observation, prepared: Any) -> None: ...


def _claim() -> tuple[uuid.UUID, uuid.UUID] | None:
    with system_session() as s:
        row = s.execute(
            text("SELECT observation_id, org_id FROM claim_observation()")
        ).first()
    return (row.observation_id, row.org_id) if row else None


def reset_stale() -> int:
    with system_session() as s:
        return int(s.execute(text("SELECT reset_stale_running()")).scalar_one())


def run_due_schedules() -> int:
    """Run the due schedules; returns how many ran.

    One schedule's failure never stops the others. Listing them can
    raise (a dead DB); main() logs that and carries on.
    """
    with system_session() as s:
        due = s.execute(
            text("SELECT schedule_id, org_id FROM due_schedules()")
        ).all()
    ran = 0
    for schedule_id, org_id in due:
        try:
            result = run_schedule(org_id, schedule_id)
            log.info("schedule %s: %s", schedule_id, result)
            ran += result is not None
        except Exception:
            log.exception("schedule %s failed", schedule_id)
    return ran


def close_due_impact_windows() -> int:
    """Measure every task whose window has closed; returns how many.

    One task's failure never stops the others, as with schedules.
    """
    with system_session() as s:
        due = s.execute(
            text("SELECT task_id, org_id FROM due_impact_windows()")
        ).all()
    closed = 0
    for task_id, org_id in due:
        try:
            label = close_window(org_id, task_id)
            log.info("task %s impact: %s", task_id, label)
            closed += label is not None
        except Exception:
            log.exception("task %s impact failed", task_id)
    return closed


def refresh_due_recommendations() -> int:
    """Regenerate recommendations for brands due a refresh; returns how
    many brands were refreshed.

    Pure SQL over stored answers, so this costs nothing and never calls a
    model. One brand's failure never stops the others, as with schedules.
    """
    with system_session() as s:
        due = s.execute(
            text("SELECT brand_id, org_id FROM due_recommendation_refreshes()")
        ).all()
    done = 0
    for brand_id, org_id in due:
        try:
            with tenant_session(org_id) as s:
                found = refresh(s, org_id, brand_id)
                # Stamped from the database clock, like every other time
                # this system records; the host clock runs ahead of it.
                s.execute(
                    update(m.Brand)
                    .where(m.Brand.id == brand_id)
                    .values(recs_refreshed_at=func.now())
                )
            log.info("brand %s: %d recommendations", brand_id, found)
            done += 1
        except Exception:
            log.exception("brand %s refresh failed", brand_id)
    return done


def scan_due_alerts() -> int:
    """Scan brands due a daily alert pass; returns how many were scanned.

    SQL only, no spend, so it runs inline like the recommendation refresh.
    One brand's failure never stops the others.
    """
    with system_session() as s:
        due = s.execute(
            text("SELECT brand_id, org_id FROM due_alert_scans()")
        ).all()
    done = 0
    for brand_id, org_id in due:
        try:
            with tenant_session(org_id) as s:
                brand = s.get_one(m.Brand, brand_id)
                rows = scan_alerts(
                    s,
                    org_id,
                    brand_id,
                    datetime.now(UTC),
                    deliver=brand.webhook_url is not None,
                )
                brand.alerts_scanned_at = func.now()
            log.info("brand %s: %d alerts", brand_id, len(rows))
            done += 1
        except Exception:
            log.exception("brand %s alert scan failed", brand_id)
    return done


def deliver_due_alerts(fetch: Poster = http_fetch) -> int:
    """POST each due alert to its brand's webhook; returns how many were
    delivered. The POST runs with no session open. Never raises.
    """
    with system_session() as s:
        due = s.execute(
            text("SELECT alert_id, org_id FROM due_alert_deliveries()")
        ).all()
    delivered = 0
    for alert_id, org_id in due:
        try:
            with tenant_session(org_id) as s:
                alert = s.get_one(m.Alert, alert_id)
                brand = s.get_one(m.Brand, alert.brand_id)
                url, body = (
                    brand.webhook_url,
                    json.dumps(
                        payload(alert, brand.name), default=str
                    ).encode(),
                )
            assert url is not None  # due_alert_deliveries() filtered on it
            resp = fetch(
                url,
                WEBHOOK_UA,
                method="POST",
                body=body,
                content_type="application/json",
            )
            with tenant_session(org_id) as s:
                alert = s.get_one(m.Alert, alert_id)
                # FOR UPDATE: a webhook clear either committed before this
                # read or waits and then nulls next_attempt_at after us.
                hooked = s.scalar(
                    select(m.Brand.webhook_url)
                    .where(m.Brand.id == alert.brand_id)
                    .with_for_update()
                )
                alert.delivery_attempts += 1
                if resp.ok:
                    alert.delivered_at = func.now()
                    alert.next_attempt_at = None
                    alert.last_error = None
                    delivered += 1
                else:
                    alert.last_error = (resp.error or f"HTTP {resp.status}")[
                        :2000
                    ]
                    n = alert.delivery_attempts
                    alert.next_attempt_at = (
                        func.now() + timedelta(seconds=BACKOFF_DELIVERY[n - 1])
                        if n < MAX_DELIVERY_ATTEMPTS and hooked is not None
                        else None
                    )
        except Exception:
            log.exception("alert %s delivery failed", alert_id)
    return delivered


def run_crawl_audit(
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    job_id: uuid.UUID,
    fetch: Fetch = http_fetch,
) -> int:
    """Audit each declared domain (crawl and entity checks); returns how many.

    Fetching happens with no transaction open, as model calls do; the
    rows are written together at the end.
    """
    with tenant_session(org_id) as s:
        brand = s.get_one(m.Brand, brand_id)
        name, aliases = brand.name, list(brand.aliases)
        hosts = list(
            s.scalars(
                select(m.Domain.host)
                .where(m.Domain.brand_id == brand_id)
                .order_by(m.Domain.created_at, m.Domain.host)
            )
        )
    audits = []
    for host in hosts:
        # One host crashing must not lose the others' rows. A crawl crash
        # stores nothing, so the domain stays due.
        try:
            crawl = audit_domain(host, fetch, pause=PAUSE_SECONDS)
        except Exception:
            log.exception("brand %s: audit of %s failed", brand_id, host)
            continue
        # The entity checks ride along; their crash must not cost the
        # crawl checks.
        try:
            ent = audit_entity(
                host, name, aliases, hosts, fetch, pause=PAUSE_SECONDS
            )
        except Exception:
            log.exception("brand %s: entity audit of %s failed", brand_id, host)
            ent = Audit([], 0)
        audits.append(
            (
                host,
                Audit(crawl.checks + ent.checks, crawl.fetches + ent.fetches),
            )
        )
    with tenant_session(org_id) as s:
        for host, audit in audits:
            s.add(
                m.SiteAudit(
                    org_id=org_id,
                    brand_id=brand_id,
                    job_id=job_id,
                    domain=host,
                    checks=[asdict(c) for c in audit.checks],
                    fetches=audit.fetches,
                )
            )
        s.flush()
        # Results reach recommendations now, not at the weekly pass.
        # recs_refreshed_at is deliberately not stamped: an on-demand
        # refresh must not defer the weekly one.
        refresh(s, org_id, brand_id)
    return len(audits)


def cited_urls(
    s: Session,
    brand_id: uuid.UUID,
    prompt_ids: list[uuid.UUID],
    brand_hosts: list[str],
    rival_hosts: list[str],
) -> list[dict[str, Any]]:
    """The cluster's most-cited pages that the brand does not own: the
    evidence a page can add. Answers counted per URL; rivals' pages stay
    in, marked, because they are the competitor pages that win."""
    rows = s.execute(
        text(
            "SELECT c.url, c.domain, count(DISTINCT o.id) AS answers, "
            "array_agg(DISTINCT o.id::text) AS obs "
            "FROM citation c JOIN observation o ON o.id = c.observation_id "
            "WHERE o.brand_id = :brand AND o.status = 'done' "
            "AND o.prompt_id = ANY(:ids) AND NOT c.is_brand_owned "
            "GROUP BY 1, 2 ORDER BY 3 DESC, 1"
        ),
        {"brand": brand_id, "ids": prompt_ids},
    ).all()
    out = []
    for r in rows:
        owner = owner_of(r.domain, brand_hosts, rival_hosts)
        if owner == "brand":
            continue
        out.append(
            {
                "url": r.url,
                "domain": r.domain,
                "owner": owner,
                "answers": int(r.answers),
                "observation_ids": sorted(r.obs),
            }
        )
        if len(out) == CITED_URLS_CAP:
            break
    return out


def audit_page(
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    params: dict[str, Any],
    embedder: Any,
    fetch: Fetch = http_fetch,
) -> dict[str, Any]:
    """Read the cluster, fetch the page, embed its sections, score. Returns
    the page_audit columns; writes nothing. The read session is closed
    before the fetch and the embed."""
    url = normalize_url(str(params.get("url", "")))
    key = str(params.get("cluster_key", ""))
    with tenant_session(org_id) as s:
        brand = s.get_one(m.Brand, brand_id)
        name, aliases = brand.name, list(brand.aliases)
        _, hosts = _entities_and_hosts(s, brand_id)
        brand_hosts = hosts[brand_id]
        rival_hosts = [
            h for e, hs in hosts.items() if e != brand_id for h in hs
        ]
        cluster = next(
            (c for c in clusters(s, brand_id, Filters()) if c["key"] == key),
            None,
        )
        if cluster is None:
            raise ValueError(f"unknown cluster {key!r}")
        pids = [p["prompt_id"] for p in cluster["prompts"]]
        # The vector as text, parsed here: the ORM never selects it.
        vectors = {
            pid: json.loads(v) if v else None
            for pid, v in s.execute(
                select(m.Prompt.id, cast(m.Prompt.embedding, Text)).where(
                    m.Prompt.id.in_(pids)
                )
            ).all()
        }
        cited = cited_urls(s, brand_id, pids, brand_hosts, rival_hosts)
    target = Target(
        intent=cluster["intent"],
        topic=cluster["topic"],
        queries=[(str(p["prompt_id"]), p["text"]) for p in cluster["prompts"]],
        rivals=[r["name"] for r in cluster["rivals"]],
        brand=name,
        aliases=aliases,
        # The audited page's own host is the brand's, declared or not.
        brand_hosts=[*brand_hosts, urlsplit(url).hostname or ""],
        rival_hosts=rival_hosts,
        cited=cited,
        observation_ids=[str(o) for o in cluster["absent_obs"]],
    )
    row: dict[str, Any] = {
        "url": url,
        "cluster_key": key,
        "status": 0,
        "error": None,
        "weights_version": WEIGHTS_VERSION,
        "score": None,
        "components": [],
        # Every key present even when unscored: the API schema and the
        # generated TS type treat the four lists as required.
        "suggestions": {
            "add": [],
            "remove": [],
            "rewrite": [],
            "evidence_to_add": [],
        },
        "evidence": {
            "prompt_ids": [str(p) for p in pids],
            "observation_ids": target.observation_ids,
            "cluster": {"intent": cluster["intent"], "topic": cluster["topic"]},
        },
        "fetches": 1,
    }
    resp = fetch(url, BROWSER_UA)
    row["status"] = resp.status
    if resp.error or not resp.ok:
        row["error"] = resp.error or f"HTTP {resp.status}"
        return row
    page = parse(resp.body)
    if not page.sections:
        row["error"] = "no headings found (is the page rendered by JavaScript?)"
        return row
    section_vectors, _ = embedder([sec.embed_text() for sec in page.sections])
    result = score(
        page, target, [vectors.get(p) for p in pids], section_vectors
    )
    row.update(
        score=result["score"],
        components=result["components"],
        suggestions=result["suggestions"],
    )
    return row


def run_page_audit(
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    job_id: uuid.UUID,
    params: dict[str, Any],
    embedder: Any,
    fetch: Fetch = http_fetch,
) -> None:
    """audit_page, then store the row and refresh recommendations."""
    row = audit_page(org_id, brand_id, params, embedder, fetch)
    with tenant_session(org_id) as s:
        s.add(
            m.PageAudit(org_id=org_id, brand_id=brand_id, job_id=job_id, **row)
        )
        s.flush()
        refresh(s, org_id, brand_id)


def _due_rival_domains(
    s: Session, brand_id: uuid.UUID
) -> list[tuple[uuid.UUID, str, bool]]:
    """(competitor_id, domain, still a baseline) for the brand's active
    competitors' declared domains with no crawl in 7 days, oldest first.
    A domain stays a baseline until a crawl of it reads URLs."""
    rows = s.execute(
        text(
            "SELECT c.id, d.domain, "
            "  NOT coalesce(bool_or(r.urls_seen > 0), false) AS never "
            "FROM competitor c "
            "CROSS JOIN LATERAL unnest(c.domains) AS d(domain) "
            "LEFT JOIN rival_crawl r ON r.competitor_id = c.id "
            "  AND r.domain = d.domain "
            "WHERE c.brand_id = :brand AND c.status = 'active' "
            "GROUP BY c.id, d.domain "
            "HAVING max(r.created_at) IS NULL "
            "  OR max(r.created_at) <= now() - interval '7 days' "
            "ORDER BY max(r.created_at) NULLS FIRST, c.id, d.domain"
        ),
        {"brand": brand_id},
    ).all()
    return [(r.id, r.domain, r.never) for r in rows]


def run_rival_crawl(
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    job_id: uuid.UUID,
    fetch: Fetch = http_fetch,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Snapshot each due competitor domain; returns how many were stored.

    Reads, then fetches with no transaction open, then writes, each
    domain in its own savepoint. A domain that crashes, fails its write,
    or runs out of time after the job's first domain is not stored and
    stays due. The first domain running out of time (it had the whole
    budget) is stored as an incomplete crawl so it is not retried
    hourly. Crawls stay baselines until one reads URLs."""
    with tenant_session(org_id) as s:
        due = _due_rival_domains(s, brand_id)
        cids = sorted({cid for cid, _, _ in due})
        known: dict[uuid.UUID, set[str]] = {cid: set() for cid in cids}
        for cid, url in s.execute(
            select(m.RivalPage.competitor_id, m.RivalPage.url).where(
                m.RivalPage.competitor_id.in_(cids)
            )
        ).tuples():
            known[cid].add(url)
    bounded = with_deadline(fetch, RIVAL_JOB_SECONDS, clock)
    done = []
    for n, (cid, domain, baseline) in enumerate(due):
        try:
            snap = snapshot_domain(
                domain, bounded, known[cid], pause=PAUSE_SECONDS
            )
        except OutOfTime:
            log.info(
                "brand %s: rival crawl out of time at %s", brand_id, domain
            )
            if n == 0:
                late = Snapshot(complete=False)
                late.errors.append(
                    "out of time: the crawl did not finish within "
                    f"{RIVAL_JOB_SECONDS} s"
                )
                done.append((cid, domain, baseline, late))
            break
        except Exception:
            log.exception(
                "brand %s: rival crawl of %s failed", brand_id, domain
            )
            continue
        done.append((cid, domain, baseline, snap))
    stored = 0
    with tenant_session(org_id) as s:
        for cid, domain, baseline, snap in done:
            try:
                with s.begin_nested():
                    fresh = [u for u in snap.urls if u not in known[cid]]
                    s.add(
                        m.RivalCrawl(
                            org_id=org_id,
                            brand_id=brand_id,
                            competitor_id=cid,
                            job_id=job_id,
                            domain=domain,
                            baseline=baseline,
                            complete=snap.complete,
                            urls_seen=len(snap.urls),
                            new_urls=len(fresh),
                            fetches=snap.fetches,
                            errors=[e.replace("\x00", "") for e in snap.errors],
                            types=snap.domain_types,
                        )
                    )
                    sampled = {p["url"]: p["types"] for p in snap.pages}
                    rows = [
                        {
                            "org_id": org_id,
                            "brand_id": brand_id,
                            "competitor_id": cid,
                            "domain": domain,
                            "url": u,
                            "baseline": baseline,
                            "types": sampled.get(u),
                        }
                        for u in snap.urls
                    ]
                    for i in range(0, len(rows), RIVAL_UPSERT_CHUNK):
                        stmt = pg_insert(m.RivalPage).values(
                            rows[i : i + RIVAL_UPSERT_CHUNK]
                        )
                        s.execute(
                            stmt.on_conflict_do_update(
                                index_elements=["competitor_id", "url"],
                                set_={
                                    "last_seen_at": func.now(),
                                    "types": func.coalesce(
                                        stmt.excluded.types, m.RivalPage.types
                                    ),
                                },
                            )
                        )
            except Exception:
                log.exception(
                    "brand %s: rival crawl write of %s failed", brand_id, domain
                )
                continue
            stored += 1
    return stored


def queue_due_rival_crawls() -> int:
    """Queue a rival crawl for every brand due one; returns how many.
    Same contract as queue_due_crawl_audits."""
    with system_session() as s:
        due = s.execute(
            text("SELECT brand_id, org_id FROM due_rival_crawls()")
        ).all()
    queued = 0
    for brand_id, org_id in due:
        try:
            with tenant_session(org_id) as s:
                enqueue_job(
                    s,
                    org_id,
                    brand_id,
                    "crawl_rivals",
                    {},
                    requeue_failed=False,
                )
            queued += 1
        except Exception:
            log.exception("brand %s rival crawl queue failed", brand_id)
    return queued


def queue_due_crawl_audits() -> int:
    """Queue an audit for every brand due one; returns how many.

    Idempotent within the hour: enqueue_job's unique key makes a repeat a
    no-op. requeue_failed=False: this runs every minute, and a failed
    audit must wait for the next hour's slot rather than being re-run
    (and re-crawling the customer's site) on every sweep. One brand's
    failure never stops the others.
    """
    with system_session() as s:
        due = s.execute(
            text("SELECT brand_id, org_id FROM due_crawl_audits()")
        ).all()
    queued = 0
    for brand_id, org_id in due:
        try:
            with tenant_session(org_id) as s:
                enqueue_job(
                    s,
                    org_id,
                    brand_id,
                    "audit_crawl",
                    {},
                    requeue_failed=False,
                )
            queued += 1
        except Exception:
            log.exception("brand %s audit queue failed", brand_id)
    return queued


def _record_failure(
    org_id: uuid.UUID, obs_id: uuid.UUID, error: str, retryable: bool
) -> None:
    with tenant_session(org_id) as s:
        obs = s.get_one(m.Observation, obs_id)
        obs.attempts += 1
        obs.error = error[:2000]
        if retryable and obs.attempts < MAX_ATTEMPTS:
            wait = BACKOFF_SECONDS[obs.attempts - 1]
            wait *= random.uniform(1 - JITTER, 1 + JITTER)
            obs.status = "retry"
            obs.next_attempt_at = func.now() + timedelta(seconds=wait)
        else:
            obs.status = "failed"
            obs.completed_at = func.now()


def process_one(
    adapter: EngineAdapter, store: RawStore, extractor: ExtractorLike
) -> bool:
    claimed = _claim()
    if claimed is None:
        return False
    obs_id, org_id = claimed
    try:
        with tenant_session(org_id) as s:
            obs = s.get_one(m.Observation, obs_id)
            archived = s.get_one(m.Brand, obs.brand_id).status == "archived"
            prompt = s.get_one(m.Prompt, obs.prompt_id).text
            locale = s.get_one(m.Locale, obs.locale_id)
            country, language = locale.country, locale.language
        if archived:  # archived after enqueue: don't spend on it
            _record_failure(org_id, obs_id, "brand archived", retryable=False)
            return True
        # The engine query and the judge (inside prepare) both run with no
        # transaction open. The row stays 'running' until the final write,
        # so a crash in between is recovered by reset_stale().
        result = adapter.query(prompt, country, language)
        if result.kind != "ok" or result.raw is None:
            _record_failure(
                org_id,
                obs_id,
                result.error or "empty result",
                result.kind == "retryable",
            )
            return True
        with tenant_session(org_id) as s:
            obs = s.get_one(m.Observation, obs_id)
            obs.raw_uri = store.put(org_id, obs_id, result.raw)
            obs.model = result.model
            obs.model_version = result.model_version
            obs.params = result.params
            obs.cost_micros = result.cost_micros
            obs.search_queries = result.search_queries
        prepared = extractor.prepare(org_id, obs_id)
        with tenant_session(org_id) as s:
            obs = s.get_one(m.Observation, obs_id)
            extractor.write(s, obs, prepared)
            obs.status = "done"
            obs.error = None
            obs.completed_at = func.now()
    except Exception as e:  # one bad row must never stop the loop
        log.exception("observation %s failed", obs_id)
        _record_failure(org_id, obs_id, repr(e), retryable=True)
    return True


class _Meter:
    """Counts what one job spends, wrapping the work it is given.

    The suggestion jobs return only a summary string: `JudgeFailed`
    carries the cost of a failure, so a success has to be counted here.
    Unmetered adapter methods (`parse`) are delegated through.
    """

    def __init__(
        self, adapter: EngineAdapter, generator: Any, embedder: Any
    ) -> None:
        self.micros = 0
        self._adapter = adapter
        self._generator = generator
        self._embedder = embedder

    def __getattr__(self, name: str) -> Any:
        return getattr(self._adapter, name)

    def query(self, prompt: str, country: str, language: str) -> Any:
        result = self._adapter.query(prompt, country, language)
        self.micros += result.cost_micros
        return result

    def generate(self, prompt: str, schema: Any, temperature: float) -> Any:
        raw, cost, model = self._generator(prompt, schema, temperature)
        self.micros += cost
        return raw, cost, model

    def embed(self, texts: list[str]) -> Any:
        vectors, cost = self._embedder(texts)
        self.micros += cost
        return vectors, cost


def _claim_job() -> tuple[uuid.UUID, uuid.UUID, str] | None:
    with system_session() as s:
        row = s.execute(
            text("SELECT job_id, org_id, kind FROM claim_job()")
        ).first()
    return (row.job_id, row.org_id, row.kind) if row else None


def _finish_job(
    org_id: uuid.UUID,
    job_id: uuid.UUID,
    status: str,
    error: str | None,
    spent: int,
) -> None:
    """Record the outcome, unless someone else already moved the job.

    A stale job is failed by claim_job() while this attempt is still
    running; this attempt's outcome is then discarded, not written over
    whatever moved it. The spend is recorded either way: the money was
    real, and both budget guards read it from this column.
    """
    with tenant_session(org_id) as s:
        job = s.get(m.Job, job_id, with_for_update=True)
        if job is None:
            return
        job.cost_micros += spent
        if job.status != "running":
            log.warning("job %s moved mid-flight: discarding", job_id)
            return
        job.status = status
        job.error = error


def process_job(
    adapter: EngineAdapter,
    generator: Any,
    embedder: Any,
    *,
    fetch: Fetch = http_fetch,
) -> bool:
    """Run one claimed job. False = nothing was queued."""
    claimed = _claim_job()
    if claimed is None:
        return False
    job_id, org_id, kind = claimed
    if kind not in JOB_ESTIMATES:
        _finish_job(org_id, job_id, "failed", "unknown kind", 0)
        return True
    with tenant_session(org_id) as s:
        job = s.get_one(m.Job, job_id)
        brand_id, params = job.brand_id, job.params
        # A job that spends nothing (audit_crawl) is never failed as
        # "budget": that would make a busy org's audits fail and get
        # re-claimed every minute, re-crawling the customer's site.
        estimate = JOB_ESTIMATES[kind]
        fits = estimate == 0 or budget_fits(s, org_id, 0, extra_micros=estimate)
    if not fits:
        _finish_job(org_id, job_id, "failed", "budget", 0)
        return True
    # Every model call below runs with no transaction open; the row stays
    # 'running' until the final write.
    meter = _Meter(adapter, generator, embedder)
    # keep in step with JOB_ESTIMATES
    runners: dict[str, Callable[[], Any]] = {
        "suggest_prompts": lambda: suggest_prompts(
            org_id,
            brand_id,
            int(params.get("count", 0)),
            meter.generate,
            meter.embed,
        ),
        "label_prompts": lambda: suggest_prompts(
            org_id, brand_id, 0, meter.generate, meter.embed
        ),
        "suggest_competitors": lambda: suggest_competitors(
            org_id, brand_id, meter, meter.generate
        ),
        "audit_crawl": lambda: run_crawl_audit(org_id, brand_id, job_id, fetch),
        "optimize_url": lambda: run_page_audit(
            org_id, brand_id, job_id, params, meter.embed, fetch
        ),
        "crawl_rivals": lambda: run_rival_crawl(
            org_id, brand_id, job_id, fetch
        ),
    }
    try:
        result = runners[kind]()
        log.info("job %s: %s", job_id, result)
        _finish_job(org_id, job_id, "done", None, meter.micros)
    except Exception as e:  # one bad job must never stop the loop
        log.exception("job %s failed", job_id)
        # repr(JudgeFailed) already carries the cause's message, so an
        # archived brand reads as such and is never retried.
        _finish_job(
            org_id,
            job_id,
            "failed",
            repr(e)[:2000],
            getattr(e, "cost_micros", 0),
        )
    return True


def tick(
    adapter: EngineAdapter,
    store: RawStore,
    extractor: ExtractorLike,
    *,
    generator: Any = generate,
    embedder: Any = embed,
    fetch: Fetch = http_fetch,
) -> bool:
    """One loop step that never raises. False = idle/failed; caller sleeps.

    A job is claimed before an observation: jobs are rare, user-facing
    and about a minute long, so a 9,000-observation run must not delay
    one for hours.
    """
    try:
        return process_job(
            adapter, generator, embedder, fetch=fetch
        ) or process_one(adapter, store, extractor)
    except Exception:
        # A row whose failure could not be recorded stays 'running';
        # reset_stale() hands it back after 10 minutes.
        log.exception("worker step failed")
        return False


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    settings = get_settings()
    JUDGE_PRICES[settings.extract_model]  # unpriced judge: fail at start
    EMBED_PRICES[settings.embed_model]  # unpriced embedder: same
    adapter = GeminiGroundingAdapter()
    store = LocalRawStore()
    extractor = Extractor(adapter, store, JUDGES[settings.judge_mode])
    last_reset = -STALE_RESET_SECONDS
    last_schedule_check = -SCHEDULE_CHECK_SECONDS
    while True:
        if time.monotonic() - last_reset >= STALE_RESET_SECONDS:
            try:
                log.info("reset %d stale rows", reset_stale())
            except Exception:
                log.exception("reset_stale failed")
            last_reset = time.monotonic()
        if time.monotonic() - last_schedule_check >= SCHEDULE_CHECK_SECONDS:
            try:
                log.info("ran %d due schedules", run_due_schedules())
            except Exception:
                log.exception("run_due_schedules failed")
            try:
                log.info("closed %d impact windows", close_due_impact_windows())
            except Exception:
                log.exception("close_due_impact_windows failed")
            try:
                log.info("refreshed %d brands", refresh_due_recommendations())
            except Exception:
                log.exception("refresh_due_recommendations failed")
            try:
                log.info("queued %d crawl audits", queue_due_crawl_audits())
            except Exception:
                log.exception("queue_due_crawl_audits failed")
            try:
                log.info("queued %d rival crawls", queue_due_rival_crawls())
            except Exception:
                log.exception("queue_due_rival_crawls failed")
            try:
                log.info("scanned %d brands for alerts", scan_due_alerts())
            except Exception:
                log.exception("scan_due_alerts failed")
            try:
                log.info("delivered %d alerts", deliver_due_alerts())
            except Exception:
                log.exception("deliver_due_alerts failed")
            last_schedule_check = time.monotonic()
        if not tick(adapter, store, extractor):
            time.sleep(1)
