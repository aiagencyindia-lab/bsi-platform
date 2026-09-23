# Slice 9: Competitor Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Per-competitor visibility metrics with Wilson intervals and deltas, a leaderboard, and a visibility change feed (≥ 10 prompts moved ≥ 10 points in 14 days, pooled change significant) with evidence.

**Architecture:** One new read-only SQL module `bsi_core/competitors.py` built on `metrics._where`, `metrics.rate`, `metrics.delta` and `metrics.brand_sov`; one new API router with three GET routes; one new Competitors tab. Nothing stored, no job, no migration, no model call.

**Tech Stack:** Python 3.13, SQLAlchemy 2 text queries on Postgres 16, FastAPI/pydantic 2, pytest; Next.js 15 Server Components, `openapi-typescript`.

**Spec:** `docs/superpowers/specs/2026-09-23-slice9-competitor-intelligence-design.md`

## Global Constraints

- Repo root `/Users/vineet/Downloads/ADK/bsi-platform`; the shell cwd resets after every command, so start each with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`. Branch `slice9-competitor-intelligence` (exists; spec committed).
- Every rate is `metrics.rate(k, n)` → `{value, n, ci_low, ci_high}` (95% Wilson). Every delta is `metrics.delta(before, after)` (Newcombe) with label in `increase | decrease | no significant change | insufficient data`.
- Base set for every number: `metrics._where(brand_id, f)` plus `o.status = 'done'`; prompt status is not filtered. Only `status = 'active'` competitors count (`metrics._entities`).
- Windows: `mid = to − days`, `start = to − 2·days`; before `[start, mid)`, after `[mid, to)`; comparability = `len(set(before versions) | set(after versions)) <= 1`, reason text exactly as `brand_deltas`: `f"windows use different pipeline versions {sorted(versions)}; re-extract the older window"`.
- Feed constants: `MIN_PROMPTS = 10`, `MIN_SHIFT = 0.10`, `EVIDENCE_CAP = 20`. A prompt moved when `after.value − before.value >= MIN_SHIFT` (up) or `before.value − after.value >= MIN_SHIFT` (down). Prompts-too-few reason exactly: `"fewer than 10 prompts with answers in both windows"`.
- Only fixed SQL fragments are concatenated; every value is bound. Bind-parameter limit 65,535. Do not select `Prompt.embedding` via ORM.
- Frontend computes no statistic and sorts nothing; the API returns rows already sorted.
- Tests never touch the network. Expectations are computed from the fixture (k/n, or by calling `metrics.delta`), never guessed. `metrics.py` stays at 100% coverage (the gate).
- ruff line length 80, `mypy --strict` over `packages/core/bsi_core`.
- Commit trailer, exactly: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
- The gate, at the end of every task (both lines must pass):
  ```bash
  cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100
  cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate
  ```
  Two pytest warnings (starlette TestClient / anyio) are pre-existing. `gen:check` fails until regenerated types are staged: `npm run gen`, `git add src/lib/schema.d.ts apps/web/openapi.json` (whichever changed), then `npm run gate`.

## File map

| File | Responsibility |
|---|---|
| `packages/core/bsi_core/competitors.py` (new) | `entity_metrics`, `entity_deltas`, `visibility_changes` |
| `tests/integration/test_competitors.py` (new) | scene, windows and feed fixtures; every function's numbers |
| `apps/api/bsi_api/routers/competitors.py` (new), `main.py`, `schemas.py` | three GET routes and their models |
| `tests/integration/test_api_competitors.py` (new), `test_isolation.py` | owner-path 200s, 422, isolation cases |
| `apps/web/src/app/(app)/b/[id]/competitors/page.tsx` (new), `b/[id]/layout.tsx`, `lib/types.ts`, `lib/schema.d.ts`, `apps/web/openapi.json` | the tab |
| `docs/findings-slice9.md` (new), `docs/README.md` | live results, index |

---

### Task 1: `entity_metrics`

**Files:**
- Create: `packages/core/bsi_core/competitors.py`
- Create: `tests/integration/test_competitors.py`

**Interfaces:**
- Consumes: `metrics.Filters`, `metrics._where`, `metrics._entities`, `metrics.rate`, `metrics.brand_sov`, `matching.is_owned`, `recommend._rival_domains` (the same private import `citations.py` uses), `models.Domain`, `models.Competitor`.
- Produces: `entity_metrics(s: Session, brand_id: uuid.UUID, f: Filters) -> list[dict[str, Any]]`, one dict per entity with keys `entity_id, name, type, mention_rate, recommendation_rate, citation_rate, prompt_coverage, sov, avg_position, sentiment, citing_domains`; sorted by `mention_rate.value` desc (None last), brand first on ties, then name. Also `owner_of(domain, brand_hosts, rival_hosts) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
"""Per-competitor metrics, deltas and the change feed (PRD F07)."""

from datetime import UTC, datetime, timedelta

import pytest
from bsi_core import models as m
from bsi_core.competitors import (
    EVIDENCE_CAP,
    MIN_PROMPTS,
    MIN_SHIFT,
    entity_deltas,
    entity_metrics,
    visibility_changes,
)
from bsi_core.db import tenant_session
from bsi_core.metrics import Filters, brand_metrics, delta, rate, wilson
from sqlalchemy import func, select, update


def _mention(org, obs, etype, eid, pos=1, rec="mentioned", sent="neutral"):
    return m.Mention(
        org_id=org.id,
        observation_id=obs,
        entity_type=etype,
        entity_id=eid,
        position=pos,
        rec_status=rec,
        sentiment=sent,
    )


def _cite(org, obs, domain, owned=False):
    return m.Citation(
        org_id=org.id,
        observation_id=obs,
        url="u",
        domain=domain,
        position=1,
        is_brand_owned=owned,
    )


@pytest.fixture
def scene(owner, make_org, make_brand, make_observation):
    """5 done answers over 3 prompts, 1 failed. Brand Nike (nike.com),
    rivals Adidas (adidas.com, adidas.co.in) and Puma (no domains),
    suggested Bata (must not appear).

    o1(p1): Nike recommended @1 positive; Adidas @2 negative;
            cites nike.com (owned), forbes.com
    o2(p1): Nike listed @3 neutral; cites shop.adidas.co.in
    o3(p2): Adidas recommended @1 positive; Puma @2 neutral;
            cites forbes.com, reddit.com
    o4(p2): nobody; cites forbes.com
    o5(p3): Puma @1 negative; cites bata.com
    o6(p3): failed
    """
    org = make_org()
    bid = make_brand(org, "Nike")
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=org.id, brand_id=bid, host="nike.com"))
        ad = m.Competitor(
            org_id=org.id,
            brand_id=bid,
            name="Adidas",
            domains=["adidas.com", "adidas.co.in"],
        )
        pu = m.Competitor(org_id=org.id, brand_id=bid, name="Puma")
        ba = m.Competitor(
            org_id=org.id, brand_id=bid, name="Bata", status="suggested"
        )
        s.add_all([ad, pu, ba])
        s.flush()
        c_ad, c_pu, c_ba = ad.id, pu.id, ba.id
    o1 = make_observation(org, bid, status="done", text="p1")
    with owner() as s:
        p1 = s.get(m.Observation, o1).prompt_id
    o2 = make_observation(org, bid, status="done", prompt_id=p1, sample_index=1)
    o3 = make_observation(org, bid, status="done", text="p2")
    with owner() as s:
        p2 = s.get(m.Observation, o3).prompt_id
    o4 = make_observation(org, bid, status="done", prompt_id=p2, sample_index=1)
    o5 = make_observation(org, bid, status="done", text="p3")
    with owner() as s:
        p3 = s.get(m.Observation, o5).prompt_id
    make_observation(org, bid, status="failed", prompt_id=p3, sample_index=1)
    with owner() as s, s.begin():
        s.add_all(
            [
                _mention(org, o1, "brand", bid, 1, "recommended", "positive"),
                _mention(org, o1, "competitor", c_ad, 2, "mentioned", "negative"),
                _mention(org, o2, "brand", bid, 3, "listed"),
                _mention(org, o3, "competitor", c_ad, 1, "recommended", "positive"),
                _mention(org, o3, "competitor", c_pu, 2),
                _mention(org, o5, "competitor", c_pu, 1, "mentioned", "negative"),
                _mention(org, o5, "competitor", c_ba, 2),
                _cite(org, o1, "nike.com", True),
                _cite(org, o1, "forbes.com"),
                _cite(org, o2, "shop.adidas.co.in"),
                _cite(org, o3, "forbes.com"),
                _cite(org, o3, "reddit.com"),
                _cite(org, o4, "forbes.com"),
                _cite(org, o5, "bata.com"),
            ]
        )
    return org, bid, {"adidas": c_ad, "puma": c_pu, "bata": c_ba, "p1": p1}


def rows(org, bid, **kw):
    with tenant_session(org.id) as s:
        return {r["name"]: r for r in entity_metrics(s, bid, Filters(**kw))}


def _r(k, n):
    return rate(k, n)


def test_every_entity_field_is_k_over_n(scene):
    org, bid, ids = scene
    got = rows(org, bid)
    assert set(got) == {"Nike", "Adidas", "Puma"}  # Bata is suggested
    nike, adidas, puma = got["Nike"], got["Adidas"], got["Puma"]
    assert (nike["type"], adidas["type"]) == ("brand", "competitor")
    # 5 done answers; Adidas named in o1, o3; recommended in o3.
    assert adidas["mention_rate"] == _r(2, 5)
    assert adidas["recommendation_rate"] == _r(1, 5)
    # Cited on a subdomain of adidas.co.in in o2 only.
    assert adidas["citation_rate"] == _r(1, 5)
    # Prompts with done answers: p1, p2, p3; Adidas named on p1, p2.
    assert adidas["prompt_coverage"] == _r(2, 3)
    # Mentions in total: Nike 2, Adidas 2, Puma 2 (Bata's is not counted).
    assert adidas["sov"] == _r(2, 6)
    assert adidas["avg_position"] == {"value": 1.5, "n_mentioned": 2}
    assert adidas["sentiment"]["positive"] == _r(1, 2)
    assert adidas["sentiment"]["negative"] == _r(1, 2)
    assert adidas["sentiment"]["index"] == pytest.approx(0.0)
    # Domains cited in answers naming Adidas (o1, o3), most answers first.
    assert adidas["citing_domains"] == [
        {"domain": "forbes.com", "answers": 2, "owner": "third_party"},
        {"domain": "nike.com", "answers": 1, "owner": "brand"},
        {"domain": "reddit.com", "answers": 1, "owner": "third_party"},
    ]
    assert puma["mention_rate"] == _r(2, 5)
    assert puma["citation_rate"] == _r(0, 5)  # no domains declared
    assert puma["sentiment"]["index"] == pytest.approx(-0.5)
    assert puma["citing_domains"] == [
        {"domain": "bata.com", "answers": 1, "owner": "third_party"},
        {"domain": "forbes.com", "answers": 1, "owner": "third_party"},
        {"domain": "reddit.com", "answers": 1, "owner": "third_party"},
    ]
    low, high = wilson(2, 5)
    assert adidas["mention_rate"]["ci_low"] == pytest.approx(low)
    assert adidas["mention_rate"]["ci_high"] == pytest.approx(high)


def test_brand_row_agrees_with_brand_metrics(scene):
    org, bid, _ = scene
    got = rows(org, bid)["Nike"]
    with tenant_session(org.id) as s:
        bm = brand_metrics(s, bid, Filters())
    for k in ("mention_rate", "recommendation_rate", "citation_rate",
              "prompt_coverage", "sov"):
        assert got[k] == bm[k], k
    assert got["avg_position"] == bm["avg_position"]
    assert got["citing_domains"][0] == {
        "domain": "forbes.com", "answers": 1, "owner": "third_party"
    }
    assert {d["domain"] for d in got["citing_domains"]} == {
        "forbes.com", "nike.com", "shop.adidas.co.in"
    }
    rival = next(d for d in got["citing_domains"] if d["domain"] == "shop.adidas.co.in")
    assert rival["owner"] == "rival"


def test_rows_sort_by_mention_rate_brand_first_on_ties(scene):
    org, bid, _ = scene
    with tenant_session(org.id) as s:
        names = [r["name"] for r in entity_metrics(s, bid, Filters())]
    # Nike 2/5, Adidas 2/5, Puma 2/5: brand first, then by name.
    assert names == ["Nike", "Adidas", "Puma"]


def test_filters_apply(scene):
    org, bid, ids = scene
    got = rows(org, bid, prompt_ids=[ids["p1"]])
    assert got["Adidas"]["mention_rate"] == _r(1, 2)
    assert got["Puma"]["mention_rate"] == _r(0, 2)
    assert got["Puma"]["avg_position"] == {"value": None, "n_mentioned": 0}
    assert got["Puma"]["sentiment"]["index"] is None
    assert got["Puma"]["citing_domains"] == []


def test_no_answers_gives_empty_rates(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Nike")
    got = rows(org, bid)
    assert list(got) == ["Nike"]
    assert got["Nike"]["mention_rate"] == _r(0, 0)
    assert got["Nike"]["sov"]["value"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/integration/test_competitors.py -q`
Expected: `ModuleNotFoundError: No module named 'bsi_core.competitors'`.

- [ ] **Step 3: Implement `entity_metrics`**

```python
"""Competitor intelligence (PRD F07): per-entity metrics, deltas and a
visibility change feed. Read-only SQL over stored answers; every number
shares metrics._where so it agrees with the Overview tiles."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import models as m
from .matching import is_owned
from .metrics import (
    Filters,
    _entities,
    _where,
    brand_sov,
    delta,
    rate,
    window_versions,
)
from .recommend import _rival_domains

DELTA_METRICS = (
    "mention_rate",
    "recommendation_rate",
    "citation_rate",
    "prompt_coverage",
    "sov",
)
CITING_DOMAINS = 5

_DONE = "o.status = 'done'"


def owner_of(domain: str, brand_hosts: list[str], rival_hosts: list[str]) -> str:
    if is_owned(domain, brand_hosts):
        return "brand"
    if is_owned(domain, rival_hosts):
        return "rival"
    return "third_party"


def _hosts(s: Session, brand_id: uuid.UUID) -> dict[uuid.UUID, list[str]]:
    """Declared domains per entity: the brand's `domain` rows, each active
    competitor's `domains` column."""
    out = {
        brand_id: list(
            s.scalars(select(m.Domain.host).where(m.Domain.brand_id == brand_id))
        )
    }
    for c in s.scalars(
        select(m.Competitor).where(
            m.Competitor.brand_id == brand_id, m.Competitor.status == "active"
        )
    ):
        out[c.id] = list(c.domains)
    return out


def entity_metrics(
    s: Session, brand_id: uuid.UUID, f: Filters
) -> list[dict[str, Any]]:
    """One row for the brand and one per active competitor, best mention
    rate first (brand wins ties, then name)."""
    where, params = _where(brand_id, f)
    hosts = _hosts(s, brand_id)
    brand_hosts = hosts[brand_id]
    rival_hosts = _rival_domains(s, brand_id)
    sov = {r["entity_id"]: r for r in brand_sov(s, brand_id, f)}
    sov_total = sum(r["mentions"] for r in sov.values())
    rows = []
    for eid, name, etype in _entities(s, brand_id):
        p = {**params, "eid": eid, "etype": etype, "domains": hosts.get(eid, [])}
        r = s.execute(
            text(f"""
            SELECT
              count(*) AS n,
              count(*) FILTER (WHERE mn.id IS NOT NULL) AS k_mention,
              count(*) FILTER (WHERE mn.rec_status = 'recommended') AS k_rec,
              count(*) FILTER (WHERE EXISTS (
                SELECT 1 FROM citation c
                WHERE c.observation_id = o.id AND EXISTS (
                  SELECT 1 FROM unnest(CAST(:domains AS text[])) d
                  WHERE c.domain = d OR c.domain LIKE '%.' || d))) AS k_cit,
              count(DISTINCT o.prompt_id) AS prompts,
              count(DISTINCT o.prompt_id) FILTER (
                WHERE mn.id IS NOT NULL) AS prompts_cov,
              avg(mn.position) AS avg_pos,
              count(*) FILTER (WHERE mn.sentiment = 'positive') AS k_pos,
              count(*) FILTER (WHERE mn.sentiment = 'negative') AS k_neg
            FROM observation o
            LEFT JOIN mention mn ON mn.observation_id = o.id
              AND mn.entity_type = :etype AND mn.entity_id = :eid
            WHERE {where} AND {_DONE}"""),
            p,
        ).one()
        cited = s.execute(
            text(
                "SELECT c.domain, count(DISTINCT o.id) AS answers "
                "FROM citation c "
                "JOIN observation o ON o.id = c.observation_id "
                "JOIN mention mn ON mn.observation_id = o.id "
                "  AND mn.entity_type = :etype AND mn.entity_id = :eid "
                f"WHERE {where} AND {_DONE} "
                "GROUP BY c.domain ORDER BY answers DESC, c.domain "
                f"LIMIT {CITING_DOMAINS}"
            ),
            p,
        ).all()
        pos = rate(r.k_pos, r.k_mention)
        neg = rate(r.k_neg, r.k_mention)
        rows.append(
            {
                "entity_id": eid,
                "name": name,
                "type": etype,
                "mention_rate": rate(r.k_mention, r.n),
                "recommendation_rate": rate(r.k_rec, r.n),
                "citation_rate": rate(r.k_cit, r.n),
                "prompt_coverage": rate(r.prompts_cov, r.prompts),
                "sov": rate(sov[eid]["mentions"], sov_total),
                "avg_position": {
                    "value": float(r.avg_pos) if r.avg_pos is not None else None,
                    "n_mentioned": r.k_mention,
                },
                "sentiment": {
                    "positive": pos,
                    "negative": neg,
                    # Computed here so the page computes nothing.
                    "index": (
                        pos["value"] - neg["value"]
                        if pos["value"] is not None and neg["value"] is not None
                        else None
                    ),
                },
                "citing_domains": [
                    {
                        "domain": c.domain,
                        "answers": c.answers,
                        "owner": owner_of(c.domain, brand_hosts, rival_hosts),
                    }
                    for c in cited
                ],
            }
        )
    rows.sort(
        key=lambda r: (
            -(r["mention_rate"]["value"] or -1.0),
            r["type"] != "brand",
            r["name"],
        )
    )
    return rows
```

`sov[eid]` is always present: `brand_sov` iterates the same `_entities`. `rate(k, 0)` gives value None, so the sort key's `or -1.0` puts empty rows last. mypy: `r.avg_pos` is `Any` from a text row; the `float(...)` is fine.

- [ ] **Step 4: Run to verify pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/integration/test_competitors.py -q`
Expected: the five tests pass. The test file also imports `entity_deltas`, `visibility_changes`, `MIN_PROMPTS`, `MIN_SHIFT` and `EVIDENCE_CAP`, so define the three constants (10, 0.10, 20) now and write the two functions as `raise NotImplementedError` stubs with the signatures from Task 2's Interfaces block. Task 2 replaces them.

- [ ] **Step 5: Gate, commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/competitors.py tests/integration/test_competitors.py && git commit -m "feat(competitors): per-entity metrics with Wilson intervals

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `entity_deltas` and `visibility_changes`

**Files:**
- Modify: `packages/core/bsi_core/competitors.py`
- Modify: `tests/integration/test_competitors.py`

**Interfaces:**
- Consumes: Task 1's `entity_metrics`; `metrics.delta`, `metrics.rate`, `metrics.window_versions`, `metrics._where`.
- Produces:
  - `entity_deltas(s, brand_id, f, days: int, to: datetime) -> dict` with keys `before: {from, to, entities}`, `after`, `comparable`, `reason`, `deltas: dict[uuid, dict[str, Delta]] | None`.
  - `visibility_changes(s, brand_id, f, days: int = 14, to: datetime | None = None) -> dict` with keys `comparable, reason, prompts, changes`; each change has `competitor_id, name, direction, before, after, delta, prompts, engines, new_citing_domains, observation_ids`.
  - Constants `MIN_PROMPTS = 10`, `MIN_SHIFT = 0.10`, `EVIDENCE_CAP = 20`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_competitors.py`:

```python
def _answers(owner, org, bid, prompt_id, when, n):
    """n done answers on one prompt with requested_at = when, inserted
    directly (make_observation cannot set the time)."""
    with owner() as s, s.begin():
        locale = s.scalars(
            select(m.Locale).where(m.Locale.brand_id == bid)
        ).first()
        engine = s.scalars(select(m.Engine)).first()
        job = s.scalars(
            select(m.Job).where(m.Job.brand_id == bid, m.Job.kind == "run")
        ).first()
        if job is None:
            job = m.Job(org_id=org.id, brand_id=bid, scheduled_slot=when)
            s.add(job)
            s.flush()
        obs = [
            m.Observation(
                org_id=org.id,
                brand_id=bid,
                job_id=job.id,
                prompt_id=prompt_id,
                engine_id=engine.id,
                locale_id=locale.id,
                sample_index=i,
                scheduled_slot=when.replace(minute=0, second=0, microsecond=0),
                status="done",
                requested_at=when,
            )
            for i in range(n)
        ]
        s.add_all(obs)
        s.flush()
        return [o.id for o in obs]


def _prompt(owner, org, bid, text_):
    with owner() as s, s.begin():
        locale = s.scalars(
            select(m.Locale).where(m.Locale.brand_id == bid)
        ).first()
        p = m.Prompt(org_id=org.id, brand_id=bid, locale_id=locale.id, text=text_)
        s.add(p)
        s.flush()
        return p.id


NOW = datetime.now(UTC) + timedelta(minutes=1)
BEFORE_AT = NOW - timedelta(days=20)
AFTER_AT = NOW - timedelta(days=5)


@pytest.fixture
def feed(owner, make_org, make_brand):
    """12 prompts x 10 answers per window (n=10 so a 0.1 shift exists).

    A: before 0/10 everywhere; after 10/10 on q00..q10 (11 prompts), 0/10
       on q11  -> up on 11 prompts, pooled 0/110 -> 110/110: qualifies.
    B: after 10/10 on q00..q08 (9 prompts)  -> count rule fails.
    C: before 4/10, after 5/10 on q00..q09 (10 prompts, shift exactly
       MIN_SHIFT) -> pooled 40/100 -> 50/100: delta() says
       "no significant change" (the test computes it, not the fixture).
       (1/10 -> 2/10 would NOT do: 10/100 -> 20/100 is just significant.)
    Citations: every before answer on q00 cites old.com; after answers
    naming A on q00 cite old.com and new.com.
    """
    org = make_org()
    bid = make_brand(org, "Nike")
    with owner() as s, s.begin():
        cs = [
            m.Competitor(org_id=org.id, brand_id=bid, name=n)
            for n in ("A", "B", "C")
        ]
        s.add_all(cs)
        s.flush()
        ca, cb, cc = (c.id for c in cs)
    prompts = [_prompt(owner, org, bid, f"q{i:02d}") for i in range(12)]
    before = {p: _answers(owner, org, bid, p, BEFORE_AT, 10) for p in prompts}
    after = {p: _answers(owner, org, bid, p, AFTER_AT, 10) for p in prompts}
    ment = []
    cites = []
    for i, p in enumerate(prompts):
        if i < 11:
            ment += [_mention(org, o, "competitor", ca) for o in after[p]]
        if i < 9:
            ment += [_mention(org, o, "competitor", cb, 2) for o in after[p]]
        if i < 10:
            ment += [_mention(org, o, "competitor", cc, 3) for o in before[p][:4]]
            ment += [_mention(org, o, "competitor", cc, 3) for o in after[p][:5]]
    cites += [_cite(org, o, "old.com") for o in before[prompts[0]]]
    cites += [_cite(org, o, d) for o in after[prompts[0]] for d in ("old.com", "new.com")]
    with owner() as s, s.begin():
        s.add_all(ment + cites)
    return org, bid, {"a": ca, "b": cb, "c": cc, "prompts": prompts, "after": after}


def changes(org, bid, days=14, to=NOW, **kw):
    with tenant_session(org.id) as s:
        return visibility_changes(s, bid, Filters(**kw), days, to)


def test_feed_constants():
    assert (MIN_PROMPTS, MIN_SHIFT, EVIDENCE_CAP) == (10, 0.10, 20)


def test_only_the_qualifying_competitor_gets_an_entry(feed):
    org, bid, ids = feed
    got = changes(org, bid)
    assert (got["comparable"], got["reason"], got["prompts"]) == (True, None, 12)
    assert [(c["name"], c["direction"]) for c in got["changes"]] == [("A", "up")]
    a = got["changes"][0]
    assert a["competitor_id"] == ids["a"]
    assert a["before"] == rate(0, 110)
    assert a["after"] == rate(110, 110)
    assert a["delta"] == delta(rate(0, 110), rate(110, 110))
    assert a["delta"]["label"] == "increase"
    assert len(a["prompts"]) == 11
    assert all(p["before"] == rate(0, 10) and p["after"] == rate(10, 10)
               for p in a["prompts"])
    assert [p["text"] for p in a["prompts"]] == [f"q{i:02d}" for i in range(11)]
    assert a["engines"] and all(isinstance(e, str) for e in a["engines"])
    assert a["new_citing_domains"] == ["new.com"]  # old.com was cited before
    assert len(a["observation_ids"]) == EVIDENCE_CAP
    assert set(a["observation_ids"]) <= {
        o for p in ids["prompts"][:11] for o in ids["after"][p]
    }


def test_the_count_rule_and_the_pooled_test_both_gate(feed):
    org, bid, ids = feed
    names = {c["name"] for c in changes(org, bid)["changes"]}
    assert "B" not in names  # 9 prompts moved: below MIN_PROMPTS
    assert "C" not in names  # 10 moved by exactly MIN_SHIFT, but pooled:
    assert delta(rate(40, 100), rate(50, 100))["label"] == "no significant change"


def test_direction_down_and_filters(feed):
    org, bid, ids = feed
    # to = NOW - 5d: after = [NOW-19d, NOW-5d) misses BEFORE_AT (NOW-20d)
    # and AFTER_AT (NOW-5d, not < to); before = [NOW-33d, NOW-19d) is
    # empty too -> no prompt has answers in both windows.
    got = changes(org, bid, days=14, to=NOW - timedelta(days=5))
    assert got["prompts"] == 0
    assert got["reason"] == "fewer than 10 prompts with answers in both windows"
    assert got["changes"] == []
    only = changes(org, bid, prompt_ids=ids["prompts"][:5])
    assert only["prompts"] == 5 and only["changes"] == []


def test_mixed_pipeline_versions_are_not_comparable(owner, feed):
    org, bid, ids = feed
    first_before = ids["prompts"][0]
    with owner() as s, s.begin():
        obs_before = s.scalars(
            select(m.Observation.id).where(
                m.Observation.prompt_id == first_before,
                m.Observation.requested_at < NOW - timedelta(days=14),
            )
        ).first()
        obs_after = ids["after"][first_before][0]
        s.add_all(
            [
                m.Extraction(org_id=org.id, observation_id=obs_before,
                             pipeline_version="1", model_used="x",
                             brand_mentioned=False),
                m.Extraction(org_id=org.id, observation_id=obs_after,
                             pipeline_version="2", model_used="x",
                             brand_mentioned=False),
            ]
        )
    got = changes(org, bid)
    assert got["comparable"] is False
    assert got["reason"] == (
        "windows use different pipeline versions ['1', '2']; "
        "re-extract the older window"
    )
    assert got["changes"] == []


def test_entity_deltas_mirror_brand_deltas(feed):
    org, bid, ids = feed
    with tenant_session(org.id) as s:
        got = entity_deltas(s, bid, Filters(), 14, NOW)
    assert got["comparable"] is True and got["reason"] is None
    assert got["before"]["from"] == NOW - timedelta(days=28)
    assert got["before"]["to"] == got["after"]["from"] == NOW - timedelta(days=14)
    assert got["after"]["to"] == NOW
    a_before = next(r for r in got["before"]["entities"] if r["name"] == "A")
    a_after = next(r for r in got["after"]["entities"] if r["name"] == "A")
    assert a_before["mention_rate"] == rate(0, 120)
    assert a_after["mention_rate"] == rate(110, 120)
    d = got["deltas"][ids["a"]]
    assert set(d) == {"mention_rate", "recommendation_rate", "citation_rate",
                      "prompt_coverage", "sov"}
    assert d["mention_rate"] == delta(rate(0, 120), rate(110, 120))
    assert d["prompt_coverage"] == delta(rate(0, 12), rate(11, 12))
    # An entity with no mentions in either window still has a delta row.
    assert got["deltas"][bid]["mention_rate"]["label"] == "no significant change"
```

Note on `test_direction_down_and_filters`: the test name promises a `down` case too. Add one: call `changes(org, bid, days=14, to=NOW)` on a second fixture state where rival A's mentions are moved from the after answers to the before answers (an owner `UPDATE mention SET observation_id` is awkward; simpler: a small helper that deletes A's after mentions and inserts them on `before[p]` for the 11 prompts), and assert one entry `("A", "down")` with `before == rate(110, 110)`, `after == rate(0, 110)`, `delta.label == "decrease"`. Keep expectations computed as above.

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/integration/test_competitors.py -q`
Expected: the new tests fail with `NotImplementedError` (Task 1's stubs) or `AssertionError`.

- [ ] **Step 3: Implement**

Replace the stubs in `competitors.py`:

```python
MIN_PROMPTS = 10
MIN_SHIFT = 0.10
EVIDENCE_CAP = 20
_FEW = "fewer than 10 prompts with answers in both windows"


def _windows(days: int, to: datetime) -> tuple[datetime, datetime]:
    return to - timedelta(days=2 * days), to - timedelta(days=days)


def _comparable(
    s: Session, brand_id: uuid.UUID, before: Filters, after: Filters
) -> tuple[bool, str | None]:
    versions = set(window_versions(s, brand_id, before)) | set(
        window_versions(s, brand_id, after)
    )
    if len(versions) <= 1:
        return True, None
    return False, (
        "windows use different pipeline versions "
        f"{sorted(versions)}; re-extract the older window"
    )


def entity_deltas(
    s: Session, brand_id: uuid.UUID, f: Filters, days: int, to: datetime
) -> dict[str, Any]:
    """Compare [to - days, to) with the `days` before it, per entity.
    Same windows and comparability rule as metrics.brand_deltas."""
    start, mid = _windows(days, to)
    fb = replace(f, date_from=start, date_to=mid)
    fa = replace(f, date_from=mid, date_to=to)
    before = entity_metrics(s, brand_id, fb)
    after = entity_metrics(s, brand_id, fa)
    comparable, reason = _comparable(s, brand_id, fb, fa)
    by_id = {r["entity_id"]: r for r in before}
    return {
        "before": {"from": start, "to": mid, "entities": before},
        "after": {"from": mid, "to": to, "entities": after},
        "comparable": comparable,
        "reason": reason,
        "deltas": {
            r["entity_id"]: {
                k: delta(by_id[r["entity_id"]][k], r[k]) for k in DELTA_METRICS
            }
            for r in after
        }
        if comparable
        else None,
    }


def _per_prompt(
    s: Session, brand_id: uuid.UUID, f: Filters
) -> tuple[dict[uuid.UUID, tuple[str, int]], dict[tuple[uuid.UUID, uuid.UUID], int]]:
    """(prompt -> (text, n done answers), (prompt, entity) -> k) in a window."""
    where, params = _where(brand_id, f)
    prompts = {
        pid: (txt, n)
        for pid, txt, n in s.execute(
            text(
                "SELECT o.prompt_id, p.text, count(*) FROM observation o "
                "JOIN prompt p ON p.id = o.prompt_id "
                f"WHERE {where} AND {_DONE} GROUP BY o.prompt_id, p.text"
            ),
            params,
        ).tuples()
    }
    counts = {
        (pid, eid): k
        for pid, eid, k in s.execute(
            text(
                "SELECT o.prompt_id, mn.entity_id, count(*) FROM mention mn "
                "JOIN observation o ON o.id = mn.observation_id "
                f"WHERE {where} AND {_DONE} AND mn.entity_type = 'competitor' "
                "GROUP BY o.prompt_id, mn.entity_id"
            ),
            params,
        ).tuples()
    }
    return prompts, counts


def visibility_changes(
    s: Session,
    brand_id: uuid.UUID,
    f: Filters,
    days: int = 14,
    to: datetime | None = None,
) -> dict[str, Any]:
    """Competitors that gained or lost >= MIN_SHIFT on >= MIN_PROMPTS
    prompts between the two windows, with a significant pooled change."""
    to = to or datetime.now(UTC)
    start, mid = _windows(days, to)
    fb = replace(f, date_from=start, date_to=mid)
    fa = replace(f, date_from=mid, date_to=to)
    comparable, reason = _comparable(s, brand_id, fb, fa)
    pb, kb = _per_prompt(s, brand_id, fb)
    pa, ka = _per_prompt(s, brand_id, fa)
    shared = [pid for pid in pa if pid in pb]
    out: dict[str, Any] = {
        "comparable": comparable,
        "reason": reason,
        "prompts": len(shared),
        "changes": [],
    }
    if not comparable:
        return out
    if len(shared) < MIN_PROMPTS:
        out["reason"] = _FEW
        return out
    cited_before = set(
        s.scalars(
            text(
                "SELECT DISTINCT c.domain FROM citation c "
                "JOIN observation o ON o.id = c.observation_id "
                f"WHERE {_where(brand_id, fb)[0]} AND {_DONE}"
            ),
            _where(brand_id, fb)[1],
        )
    )
    entries = []
    for cid, name, etype in _entities(s, brand_id):
        if etype != "competitor":
            continue
        moved: dict[str, list[tuple[uuid.UUID, float, int, int, int, int]]] = {
            "up": [],
            "down": [],
        }
        for pid in shared:
            (_, nb), (_, na) = pb[pid], pa[pid]
            k1, k2 = kb.get((pid, cid), 0), ka.get((pid, cid), 0)
            # Rounded: 3/10 - 2/10 is 0.0999... in floats, and a
            # one-answer shift at n=10 must count as MIN_SHIFT.
            shift = round(k2 / na - k1 / nb, 9)
            if shift >= MIN_SHIFT:
                moved["up"].append((pid, shift, k1, nb, k2, na))
            elif -shift >= MIN_SHIFT:
                moved["down"].append((pid, shift, k1, nb, k2, na))
        for direction, rows in moved.items():
            if len(rows) < MIN_PROMPTS:
                continue
            before = rate(sum(r[2] for r in rows), sum(r[3] for r in rows))
            after = rate(sum(r[4] for r in rows), sum(r[5] for r in rows))
            d = delta(before, after)
            if d["label"] != ("increase" if direction == "up" else "decrease"):
                continue
            rows.sort(key=lambda r: (-abs(r[1]), pa[r[0]][0]))
            pids = [r[0] for r in rows]
            entries.append(
                {
                    "competitor_id": cid,
                    "name": name,
                    "direction": direction,
                    "before": before,
                    "after": after,
                    "delta": d,
                    "prompts": [
                        {
                            "prompt_id": pid,
                            "text": pa[pid][0],
                            "before": rate(k1, nb),
                            "after": rate(k2, na),
                        }
                        for pid, _, k1, nb, k2, na in rows
                    ],
                    **_evidence(s, brand_id, fa, cid, pids, cited_before),
                }
            )
    entries.sort(key=lambda e: (-abs(e["delta"]["value"]), e["name"]))
    out["changes"] = entries
    return out


def _evidence(
    s: Session,
    brand_id: uuid.UUID,
    fa: Filters,
    cid: uuid.UUID,
    pids: list[uuid.UUID],
    cited_before: set[str],
) -> dict[str, Any]:
    """After-window answers on the moved prompts that name the competitor:
    their engines, newly cited domains, and up to EVIDENCE_CAP ids."""
    where, params = _where(brand_id, replace(fa, prompt_ids=pids))
    p = {**params, "cid": cid}
    base = (
        "FROM observation o JOIN mention mn ON mn.observation_id = o.id "
        "AND mn.entity_type = 'competitor' AND mn.entity_id = :cid "
        f"WHERE {where} AND {_DONE}"
    )
    engines = list(
        s.scalars(
            text(
                "SELECT DISTINCT e.code " + base.replace(
                    "FROM observation o", "FROM observation o JOIN engine e ON e.id = o.engine_id", 1
                ) + " ORDER BY 1"
            ),
            p,
        )
    )
    domains = [
        d
        for d, in s.execute(
            text(
                "SELECT c.domain FROM citation c JOIN (SELECT o.id " + base
                + ") a ON a.id = c.observation_id "
                "GROUP BY c.domain ORDER BY count(DISTINCT c.observation_id) DESC, c.domain"
            ),
            p,
        ).tuples()
        if d not in cited_before
    ]
    ids = list(
        s.scalars(
            text(
                "SELECT o.id " + base + f" ORDER BY o.requested_at DESC, o.id LIMIT {EVIDENCE_CAP}"
            ),
            p,
        )
    )
    return {"engines": engines, "new_citing_domains": domains, "observation_ids": ids}
```

Fix the one awkward line: build the engines query plainly instead of `str.replace` if it reads badly, e.g. a second `base_e` string with the engine join. Keep every value bound; `EVIDENCE_CAP` and `CITING_DOMAINS` are module ints, not user input. `entity_deltas` needs no `to` default; the router supplies it.

- [ ] **Step 4: Run to verify pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/integration/test_competitors.py -q`
Expected: all pass. If `test_the_count_rule_and_the_pooled_test_both_gate` fails on C, re-check that C has 4 before and 5 after mentions on exactly 10 prompts with n = 10 each; `delta(rate(40,100), rate(50,100))` is "no significant change" (Newcombe low ≈ −0.037). If C is missing from the moved count altogether, the shift comparison is suffering float error: 5/10 − 4/10 must count as 0.10.

- [ ] **Step 5: Gate, commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/competitors.py tests/integration/test_competitors.py && git commit -m "feat(competitors): per-entity deltas and the visibility change feed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: API routes and schemas

**Files:**
- Create: `apps/api/bsi_api/routers/competitors.py`
- Modify: `apps/api/bsi_api/main.py` (the `from .routers import (...)` list and the `for router in (...)` tuple)
- Modify: `apps/api/bsi_api/schemas.py` (append after `SovOut`)
- Create: `tests/integration/test_api_competitors.py`
- Modify: `tests/integration/test_isolation.py` (`CASES`)

**Interfaces:**
- Consumes: Task 1–2 functions; `routers.metrics.filters`, `routers.metrics._flag` (flags `recommendation_rate` experimental), `deps.brand_or_404`, `problems.Problem`, schemas `Rate`, `RecRate`, `AvgPosition`, `Delta`.
- Produces: `GET /v1/brands/{id}/competitors/metrics` → `list[EntityMetricsOut]`; `GET .../competitors/deltas?days=` → `EntityDeltasOut`; `GET .../competitors/changes?days=` → `ChangesOut`.

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_api_competitors.py`:

```python
from datetime import timedelta

from tests.integration.test_competitors import (  # noqa: F401
    NOW,
    feed,
    scene,
)


def test_metrics_lists_brand_and_active_rivals(client, scene):  # noqa: F811
    org, bid, _ = scene
    r = client.get(f"/v1/brands/{bid}/competitors/metrics", headers=org.headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [x["name"] for x in rows] == ["Nike", "Adidas", "Puma"]
    adidas = rows[1]
    assert adidas["mention_rate"]["value"] == 0.4
    assert adidas["recommendation_rate"]["experimental"] is True
    assert adidas["sentiment"]["index"] == 0.0
    assert adidas["citing_domains"][0]["owner"] == "third_party"


def test_metrics_honours_filters(client, scene):  # noqa: F811
    org, bid, ids = scene
    r = client.get(
        f"/v1/brands/{bid}/competitors/metrics?prompt_ids={ids['p1']}",
        headers=org.headers,
    )
    assert r.json()[1]["mention_rate"]["n"] == 2


def test_deltas_and_changes(client, feed):  # noqa: F811
    org, bid, ids = feed
    to = NOW.isoformat()
    r = client.get(
        f"/v1/brands/{bid}/competitors/deltas?days=14&date_to={to}",
        headers=org.headers,
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["comparable"] is True
    assert d["deltas"][str(ids["a"])]["mention_rate"]["label"] == "increase"
    assert d["after"]["entities"][0]["recommendation_rate"]["experimental"] is True
    r = client.get(
        f"/v1/brands/{bid}/competitors/changes?days=14&date_to={to}",
        headers=org.headers,
    )
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["prompts"] == 12
    assert [x["name"] for x in c["changes"]] == ["A"]
    assert c["changes"][0]["direction"] == "up"
    assert c["changes"][0]["new_citing_domains"] == ["new.com"]
    assert len(c["changes"][0]["observation_ids"]) == 20


def test_date_from_is_rejected_on_window_routes(client, scene):  # noqa: F811
    org, bid, _ = scene
    frm = (NOW - timedelta(days=3)).isoformat()
    for route in ("deltas", "changes"):
        r = client.get(
            f"/v1/brands/{bid}/competitors/{route}?date_from={frm}",
            headers=org.headers,
        )
        assert r.status_code == 422, route


def test_unknown_brand_is_404(client, make_org):
    org = make_org()
    for route in ("metrics", "deltas", "changes"):
        r = client.get(
            f"/v1/brands/00000000-0000-0000-0000-000000000000/competitors/{route}",
            headers=org.headers,
        )
        assert r.status_code == 404, route
```

In `test_isolation.py` `CASES`, after the `/competitors` POST line add:

```python
    ("GET", "/v1/brands/{b}/competitors/metrics", None),
    ("GET", "/v1/brands/{b}/competitors/deltas", None),
    ("GET", "/v1/brands/{b}/competitors/changes", None),
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/integration/test_api_competitors.py tests/integration/test_isolation.py -q`
Expected: the new tests fail (404 on the owner path because the routes do not exist). The isolation cases pass already (404 either way) — that is expected; they guard the future.

- [ ] **Step 3: Schemas**

Append to `schemas.py` after `SovOut`:

```python
class SentimentOut(BaseModel):
    positive: Rate
    negative: Rate
    index: float | None


class CitingDomainOut(BaseModel):
    domain: str
    answers: int
    owner: Literal["brand", "rival", "third_party"]


class EntityMetricsOut(BaseModel):
    entity_id: uuid.UUID
    name: str
    type: Literal["brand", "competitor"]
    mention_rate: Rate
    recommendation_rate: RecRate
    citation_rate: Rate
    prompt_coverage: Rate
    sov: Rate
    avg_position: AvgPosition
    sentiment: SentimentOut
    citing_domains: list[CitingDomainOut]


class EntityWindowOut(BaseModel):
    from_: datetime = Field(alias="from")
    to: datetime
    entities: list[EntityMetricsOut]


class EntityDeltasOut(BaseModel):
    before: EntityWindowOut
    after: EntityWindowOut
    comparable: bool
    reason: str | None
    deltas: dict[uuid.UUID, dict[str, Delta]] | None


class ChangePromptOut(BaseModel):
    prompt_id: uuid.UUID
    text: str
    before: Rate
    after: Rate


class ChangeOut(BaseModel):
    competitor_id: uuid.UUID
    name: str
    direction: Literal["up", "down"]
    before: Rate
    after: Rate
    delta: Delta
    prompts: list[ChangePromptOut]
    engines: list[str]
    new_citing_domains: list[str]
    observation_ids: list[uuid.UUID]


class ChangesOut(BaseModel):
    comparable: bool
    reason: str | None
    prompts: int
    changes: list[ChangeOut]
```

`Delta` is defined above `SovOut` already; if it is defined below the insertion point, place these classes after it.

- [ ] **Step 4: Router**

`apps/api/bsi_api/routers/competitors.py`:

```python
"""Competitor intelligence: per-entity metrics, deltas, change feed."""

import uuid
from datetime import UTC, datetime
from typing import Any

from bsi_core.competitors import (
    entity_deltas,
    entity_metrics,
    visibility_changes,
)
from bsi_core.metrics import Filters
from fastapi import APIRouter, Depends, Query

from ..deps import TENANT, Ctx, brand_or_404
from ..problems import Problem
from ..schemas import ChangesOut, EntityDeltasOut, EntityMetricsOut
from .metrics import _flag, filters

router = APIRouter(prefix="/brands/{brand_id}", tags=["competitors"])


def _no_date_from(f: Filters) -> datetime:
    if f.date_from is not None:
        raise Problem(
            422, "date_from is not allowed", "days and date_to set the windows"
        )
    return f.date_to or datetime.now(UTC)


@router.get("/competitors/metrics", response_model=list[EntityMetricsOut])
def get_entity_metrics(
    brand_id: uuid.UUID, f: Filters = Depends(filters), c: Ctx = TENANT
) -> list[dict[str, Any]]:
    brand_or_404(c, brand_id)
    return [_flag(r) for r in entity_metrics(c.s, brand_id, f)]


@router.get("/competitors/deltas", response_model=EntityDeltasOut)
def get_entity_deltas(
    brand_id: uuid.UUID,
    days: int = Query(7, ge=1, le=90),
    f: Filters = Depends(filters),
    c: Ctx = TENANT,
) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    out = entity_deltas(c.s, brand_id, f, days, _no_date_from(f))
    for w in ("before", "after"):
        out[w]["entities"] = [_flag(r) for r in out[w]["entities"]]
    return out


@router.get("/competitors/changes", response_model=ChangesOut)
def get_changes(
    brand_id: uuid.UUID,
    days: int = Query(14, ge=1, le=90),
    f: Filters = Depends(filters),
    c: Ctx = TENANT,
) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    return visibility_changes(c.s, brand_id, f, days, _no_date_from(f))
```

`_flag` mutates and returns its dict, which is what the list comprehension relies on. Register in `main.py`: add `competitors` to the `from .routers import (...)` list (alphabetical) and `competitors.router,` to the tuple in the loop.

- [ ] **Step 5: Run to verify pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/integration/test_api_competitors.py tests/integration/test_isolation.py tests/integration/test_api_typed.py -q`
Expected: all pass.

- [ ] **Step 6: Regenerate types, gate, commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gen && git -C /Users/vineet/Downloads/ADK/bsi-platform add apps/web/openapi.json apps/web/src/lib/schema.d.ts
```
Then the gate. Commit:

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/api/bsi_api/routers/competitors.py apps/api/bsi_api/main.py apps/api/bsi_api/schemas.py tests/integration/test_api_competitors.py tests/integration/test_isolation.py apps/web/openapi.json apps/web/src/lib/schema.d.ts && git commit -m "feat(api): competitor metrics, deltas and change feed routes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Competitors tab

**Files:**
- Create: `apps/web/src/app/(app)/b/[id]/competitors/page.tsx`
- Modify: `apps/web/src/app/(app)/b/[id]/layout.tsx` (tab list), `apps/web/src/lib/types.ts`

**Interfaces:**
- Consumes: the three routes (Task 3), generated types `EntityMetricsOut`, `EntityDeltasOut`, `ChangesOut`; `Filters`, `CiBar`, `apiQuery`, `pct`, `pts`, `ciText`.
- Produces: `/b/{id}/competitors`.

- [ ] **Step 1: Types and tab**

`lib/types.ts`, add:
```ts
export type EntityMetrics = S["EntityMetricsOut"];
export type EntityDeltas = S["EntityDeltasOut"];
export type Changes = S["ChangesOut"];
```
`layout.tsx`: after the Prompts link add `<Link href={`/b/${id}/competitors`}>Competitors</Link>`.

- [ ] **Step 2: Page**

```tsx
import Link from "next/link";
import { Filters } from "@/components/Filters";
import { CiBar } from "@/components/Tile";
import { api } from "@/lib/api";
import { apiQuery, ciText, pct, pts, type Params } from "@/lib/format";
import type { Changes, EntityDeltas, EntityMetrics } from "@/lib/types";

const num = (v: number | null | undefined, digits = 1) =>
  v == null ? "—" : v.toFixed(digits);

export default async function Competitors({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const q = apiQuery(sp);
  // Window routes take days and date_to; they refuse date_from.
  const wq = apiQuery(sp, ["days"], ["date_from"]);
  const [rows, d, feed] = await Promise.all([
    api<EntityMetrics[]>(`/brands/${id}/competitors/metrics${q}`),
    api<EntityDeltas>(`/brands/${id}/competitors/deltas${wq}`),
    api<Changes>(`/brands/${id}/competitors/changes${wq}`),
  ]);
  const days = typeof sp.days === "string" ? Number(sp.days) || 7 : 7;
  const deltaText = (eid: string, key: "mention_rate" | "sov") => {
    const x = d.deltas?.[eid]?.[key];
    if (!x) return null;
    const sig = x.label === "increase" || x.label === "decrease";
    return (
      <div className={sig ? (x.label === "increase" ? "up" : "down") : "muted"}>
        {sig ? `${pts(x.value)} vs previous ${days} days` : x.label}
      </div>
    );
  };
  return (
    <>
      <Filters sp={sp} days />
      <h2>Leaderboard</h2>
      {!d.comparable && <p className="muted">Deltas hidden: {d.reason}</p>}
      <table>
        <thead>
          <tr>
            <th>Entity</th>
            <th>Mention rate</th>
            <th>Recommended</th>
            <th>Share of voice</th>
            <th>Coverage</th>
            <th>Cited</th>
            <th>Avg position</th>
            <th>Sentiment</th>
            <th>Cited alongside</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.entity_id} className={r.type === "brand" ? "you" : undefined}>
              <td>
                {r.name} {r.type === "brand" && <span className="tag">you</span>}
              </td>
              <td>
                {pct(r.mention_rate.value)}
                <CiBar r={r.mention_rate} />
                <div className="muted">{ciText(r.mention_rate)}</div>
                {deltaText(r.entity_id, "mention_rate")}
              </td>
              <td>
                {pct(r.recommendation_rate.value)}{" "}
                {r.recommendation_rate.experimental && (
                  <span className="tag">experimental</span>
                )}
              </td>
              <td>
                {pct(r.sov.value)}
                <div className="muted">{ciText(r.sov)}</div>
                {deltaText(r.entity_id, "sov")}
              </td>
              <td>{pct(r.prompt_coverage.value)}</td>
              <td>{pct(r.citation_rate.value)}</td>
              <td>{num(r.avg_position.value)}</td>
              <td title={`+${pct(r.sentiment.positive.value)} / −${pct(r.sentiment.negative.value)}`}>
                {num(r.sentiment.index, 2)}
              </td>
              <td className="muted">
                {r.citing_domains.map((c) => `${c.domain} (${c.answers})`).join(", ") || "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <h2>Visibility changes</h2>
      <p className="muted">
        A rival that gained or lost at least 10 points on at least 10 prompts in
        the last {days} days, with a significant pooled change. {feed.prompts}{" "}
        prompts have answers in both windows.
      </p>
      {feed.changes.length === 0 && (
        <p className="muted">
          {feed.reason ??
            "No competitor moved 10 points on 10 prompts with a significant pooled change."}
        </p>
      )}
      {feed.changes.map((c) => (
        <div className="card" key={`${c.competitor_id}-${c.direction}`}>
          <h3>
            {c.name} <span className={`tag ${c.direction === "up" ? "up" : "down"}`}>{c.direction}</span>
          </h3>
          <p>
            {pct(c.before.value)} → {pct(c.after.value)} ({pts(c.delta.value)},{" "}
            {pct(c.delta.ci_low)} to {pct(c.delta.ci_high)}) over {c.prompts.length} prompts ·
            engines {c.engines.join(", ")}
          </p>
          {c.new_citing_domains.length > 0 && (
            <p className="muted">New citing domains: {c.new_citing_domains.join(", ")}</p>
          )}
          <ul>
            {c.prompts.map((p) => (
              <li key={p.prompt_id}>
                {p.text}: {pct(p.before.value)} → {pct(p.after.value)}
              </li>
            ))}
          </ul>
          <p className="muted">
            Evidence:{" "}
            {c.observation_ids.map((o) => (
              <Link key={o} href={`/o/${o}`} style={{ marginRight: 6 }}>
                {o.slice(0, 8)}
              </Link>
            ))}
          </p>
        </div>
      ))}
    </>
  );
}
```

`days` mirrors the Overview's parsing (the deltas route defaults to 7; the changes route to 14, but the page passes the same `days` to both, so a bare page shows 7-day deltas and a 7-day feed; that is acceptable — the Filters days field controls both). If `className="you"` has no style, drop it and rely on the tag.

- [ ] **Step 3: Verify**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate`
Expected: typecheck, lint, tests, build (no warnings), gen:check all pass. With the API and web dev servers running, `curl -s -b "bsi_key=<key>" http://localhost:3000/b/<brand>/competitors | grep -c Leaderboard` prints ≥ 1 (optional; the user's dev key is in the handoff and must never be typed into a browser form).

- [ ] **Step 4: Gate, commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add "apps/web/src/app/(app)/b/[id]/competitors/page.tsx" "apps/web/src/app/(app)/b/[id]/layout.tsx" apps/web/src/lib/types.ts && git commit -m "feat(web): Competitors tab with leaderboard and change feed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Live check, findings, index

**Files:**
- Create: `docs/findings-slice9.md`
- Modify: `docs/README.md` (after the Slice 8 section)

- [ ] **Step 1: Read-only live check on Run 1**

Scratchpad script (not committed), run with `uv run python`:

```python
import uuid
from datetime import UTC, datetime

from bsi_core.competitors import entity_deltas, entity_metrics, visibility_changes
from bsi_core.db import tenant_session
from bsi_core.metrics import Filters

ORG = uuid.UUID("<Run 1 org id, de2e7f7b-...: read it with SELECT id, name FROM organization>")
BRAND = uuid.UUID("34db213a-f484-4991-a969-c52cfa5e1c10")
with tenant_session(ORG) as s:
    for r in entity_metrics(s, BRAND, Filters()):
        print(r["name"], r["type"], r["mention_rate"], r["sov"], r["sentiment"]["index"], [c["domain"] for c in r["citing_domains"]])
    d = entity_deltas(s, BRAND, Filters(), 7, datetime.now(UTC))
    print("deltas comparable:", d["comparable"], d["reason"])
    c = visibility_changes(s, BRAND, Filters(), 14, datetime.now(UTC))
    print("changes:", c["comparable"], c["reason"], c["prompts"], len(c["changes"]))
```

Nothing is written: `entity_metrics`, `entity_deltas` and `visibility_changes` only SELECT. Confirm afterwards with `docker compose exec -T db psql -U bsi_owner -d bsi -tAc "select (select count(*) from recommendation),(select count(*) from task),(select count(*) from site_audit)"` → `0|0|0`. To find the org id: `docker compose exec -T db psql -U bsi_owner -d bsi -tAc "select id, name from organization"`.

- [ ] **Step 2: `docs/findings-slice9.md`**

Same shape as `docs/findings-slice8.md`: header (date 2026-09-23, branch, sources: read-only calls in a tenant session, no writes, no spend), then:
1. What was measured, and how (the script).
2. The leaderboard for Run 1 (real output only: each entity's mention rate with n and interval, SOV, coverage, sentiment index, citing domains).
3. Deltas and the change feed: the actual `comparable`/`reason`/`prompts` values and why the feed is empty on a single-burst run (all 100 answers share one window; `prompts` in both windows is 0 → the "fewer than 10 prompts" reason).
4. What the fixture proves that Run 1 cannot: the qualifying/non-qualifying cases in `test_competitors.py` with the computed pooled deltas.
5. Deferred, by decision: rival crawl (sitemap diff); stored entries and alerts; page-level "new cited pages" (Vertex redirects); competitor archive; sentiment is model-judged and unlabelled; correlated windows make the pooled test optimistic.
6. Spend: unchanged ($9.2762 of $15).

- [ ] **Step 3: README index**

After the Slice 8 table in `docs/README.md`:

```markdown
## Slice 9: competitor intelligence

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-23-slice9-competitor-intelligence-design.md](superpowers/specs/2026-09-23-slice9-competitor-intelligence-design.md) | Design spec: per-competitor metrics with Wilson intervals, a leaderboard, week-over-week deltas, and a visibility change feed gated by the PRD's count rule plus a pooled Newcombe test; computed on read. |
| [superpowers/plans/2026-09-23-slice9-competitor-intelligence.md](superpowers/plans/2026-09-23-slice9-competitor-intelligence.md) | Implementation plan, Tasks 1–5. |
| [findings-slice9.md](findings-slice9.md) | Results: the Run 1 leaderboard, why the feed is empty on a single-burst run, what the synthetic fixture proves, and what is deferred. |
```

- [ ] **Step 4: Gate, commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add docs/findings-slice9.md docs/README.md && git commit -m "docs: slice 9 findings and index

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After the tasks

Whole-branch review, one fix wave, scoped re-review (per `subagent-driven-development`), then `finishing-a-development-branch`: push, `GH_TOKEN=$(gh auth token -u aiagencyindia-lab) gh pr create …` (body ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`), `gh pr checks N --watch`, read the run log. Merge only when the user says so.
