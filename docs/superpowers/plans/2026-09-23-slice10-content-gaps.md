# Slice 10: Content Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Content gaps at cluster level: `(intent, topic)` clusters of active prompts with their brand/rival numbers, a gap flag, a model-free brief, one `create_content` recommendation per gap cluster, a labelling job for unlabelled prompts, and a Clusters tab.

**Architecture:** New read-only module `bsi_core/gaps.py` (SQL over stored answers, mentions, extractions and citations, built on `metrics._where`/`rate`); `recommend.py` gains a cluster rule and restricts the per-prompt rule to unlabelled prompts; a `label_prompts` job kind reuses `suggest_prompts(count=0)`; one GET route, one queue route; one tab. No migration.

**Tech Stack:** Python 3.13, SQLAlchemy 2 text queries on Postgres 16, FastAPI/pydantic 2, pytest; Next.js 15 Server Components, `openapi-typescript`.

**Spec:** `docs/superpowers/specs/2026-09-23-slice10-content-gaps-design.md` (committed 9612b7e on branch `slice10-content-gaps`)

## Global Constraints

- Repo root `/Users/vineet/Downloads/ADK/bsi-platform`; the shell cwd resets after every command, so start each with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`. Branch `slice10-content-gaps`.
- Every rate is `metrics.rate(k, n)` → `{value, n, ci_low, ci_high}` (95% Wilson).
- Base set for cluster numbers: `metrics._where(brand_id, f)` + `o.status = 'done'` + `p.status = 'active'` + `p.intent IS NOT NULL AND p.topic IS NOT NULL`. Only `status = 'active'` competitors count as rivals.
- Gap rule, exactly: `absent * 2 >= n` and `rival_absent >= 1` and `most_common(reasons) in CONTENT_REASONS` (`("competitor_dominance", "not_retrieved")` from `recommend.py`); `reasons` ignores null.
- Cluster key, exactly: `f"cluster:{intent}:{topic}"`. Constants `EVIDENCE_CAP = 20`, `SOURCES_CAP = 10`, `LINKS_CAP = 10`, `LABEL_JOB_MICROS = 10_000`.
- Recommendation copy must not contain: guarantee, will rank, will appear, will be recommended, ensure, boost, #1, top spot, dominat, certain; it must contain "Metric to watch:".
- Only fixed SQL fragments are concatenated; every value is bound. Frontend computes no statistic and sorts nothing.
- Tests never touch the network; model calls are injected fakes. `metrics.py` stays at 100% coverage. Expectations are computed from fixtures.
- ruff line length 80, `mypy --strict` over `packages/core/bsi_core`.
- Commit trailer, exactly: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (execution runs on Opus 5.5).
- The gate, at the end of every task (both lines must pass):
  ```bash
  cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100
  cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate
  ```
  Two pytest warnings (starlette TestClient / anyio) are pre-existing. `gen:check` fails until regenerated types are staged: `npm run gen`, `git add apps/web/openapi.json apps/web/src/lib/schema.d.ts`, then `npm run gate`.
- Never write to the dev database `bsi` from tests; the live check (Task 5) is the only dev-DB write and is approved (labelling Run 1).

## File map

| File | Responsibility |
|---|---|
| `packages/core/bsi_core/gaps.py` (new) | `clusters`, `unlabelled`, `brief`, `PAGE_TYPES`, `STRUCTURES` |
| `packages/core/bsi_core/recommend.py` | `_content` restricted; `_content_clusters`; `cluster_copy`; `generate` |
| `packages/core/bsi_core/suggest.py` | `LABEL_JOB_MICROS` |
| `apps/workers/bsi_workers/worker.py` | `JOB_ESTIMATES["label_prompts"]`, runner |
| `apps/api/bsi_api/routers/clusters.py` (new), `routers/prompts.py`, `main.py`, `schemas.py` | `GET /brands/{id}/clusters/gaps`, `POST /brands/{id}/prompts/label` |
| `apps/web/src/app/(app)/b/[id]/clusters/{page.tsx,actions.ts}` (new), `layout.tsx`, `recommendations/page.tsx`, `lib/types.ts`, `lib/format.ts` | Clusters tab; multi-prompt evidence links |
| `tests/integration/test_gaps.py` (new), `test_api_gaps.py` (new), `test_isolation.py`, `test_worker.py`; `tests/unit/test_recommend_copy.py` | tests |
| `docs/findings-slice10.md` (new), `docs/README.md` | live results, index |

---

### Task 1: `gaps.clusters`, `unlabelled` and `brief`

**Files:**
- Create: `packages/core/bsi_core/gaps.py`
- Create: `tests/integration/test_gaps.py`

**Interfaces:**
- Consumes: `metrics.Filters`, `metrics._where`, `metrics.rate`; `competitors._entities_and_hosts(s, brand_id) -> (entities, hosts)` and `competitors.owner_of(domain, brand_hosts, rival_hosts)`; `recommend.CONTENT_REASONS`; models `Prompt`, `Domain`.
- Produces:
  - `clusters(s, brand_id, f: Filters) -> list[dict]`: rows with keys `intent, topic, key, prompts[{prompt_id, text, n, absent}], n, brand, absent, rival_absent, reasons, rivals[{competitor_id, name, answers}], top_rival, spread, cited, sources[{domain, answers, owner}], brand_urls, gap, brief`; sorted `(spread asc, None last), n desc, key`.
  - `unlabelled(s, brand_id) -> int`.
  - `brief(cluster: dict, brand: str) -> dict` with keys `target_queries, page_type, structure, competitors, sources, internal_links, evidence{prompt_ids, observation_ids}, note`.
  - Constants `EVIDENCE_CAP`, `SOURCES_CAP`, `LINKS_CAP`, `PAGE_TYPES`, `NOTE`.

- [ ] **Step 1: Write the failing tests**

```python
"""Content-gap clusters (PRD F11): clusters, the gap rule, the brief."""

from types import SimpleNamespace

import pytest
from bsi_core import models as m
from bsi_core.db import tenant_session
from bsi_core.gaps import (
    EVIDENCE_CAP,
    NOTE,
    PAGE_TYPES,
    brief,
    clusters,
    unlabelled,
)
from bsi_core.metrics import Filters, rate
from sqlalchemy import select, update


def _mention(org, obs, etype, eid, pos=1):
    return m.Mention(
        org_id=org.id, observation_id=obs, entity_type=etype, entity_id=eid,
        position=pos, rec_status="mentioned", sentiment="neutral",
    )


@pytest.fixture
def scene(owner, make_org, make_brand, make_observation):
    """Brand Nike (nike.com); active rivals Adidas (adidas.co.in) and
    Puma; suggested Bata. Prompts (intent, topic) and answers as
    (brand present, rivals named, absence reason, cites):

    gap cluster (comparison, running shoes): 2 prompts x 4 answers
      "nike vs adidas": absent 3/4 (2 dominance naming Adidas, 1 not_retrieved
        naming only Bata, which is suggested); present answer cites
        https://nike.com/run (owned)
      "best running shoe brand": absent 3/4 (dominance, naming Adidas);
        absent answers cite forbes.com and shop.adidas.co.in
      -> absent 6/8, rival_absent 5, reasons {competitor_dominance: 5,
         not_retrieved: 1}: GAP
    winning (informational, sizing): "shoe size chart" 4/4 present
    mixed (recommendation, kids): "kids shoes" absent 1/4 (dominance)
    unlabelled: "old prompt" (no intent/topic) absent 3/3 dominance, Adidas
    Bata is named on two gap answers but is suggested -> never a rival; Puma
    is active but never named.
    """
    org = make_org()
    bid = make_brand(org, "Nike")
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=org.id, brand_id=bid, host="nike.com"))
        ad = m.Competitor(org_id=org.id, brand_id=bid, name="Adidas",
                          domains=["adidas.co.in"])
        pu = m.Competitor(org_id=org.id, brand_id=bid, name="Puma")
        ba = m.Competitor(org_id=org.id, brand_id=bid, name="Bata",
                          status="suggested")
        s.add_all([ad, pu, ba])
        s.flush()
        ids = SimpleNamespace(org=org, brand=bid, adidas=ad.id, puma=pu.id,
                              bata=ba.id)

    def prompt(text, intent, topic, rows):
        first = make_observation(org, bid, status="done", text=text)
        with owner() as s, s.begin():
            pid = s.get(m.Observation, first).prompt_id
            s.execute(update(m.Prompt).where(m.Prompt.id == pid)
                      .values(intent=intent, topic=topic))
        obs = [first] + [
            make_observation(org, bid, status="done", prompt_id=pid,
                             sample_index=i)
            for i in range(1, len(rows))
        ]
        with owner() as s, s.begin():
            for oid, (present, rivals, reason, cites) in zip(
                obs, rows, strict=True
            ):
                s.add(m.Extraction(org_id=org.id, observation_id=oid,
                                   pipeline_version="2", model_used="t",
                                   brand_mentioned=present,
                                   absence_reason=reason))
                if present:
                    s.add(_mention(org, oid, "brand", bid))
                for k, rid in enumerate(rivals, 2):
                    s.add(_mention(org, oid, "competitor", rid, k))
                for pos, (url, domain, owned) in enumerate(cites, 1):
                    s.add(m.Citation(org_id=org.id, observation_id=oid,
                                     url=url, domain=domain, position=pos,
                                     is_brand_owned=owned))
        return pid, obs

    A, P, B = ids.adidas, ids.puma, ids.bata
    forbes = ("https://forbes.com/x", "forbes.com", False)
    adi = ("https://shop.adidas.co.in/y", "shop.adidas.co.in", False)
    own = ("https://nike.com/run", "nike.com", True)
    ids.vs, ids.vs_obs = prompt("nike vs adidas", "comparison", "running shoes", [
        (True, [A], None, [own]),
        (False, [A], "competitor_dominance", [forbes]),
        (False, [A, B], "competitor_dominance", [forbes, adi]),
        (False, [B], "not_retrieved", []),
    ])
    ids.best, ids.best_obs = prompt("best running shoe brand", "comparison",
                                    "running shoes", [
        (True, [], None, []),
        (False, [A], "competitor_dominance", [forbes]),
        (False, [A], "competitor_dominance", [adi]),
        (False, [A], "competitor_dominance", [forbes]),
    ])
    ids.size, _ = prompt("shoe size chart", "informational", "sizing",
                         [(True, [], None, [])] * 4)
    ids.kids, _ = prompt("kids shoes", "recommendation", "kids", [
        (True, [A], None, []), (True, [], None, []), (True, [], None, []),
        (False, [A], "competitor_dominance", []),
    ])
    ids.old, _ = prompt("old prompt", None, None,
                        [(False, [A], "competitor_dominance", [])] * 3)
    return ids


def rows(ids, **kw):
    with tenant_session(ids.org.id) as s:
        return {c["key"]: c for c in clusters(s, ids.brand, Filters(**kw))}


def test_cluster_numbers_and_order(scene):
    got = rows(scene)
    assert list(got) == [
        "cluster:comparison:running shoes",   # spread 2/8 - 6/8 = -0.5
        "cluster:recommendation:kids",        # 3/4 - 2/4 = +0.25
        "cluster:informational:sizing",       # top_rival None -> last
    ]
    gap = got["cluster:comparison:running shoes"]
    assert (gap["intent"], gap["topic"], gap["n"]) == ("comparison", "running shoes", 8)
    assert gap["brand"] == rate(2, 8)
    assert (gap["absent"], gap["rival_absent"]) == (6, 5)
    assert gap["reasons"] == {"competitor_dominance": 5, "not_retrieved": 1}
    assert [(r["name"], r["answers"]) for r in gap["rivals"]] == [("Adidas", 6)]
    assert gap["top_rival"] == {"name": "Adidas", "competitor_id": scene.adidas, **rate(6, 8)}
    assert gap["spread"] == pytest.approx(2 / 8 - 6 / 8)
    assert gap["cited"] == rate(1, 8)
    assert gap["sources"] == [
        {"domain": "forbes.com", "answers": 4, "owner": "third_party"},
        {"domain": "shop.adidas.co.in", "answers": 2, "owner": "rival"},
        {"domain": "nike.com", "answers": 1, "owner": "brand"},
    ]
    assert gap["brand_urls"] == ["https://nike.com/run"]
    # Worst prompt first: both 3/4 absent -> tie broken by text.
    assert [(p["text"], p["n"], p["absent"]) for p in gap["prompts"]] == [
        ("best running shoe brand", 4, 3), ("nike vs adidas", 4, 3),
    ]
    assert gap["gap"] is True and gap["brief"] is not None
    win = got["cluster:informational:sizing"]
    assert win["brand"] == rate(4, 4) and win["top_rival"] is None
    assert win["spread"] is None and win["gap"] is False and win["brief"] is None
    mixed = got["cluster:recommendation:kids"]
    assert (mixed["absent"], mixed["gap"]) == (1, False)
    assert "cluster:None:None" not in got  # the unlabelled prompt is not a cluster


def test_gap_rule_edges(scene, owner):
    # kids: make it absent 2/4 with rivals -> 2*2 >= 4 -> gap.
    with owner() as s, s.begin():
        oid = s.scalars(select(m.Observation.id).where(
            m.Observation.prompt_id == scene.kids).order_by(
            m.Observation.sample_index)).all()[1]
        s.execute(m.Mention.__table__.delete().where(
            m.Mention.observation_id == oid, m.Mention.entity_type == "brand"))
        s.add(_mention(scene.org, oid, "competitor", scene.adidas, 2))
        s.execute(update(m.Extraction).where(m.Extraction.observation_id == oid)
                  .values(brand_mentioned=False, absence_reason="not_retrieved"))
    got = rows(scene)["cluster:recommendation:kids"]
    assert got["absent"] == 2 and got["gap"] is True
    # A cluster whose top reason is category_mismatch is not a gap.
    with owner() as s, s.begin():
        s.execute(update(m.Extraction).where(
            m.Extraction.observation_id.in_(scene.best_obs + scene.vs_obs))
            .values(absence_reason="category_mismatch"))
    assert rows(scene)["cluster:comparison:running shoes"]["gap"] is False


def test_brief_fields(scene):
    gap = rows(scene)["cluster:comparison:running shoes"]
    b = gap["brief"]
    assert b == brief(gap, "Nike")  # brief is pure and stored on the row
    assert b["target_queries"] == ["best running shoe brand", "nike vs adidas"]
    assert b["page_type"] == PAGE_TYPES["comparison"] == "comparison page"
    assert b["structure"][0].startswith("H1")
    assert any("best running shoe brand" in h for h in b["structure"])
    assert b["competitors"] == ["Adidas"]
    assert b["sources"] == [
        {"domain": "forbes.com", "answers": 4, "owner": "third_party"},
        {"domain": "shop.adidas.co.in", "answers": 2, "owner": "rival"},
    ]
    assert b["internal_links"] == ["https://nike.com/run"]
    assert set(b["evidence"]["prompt_ids"]) == {str(scene.vs), str(scene.best)}
    assert len(b["evidence"]["observation_ids"]) == 6
    assert b["note"] == NOTE


def test_evidence_is_capped(scene, owner, make_observation):
    for i in range(4, 4 + EVIDENCE_CAP):
        oid = make_observation(scene.org, scene.brand, status="done",
                               prompt_id=scene.vs, sample_index=i)
        with owner() as s, s.begin():
            s.add(m.Extraction(org_id=scene.org.id, observation_id=oid,
                               pipeline_version="2", model_used="t",
                               brand_mentioned=False,
                               absence_reason="competitor_dominance"))
            s.add(_mention(scene.org, oid, "competitor", scene.adidas))
    b = rows(scene)["cluster:comparison:running shoes"]["brief"]
    assert len(b["evidence"]["observation_ids"]) == EVIDENCE_CAP


def test_filters_narrow_clusters(scene):
    got = rows(scene, prompt_ids=[scene.vs])
    assert list(got) == ["cluster:comparison:running shoes"]
    assert got["cluster:comparison:running shoes"]["n"] == 4


def test_unlabelled_counts_active_prompts_missing_a_label(scene, owner):
    with tenant_session(scene.org.id) as s:
        assert unlabelled(s, scene.brand) == 1
    with owner() as s, s.begin():
        s.execute(update(m.Prompt).where(m.Prompt.id == scene.old)
                  .values(status="paused"))
    with tenant_session(scene.org.id) as s:
        assert unlabelled(s, scene.brand) == 0


def test_every_intent_has_a_page_type():
    assert set(PAGE_TYPES) == set(m.INTENTS)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/integration/test_gaps.py -q`
Expected: `ModuleNotFoundError: No module named 'bsi_core.gaps'`.

- [ ] **Step 3: Implement `gaps.py`**

```python
"""Content gaps (PRD F11, the gap half): (intent, topic) clusters of active
prompts, the brand's standing in each, and a model-free brief for the
clusters the brand is losing. Read-only SQL over stored answers."""

import uuid
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from . import models as m
from .competitors import _entities_and_hosts, owner_of
from .metrics import Filters, _where, rate
from .recommend import CONTENT_REASONS

EVIDENCE_CAP = 20
SOURCES_CAP = 10
LINKS_CAP = 10
NOTE = (
    "Page type and structure are templates by intent, not a judgement of "
    "the site."
)
PAGE_TYPES = {
    "comparison": "comparison page",
    "alternative": "alternatives page",
    "recommendation": "best-of round-up",
    "informational": "guide",
    "commercial": "category page",
    "transactional": "product page",
    "problem-based": "how-to",
    "persona-specific": "solution page",
    "industry-specific": "solution page",
    "geographic": "local page",
}
# Heading templates per page type; {q} rows repeat once per prompt.
STRUCTURES = {
    "comparison page": ["H1: {topic}: how the options compare", "H2: {q}",
                        "H2: Side-by-side table", "H2: Sources and evidence", "H2: FAQ"],
    "alternatives page": ["H1: Alternatives for {topic}", "H2: {q}",
                          "H2: How to choose", "H2: Sources and evidence"],
    "best-of round-up": ["H1: Best {topic}", "H2: Our picks", "H2: {q}",
                         "H2: How we chose", "H2: Sources and evidence"],
    "guide": ["H1: {topic}: a guide", "H2: {q}", "H2: Sources and evidence", "H2: FAQ"],
    "category page": ["H1: {topic}", "H2: {q}", "H2: Products", "H2: FAQ"],
    "product page": ["H1: {topic}", "H2: {q}", "H2: Specifications", "H2: FAQ"],
    "how-to": ["H1: How to {topic}", "H2: {q}", "H2: Step by step", "H2: Sources and evidence"],
    "solution page": ["H1: {topic}", "H2: {q}", "H2: Who it is for", "H2: Sources and evidence"],
    "local page": ["H1: {topic}", "H2: {q}", "H2: Locations and availability", "H2: FAQ"],
}
_BASE = (
    "o.status = 'done' AND p.status = 'active' "
    "AND p.intent IS NOT NULL AND p.topic IS NOT NULL"
)
_FROM = "FROM observation o JOIN prompt p ON p.id = o.prompt_id"


def unlabelled(s: Session, brand_id: uuid.UUID) -> int:
    return int(
        s.scalar(
            select(func.count()).select_from(m.Prompt).where(
                m.Prompt.brand_id == brand_id,
                m.Prompt.status == "active",
                (m.Prompt.intent.is_(None)) | (m.Prompt.topic.is_(None)),
            )
        )
        or 0
    )


def brief(c: dict[str, Any], brand: str) -> dict[str, Any]:
    """The model-free content brief for a gap cluster."""
    page_type = PAGE_TYPES[c["intent"]]
    queries = [p["text"] for p in c["prompts"]]
    structure: list[str] = []
    for h in STRUCTURES[page_type]:
        if "{q}" in h:
            structure += [h.format(q=q) for q in queries]
        else:
            structure.append(h.format(topic=c["topic"]))
    return {
        "target_queries": queries,
        "page_type": page_type,
        "structure": structure,
        "competitors": [r["name"] for r in c["rivals"]],
        "sources": [x for x in c["sources"] if x["owner"] != "brand"],
        "internal_links": c["brand_urls"],
        "evidence": {
            "prompt_ids": [str(p["prompt_id"]) for p in c["prompts"]],
            "observation_ids": [str(o) for o in c["_absent_obs"][:EVIDENCE_CAP]],
        },
        "note": NOTE,
    }


def clusters(
    s: Session, brand_id: uuid.UUID, f: Filters
) -> list[dict[str, Any]]:
    where, params = _where(brand_id, f)
    brand = s.get_one(m.Brand, brand_id).name
    entities, hosts = _entities_and_hosts(s, brand_id)
    brand_hosts = hosts[brand_id]
    rival_hosts = [h for e, hs in hosts.items() if e != brand_id for h in hs]
    answers = s.execute(
        text(
            "SELECT p.intent, p.topic, o.prompt_id, p.text, o.id, "
            "EXISTS (SELECT 1 FROM mention mn WHERE mn.observation_id = o.id "
            "  AND mn.entity_type = 'brand') AS present, "
            "EXISTS (SELECT 1 FROM mention mn JOIN competitor cp "
            "  ON cp.id = mn.entity_id WHERE mn.observation_id = o.id "
            "  AND mn.entity_type = 'competitor' AND cp.status = 'active') "
            "  AS rival, "
            "EXISTS (SELECT 1 FROM citation c WHERE c.observation_id = o.id "
            "  AND c.is_brand_owned) AS cited, "
            "e.absence_reason "
            f"{_FROM} LEFT JOIN extraction e ON e.observation_id = o.id "
            f"WHERE {where} AND {_BASE} "
            "ORDER BY p.intent, p.topic, o.prompt_id, o.requested_at DESC, o.id"
        ),
        params,
    ).all()
    rivals = s.execute(
        text(
            "SELECT p.intent, p.topic, cp.id, cp.name, "
            "count(DISTINCT o.id) AS answers "
            "FROM mention mn JOIN competitor cp ON cp.id = mn.entity_id "
            "JOIN observation o ON o.id = mn.observation_id "
            "JOIN prompt p ON p.id = o.prompt_id "
            f"WHERE {where} AND {_BASE} AND mn.entity_type = 'competitor' "
            "AND cp.status = 'active' "
            "GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 5 DESC, 4"
        ),
        params,
    ).all()
    sources = s.execute(
        text(
            "SELECT p.intent, p.topic, c.domain, count(DISTINCT o.id) AS answers "
            "FROM citation c JOIN observation o ON o.id = c.observation_id "
            "JOIN prompt p ON p.id = o.prompt_id "
            f"WHERE {where} AND {_BASE} "
            "GROUP BY 1, 2, 3 ORDER BY 1, 2, 4 DESC, 3"
        ),
        params,
    ).all()
    urls = s.execute(
        text(
            "SELECT DISTINCT p.intent, p.topic, c.url "
            "FROM citation c JOIN observation o ON o.id = c.observation_id "
            "JOIN prompt p ON p.id = o.prompt_id "
            f"WHERE {where} AND {_BASE} AND c.is_brand_owned ORDER BY 1, 2, 3"
        ),
        params,
    ).all()
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for r in answers:
        c = by_key.setdefault(
            (r.intent, r.topic),
            {"n": 0, "present": 0, "cited": 0, "rival_absent": 0,
             "reasons": Counter(), "prompts": {}, "_absent_obs": []},
        )
        c["n"] += 1
        c["present"] += r.present
        c["cited"] += r.cited
        p = c["prompts"].setdefault(r.prompt_id, {"prompt_id": r.prompt_id, "text": r.text, "n": 0, "absent": 0})
        p["n"] += 1
        if not r.present:
            p["absent"] += 1
            c["_absent_obs"].append(r.id)  # newest first (ORDER BY)
            c["rival_absent"] += r.rival
            if r.absence_reason:
                c["reasons"][r.absence_reason] += 1
    riv: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rivals:
        riv[(r.intent, r.topic)].append({"competitor_id": r.id, "name": r.name, "answers": r.answers})
    src: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in sources:
        src[(r.intent, r.topic)].append({"domain": r.domain, "answers": r.answers,
                                         "owner": owner_of(r.domain, brand_hosts, rival_hosts)})
    lnk: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in urls:
        lnk[(r.intent, r.topic)].append(r.url)
    out = []
    for (intent, topic), c in by_key.items():
        n, absent = c["n"], c["n"] - c["present"]
        top = riv[(intent, topic)][:1]
        top_rival = {**top[0], **rate(top[0]["answers"], n)} if top else None
        b = rate(c["present"], n)
        reasons = dict(c["reasons"])
        reason = c["reasons"].most_common(1)[0][0] if reasons else None
        gap = absent * 2 >= n and c["rival_absent"] >= 1 and reason in CONTENT_REASONS
        row: dict[str, Any] = {
            "intent": intent, "topic": topic, "key": f"cluster:{intent}:{topic}",
            "prompts": sorted(c["prompts"].values(),
                              key=lambda p: (-(p["absent"] / p["n"]), p["text"])),
            "n": n, "brand": b, "absent": absent, "rival_absent": c["rival_absent"],
            "reasons": reasons, "reason": reason,
            "rivals": riv[(intent, topic)], "top_rival": top_rival,
            "spread": (b["value"] - top_rival["value"]) if top_rival else None,
            "cited": rate(c["cited"], n),
            "sources": src[(intent, topic)][:SOURCES_CAP],
            "brand_urls": lnk[(intent, topic)][:LINKS_CAP],
            "gap": gap, "_absent_obs": c["_absent_obs"],
        }
        row["brief"] = brief(row, brand) if gap else None
        out.append(row)
    out.sort(key=lambda r: (r["spread"] is None, r["spread"] or 0.0, -r["n"], r["key"]))
    for r in out:
        del r["_absent_obs"]
    return out
```

Notes for the implementer: `top_rival` merges the rival dict with the rate keys (`name, competitor_id, answers, value, n, ci_low, ci_high`); the test compares against `{"name", "competitor_id", **rate(6, 8)}` — drop `answers` from `top_rival` or add it to the test expectation, consistently (prefer: keep `answers` out of `top_rival`). `reason` is an extra key (the top reason) the rule uses; the spec lists `reasons`; keep both. The `_absent_obs` key is internal and removed before return; `brief()` is called before removal.

- [ ] **Step 4: Run to verify pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/integration/test_gaps.py -q`
Expected: all pass. Fix `top_rival` shape per the note if the equality fails.

- [ ] **Step 5: Gate, commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/gaps.py tests/integration/test_gaps.py && git commit -m "feat(gaps): (intent, topic) clusters, the gap rule and a model-free brief

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: cluster-keyed `create_content`

**Files:**
- Modify: `packages/core/bsi_core/recommend.py` (`_content` ~L322, after `content_copy` ~L113, `generate` ~L540)
- Modify: `tests/integration/test_gaps.py`, `tests/unit/test_recommend_copy.py`

**Interfaces:**
- Consumes: `gaps.clusters` (Task 1; note `gaps` imports `CONTENT_REASONS` from `recommend`, so `recommend` must import `gaps` lazily inside `_content_clusters` to avoid a cycle — or move `CONTENT_REASONS` to `gaps.py` and re-export from `recommend`; prefer the lazy import with a comment).
- Produces: `cluster_copy(brand, intent, topic, page_type, worst, absent, n, rivals) -> (title, body)`; `_content_clusters(s, brand_id, brand, total) -> list[Candidate]`; `_content` restricted to unlabelled prompts.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_gaps.py`:

```python
from bsi_core.recommend import generate, refresh  # noqa: E402


def found(ids):
    with tenant_session(ids.org.id) as s:
        return {(c.type, c.subject_key): c for c in generate(s, ids.brand)}


def test_one_content_rec_per_gap_cluster_and_per_prompt_only_when_unlabelled(scene):
    recs = found(scene)
    content = {k: c for k, c in recs.items() if k[0] == "create_content"}
    assert set(content) == {
        ("create_content", "cluster:comparison:running shoes"),
        ("create_content", str(scene.old)),  # unlabelled: per-prompt rule
    }
    c = content[("create_content", "cluster:comparison:running shoes")]
    # total = 8 + 4 + 4 + 3 = 19 done answers on active prompts.
    assert (c.reach, c.pressure, c.feasibility) == (
        pytest.approx(6 / 19), pytest.approx(5 / 6), 0.4)
    assert c.priority == round(6 / 19 * 5 / 6 * 0.4, 4)
    assert c.title == "Publish a comparison page for running shoes (comparison)"
    assert "Adidas" in c.body and "Metric to watch:" in c.body
    ev = c.evidence
    assert ev["cluster"] == {"intent": "comparison", "topic": "running shoes"}
    assert (ev["reason"], ev["absent"], ev["n"]) == ("competitor_dominance", 6, 8)
    assert set(ev["prompt_ids"]) == {str(scene.vs), str(scene.best)}
    assert len(ev["observation_ids"]) == 6
    assert ev["page_type"] == "comparison page" and ev["internal_links"] == ["https://nike.com/run"]
    assert ev["competitors"] == ["Adidas"]


def test_labelling_a_prompt_moves_it_from_prompt_rec_to_cluster_rec(scene, owner):
    with tenant_session(scene.org.id) as s:
        refresh(s, scene.org.id, scene.brand)
        keys = set(s.scalars(select(m.Recommendation.subject_key).where(
            m.Recommendation.type == "create_content")))
    assert str(scene.old) in keys
    with owner() as s, s.begin():
        s.execute(update(m.Prompt).where(m.Prompt.id == scene.old)
                  .values(intent="comparison", topic="running shoes"))
    with tenant_session(scene.org.id) as s:
        refresh(s, scene.org.id, scene.brand)
        rows_ = s.scalars(select(m.Recommendation).where(
            m.Recommendation.type == "create_content")).all()
    assert {r.subject_key for r in rows_} == {"cluster:comparison:running shoes"}
    cluster = rows_[0]
    assert cluster.evidence["n"] == 11 and cluster.evidence["absent"] == 9


def test_an_accepted_prompt_rec_survives_labelling(scene, owner):
    with tenant_session(scene.org.id) as s:
        refresh(s, scene.org.id, scene.brand)
    with owner() as s, s.begin():
        s.execute(update(m.Recommendation).where(
            m.Recommendation.subject_key == str(scene.old)).values(status="accepted"))
        s.execute(update(m.Prompt).where(m.Prompt.id == scene.old)
                  .values(intent="informational", topic="history"))
    with tenant_session(scene.org.id) as s:
        refresh(s, scene.org.id, scene.brand)
        statuses = dict(s.execute(select(m.Recommendation.subject_key,
                                         m.Recommendation.status).where(
            m.Recommendation.type == "create_content")).all())
    assert statuses[str(scene.old)] == "accepted"
    assert "cluster:informational:history" in statuses  # 3/3 absent, Adidas named
```

In `tests/unit/test_recommend_copy.py`, add `cluster_copy` to the import and to `CASES`:

```python
CASES += [
    cluster_copy("Nike", "comparison", "running shoes", "comparison page",
                 ["nike vs adidas", "best running shoe brand"], 6, 8, ["Adidas", "Puma"]),
    cluster_copy("Nike", "informational", "sizing", "guide", ["shoe size chart"], 2, 3, []),
]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/integration/test_gaps.py tests/unit/test_recommend_copy.py -q`
Expected: ImportError on `cluster_copy`; the rule tests fail (per-prompt recs for labelled prompts, no cluster rec).

- [ ] **Step 3: Implement**

In `recommend.py`:

1. `_content`: add `"AND (p.intent IS NULL OR p.topic IS NULL) "` after `"AND p.status = 'active' "` and update its docstring: "Per-prompt rule for prompts without labels; labelled prompts are handled per cluster by `_content_clusters`."
2. After `content_copy`:

```python
def cluster_copy(
    brand: str,
    intent: str,
    topic: str,
    page_type: str,
    worst: list[str],
    absent: int,
    n: int,
    rivals: list[str],
) -> tuple[str, str]:
    asks = " and ".join(f"“{q}”" for q in worst[:2])
    led = f" Rivals named there: {names(rivals)}." if rivals else ""
    return (
        f"Publish a {page_type} for {topic} ({intent})",
        f"{brand} is absent from {absent} of {n} answers in this cluster, "
        f"led by {asks}.{led} A {page_type} that answers these prompts "
        "directly gives engines something of the brand's own to retrieve. "
        f"Metric to watch: {brand}'s mention rate on the cluster's prompts.",
    )
```

3. After `_content`:

```python
def _content_clusters(
    s: Session, brand_id: uuid.UUID, brand: str, total: int
) -> list[Candidate]:
    """One candidate per gap cluster of labelled prompts (PRD F11)."""
    from .gaps import clusters  # gaps imports CONTENT_REASONS from here

    out = []
    for c in clusters(s, brand_id, Filters()):
        if not c["gap"]:
            continue
        b = c["brief"]
        title, body = cluster_copy(
            brand, c["intent"], c["topic"], b["page_type"],
            b["target_queries"], c["absent"], c["n"], b["competitors"],
        )
        out.append(
            Candidate(
                "create_content",
                c["key"],
                title,
                body,
                {
                    **b,
                    "prompt_ids": b["evidence"]["prompt_ids"],
                    "observation_ids": b["evidence"]["observation_ids"],
                    "cluster": {"intent": c["intent"], "topic": c["topic"]},
                    "reason": c["reason"],
                    "absent": c["absent"],
                    "n": c["n"],
                },
                c["absent"] / total,
                c["rival_absent"] / c["absent"],
            )
        )
    return out
```

4. In `generate`, inside `if total:` add `*_content_clusters(s, brand_id, brand, total),` after `_content`. Update the module docstring's list of rules in one sentence.

- [ ] **Step 4: Run to verify pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/integration/test_gaps.py tests/integration/test_recommend.py tests/unit/test_recommend_copy.py -q`
Expected: all pass. `test_recommend.py`'s `world` prompts have no labels, so its per-prompt expectations are unchanged.

- [ ] **Step 5: Gate, commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/recommend.py tests/integration/test_gaps.py tests/unit/test_recommend_copy.py && git commit -m "feat(recommend): one create_content per gap cluster; per-prompt only when unlabelled

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `label_prompts` job and the two routes

**Files:**
- Modify: `packages/core/bsi_core/suggest.py` (after `PROMPT_JOB_MICROS`), `apps/workers/bsi_workers/worker.py` (`JOB_ESTIMATES` ~L45, `runners` ~L403)
- Create: `apps/api/bsi_api/routers/clusters.py`; Modify: `routers/prompts.py` (after `/suggest`), `main.py`, `schemas.py`
- Create: `tests/integration/test_api_gaps.py`; Modify: `tests/integration/test_isolation.py` (`CASES`), `tests/integration/test_worker.py`

**Interfaces:**
- Produces: `POST /v1/brands/{id}/prompts/label` → 202 `QueuedOut`; `GET /v1/brands/{id}/clusters/gaps` → `ClustersOut{unlabelled: int, clusters: list[ClusterOut]}`; job kind `label_prompts` with estimate `LABEL_JOB_MICROS = 10_000`.

- [ ] **Step 1: Write the failing tests**

`tests/integration/test_api_gaps.py`:

```python
from bsi_core import models as m
from sqlalchemy import update

from tests.integration.test_gaps import scene  # noqa: F401


def test_clusters_route_returns_numbers_and_briefs(client, scene):  # noqa: F811
    r = client.get(f"/v1/brands/{scene.brand}/clusters/gaps", headers=scene.org.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unlabelled"] == 1
    keys = [c["key"] for c in body["clusters"]]
    assert keys[0] == "cluster:comparison:running shoes"
    gap = body["clusters"][0]
    assert gap["gap"] is True and gap["brief"]["page_type"] == "comparison page"
    assert gap["brand"]["n"] == 8 and gap["top_rival"]["name"] == "Adidas"
    assert body["clusters"][-1]["brief"] is None


def test_clusters_route_honours_filters(client, scene):  # noqa: F811
    r = client.get(f"/v1/brands/{scene.brand}/clusters/gaps",
                   params={"prompt_ids": str(scene.vs)}, headers=scene.org.headers)
    assert [c["key"] for c in r.json()["clusters"]] == ["cluster:comparison:running shoes"]


def test_label_route_queues_a_job(client, owner, scene):  # noqa: F811
    r = client.post(f"/v1/brands/{scene.brand}/prompts/label", headers=scene.org.headers)
    assert r.status_code == 202, r.text
    with owner() as s:
        job = s.get(m.Job, r.json()["job_id"])
    assert (job.kind, job.status) == ("label_prompts", "queued")
    again = client.post(f"/v1/brands/{scene.brand}/prompts/label", headers=scene.org.headers)
    assert again.json()["job_id"] == r.json()["job_id"]


def test_label_route_on_an_archived_brand_is_409(client, owner, scene):  # noqa: F811
    with owner() as s, s.begin():
        s.execute(update(m.Brand).where(m.Brand.id == scene.brand).values(status="archived"))
    r = client.post(f"/v1/brands/{scene.brand}/prompts/label", headers=scene.org.headers)
    assert r.status_code == 409


def test_unknown_brand_is_404(client, make_org):
    org = make_org()
    zero = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/v1/brands/{zero}/clusters/gaps", headers=org.headers).status_code == 404
    assert client.post(f"/v1/brands/{zero}/prompts/label", headers=org.headers).status_code == 404
```

`test_isolation.py` `CASES`, add:
```python
    ("GET", "/v1/brands/{b}/clusters/gaps", None),
    ("POST", "/v1/brands/{b}/prompts/label", None),
```

`tests/integration/test_worker.py`, after `test_a_queued_prompts_job_runs_and_is_marked_done`:

```python
def test_a_label_job_labels_only_unlabelled_prompts_and_adds_none(
    owner, make_org, make_brand, make_observation
):
    import json

    org = make_org()
    bid = make_brand(org)
    a = make_observation(org, bid, status="done", text="alpha")
    b = make_observation(org, bid, status="done", text="beta")
    with owner() as s, s.begin():
        pa = s.get(m.Observation, a).prompt_id
        pb = s.get(m.Observation, b).prompt_id
        s.execute(update(m.Prompt).where(m.Prompt.id == pa)
                  .values(intent="informational", topic="done"))
    job_id = _job(owner, org, bid, "label_prompts", "queued")
    seen = []

    def generator(prompt, schema, temperature):
        seen.append(prompt)
        return json.dumps({"prompts": [
            {"text": "beta", "intent": "comparison", "topic": " Sizing "}]}), 700, "fake"

    def embedder(texts):
        # prompt.embedding is vector(768): the shared _spender's [1.0]
        # vectors would not fit the column.
        return [[0.0] * 767 + [1.0] for _ in texts], 55

    assert worker.process_job(FakeAdapter(), generator, embedder) is True
    job = _load_job(owner, job_id)
    assert (job.status, job.error) == ("done", None)
    assert job.cost_micros == 700 + 55
    assert len(seen) == 1 and "beta" in seen[0]  # alpha is labelled already
    # (alpha still appears in the request's existing-prompts context.)
    with owner() as s:
        rows = {p.text: p for p in s.scalars(select(m.Prompt).where(m.Prompt.brand_id == bid))}
    assert len(rows) == 2  # nothing generated
    assert (rows["beta"].intent, rows["beta"].topic) == ("comparison", "sizing")
    assert rows["alpha"].topic == "done"
    assert rows["alpha"].embedding is not None and rows["beta"].embedding is not None


def test_label_job_estimate_is_budget_gated(owner, make_org, make_brand):
    assert worker.JOB_ESTIMATES["label_prompts"] == LABEL_JOB_MICROS == 10_000
```

(import `LABEL_JOB_MICROS` from `bsi_core.suggest` at the top of `test_worker.py`; reuse the file's existing `_job`, `_spender`, `_load_job`, `FakeAdapter`.) Note: `suggest_prompts` embeds every prompt lacking a vector, including the already-labelled "alpha" — that is the existing backfill behaviour and the test asserts it.

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/integration/test_api_gaps.py tests/integration/test_worker.py -q -k "label or clusters or unknown_brand"`
Expected: 404/405 on the routes; `KeyError: 'label_prompts'` / unknown kind in the worker test.

- [ ] **Step 3: Implement**

`suggest.py`, after `PROMPT_JOB_MICROS`:
```python
# Labelling only (count=0): one Flash-Lite label call plus embeddings for
# up to MAX_BACKFILL prompts; no generation.
LABEL_JOB_MICROS = 10_000
```

`worker.py`: import `LABEL_JOB_MICROS`; `JOB_ESTIMATES["label_prompts"] = LABEL_JOB_MICROS`; runner
`"label_prompts": lambda: suggest_prompts(org_id, brand_id, 0, meter.generate, meter.embed),`.

`schemas.py`, after `ClusterOut` (the existing count model — keep it; name the new ones distinctly):

```python
class ClusterPromptOut(BaseModel):
    prompt_id: uuid.UUID
    text: str
    n: int
    absent: int


class ClusterRivalOut(BaseModel):
    competitor_id: uuid.UUID
    name: str
    answers: int


class TopRivalOut(Rate):
    competitor_id: uuid.UUID
    name: str


class BriefEvidenceOut(BaseModel):
    prompt_ids: list[uuid.UUID]
    observation_ids: list[uuid.UUID]


class BriefOut(BaseModel):
    target_queries: list[str]
    page_type: str
    structure: list[str]
    competitors: list[str]
    sources: list[CitingDomainOut]
    internal_links: list[str]
    evidence: BriefEvidenceOut
    note: str


class GapClusterOut(BaseModel):
    intent: str
    topic: str
    key: str
    prompts: list[ClusterPromptOut]
    n: int
    brand: Rate
    absent: int
    rival_absent: int
    reasons: dict[str, int]
    reason: str | None
    rivals: list[ClusterRivalOut]
    top_rival: TopRivalOut | None
    spread: float | None
    cited: Rate
    sources: list[CitingDomainOut]
    brand_urls: list[str]
    gap: bool
    brief: BriefOut | None


class ClustersOut(BaseModel):
    unlabelled: int
    clusters: list[GapClusterOut]
```

`routers/clusters.py`:
```python
"""Content-gap clusters (PRD F11)."""

import uuid
from typing import Any

from bsi_core.gaps import clusters, unlabelled
from bsi_core.metrics import Filters
from fastapi import APIRouter, Depends

from ..deps import TENANT, Ctx, brand_or_404
from ..schemas import ClustersOut
from .metrics import filters

router = APIRouter(prefix="/brands/{brand_id}", tags=["clusters"])


@router.get("/clusters/gaps", response_model=ClustersOut)
def list_gap_clusters(
    brand_id: uuid.UUID, f: Filters = Depends(filters), c: Ctx = TENANT
) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    return {
        "unlabelled": unlabelled(c.s, brand_id),
        "clusters": clusters(c.s, brand_id, f),
    }
```
Register in `main.py`. In `routers/prompts.py` after `/suggest`:
```python
@router.post("/label", status_code=202)
def label(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
    """Label and embed prompts that lack intent, topic or embedding."""
    return queue_suggestion(c, brand_id, "label_prompts", {})
```
Route order: `/clusters/gaps` is registered on a different router from `brands.py`'s `/clusters`; FastAPI matches the longer literal path, and the existing `GET /{brand_id}/clusters` has no sub-path parameter, so no shadowing.

- [ ] **Step 4: Run to verify pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/integration/test_api_gaps.py tests/integration/test_worker.py tests/integration/test_isolation.py tests/integration/test_api_typed.py -q`
Expected: all pass.

- [ ] **Step 5: Regenerate types, gate, commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gen && git -C /Users/vineet/Downloads/ADK/bsi-platform add apps/web/openapi.json apps/web/src/lib/schema.d.ts
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/suggest.py apps/workers/bsi_workers/worker.py apps/api/bsi_api/routers/clusters.py apps/api/bsi_api/routers/prompts.py apps/api/bsi_api/main.py apps/api/bsi_api/schemas.py tests/integration/test_api_gaps.py tests/integration/test_isolation.py tests/integration/test_worker.py && git commit -m "feat(api): gap clusters route and a budget-gated label_prompts job

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Clusters tab and multi-prompt evidence

**Files:**
- Create: `apps/web/src/app/(app)/b/[id]/clusters/page.tsx`, `clusters/actions.ts`
- Modify: `b/[id]/layout.tsx` (tab after Prompts), `b/[id]/recommendations/page.tsx` (evidence), `lib/types.ts` (`export type Clusters = S["ClustersOut"];`), `lib/format.ts` (`labelNote` = reuse `auditNote` text map; add a `LABEL_NOTES` with "Queued; the worker labels them within a minute." for queued/running, "Already queued this hour." for done, "Queued again after a failed run." for failed, and `labelNote()`)

- [ ] **Step 1: actions.ts** (mirror `site/actions.ts`): `labelPrompts(form)` POSTs `/brands/${id}/prompts/label` and redirects to `/b/${id}/clusters?queued=${status}`.

- [ ] **Step 2: page.tsx**

```tsx
import Link from "next/link";
import { Filters } from "@/components/Filters";
import { api } from "@/lib/api";
import { apiQuery, ciText, labelNote, pct, pts, type Params } from "@/lib/format";
import type { Clusters } from "@/lib/types";
import { labelPrompts } from "./actions";

export default async function ClustersPage({ params, searchParams }: {
  params: Promise<{ id: string }>; searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const data = await api<Clusters>(`/brands/${id}/clusters/gaps${apiQuery(sp)}`);
  const gaps = data.clusters.filter((c) => c.gap).length;
  return (
    <>
      <Filters sp={sp} />
      {data.unlabelled > 0 && (
        <form action={labelPrompts} className="row card">
          <input type="hidden" name="brand_id" value={id} />
          <span>{data.unlabelled} prompts have no intent or topic yet, so they are not in any cluster.</span>
          <button className="primary">Label now</button>
          <span className="muted">{labelNote(sp.queued)}</span>
        </form>
      )}
      <p className="muted">{data.clusters.length} clusters · {gaps} gaps · a gap: the brand is absent from at least half the answers and a rival is named in one</p>
      {data.clusters.length === 0 && <p>No labelled prompts with answers for these filters.</p>}
      {data.clusters.length > 0 && (
        <table>
          <thead><tr><th>Cluster</th><th>Prompts</th><th>n</th><th>Brand</th><th>Top rival</th><th>Absent</th><th>Spread</th></tr></thead>
          <tbody>
            {data.clusters.map((c) => (
              <tr key={c.key}>
                <td>
                  <span className="tag">{c.intent}</span> {c.topic}{" "}
                  {c.gap && <span className="tag down">gap</span>}
                  {c.brief && (
                    <details>
                      <summary>Brief: {c.brief.page_type}</summary>
                      <p className="muted">{c.brief.note}</p>
                      <strong>Target queries</strong>
                      <ul>{c.brief.target_queries.map((q) => <li key={q}>{q}</li>)}</ul>
                      <strong>Structure</strong>
                      <ul>{c.brief.structure.map((h, i) => <li key={i}>{h}</li>)}</ul>
                      <p>Competitors: {c.brief.competitors.join(", ") || "—"}</p>
                      <p>Sources: {c.brief.sources.map((s) => `${s.domain} (${s.answers}, ${s.owner})`).join(", ") || "—"}</p>
                      <p>Internal links: {c.brief.internal_links.length ? c.brief.internal_links.map((u) => <a key={u} href={u} style={{ marginRight: 6 }}>{u}</a>) : "none cited yet"}</p>
                      <p className="muted">Evidence: {c.brief.evidence.observation_ids.map((o) => <Link key={o} href={`/o/${o}`} style={{ marginRight: 6 }}>{o.slice(0, 8)}</Link>)}</p>
                    </details>
                  )}
                </td>
                <td>{c.prompts.map((p) => <div key={p.prompt_id}><Link href={`/b/${id}/prompts/${p.prompt_id}`}>{p.text}</Link> <span className="muted">{p.absent}/{p.n} absent</span></div>)}</td>
                <td>{c.n}</td>
                <td>{pct(c.brand.value)}<div className="muted">{ciText(c.brand)}</div></td>
                <td>{c.top_rival ? `${c.top_rival.name} ${pct(c.top_rival.value)}` : "—"}</td>
                <td>{c.absent}/{c.n}</td>
                <td className={c.spread == null ? "muted" : c.spread < 0 ? "down" : "up"}>{pts(c.spread)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
```
`filter(...).length` is a count for a caption, not a statistic; the API's order is kept. Internal links: `href` values come from stored citation URLs on brand-owned domains; render with `rel="noreferrer"`.

- [ ] **Step 3: Recommendations evidence.** In `recommendations/page.tsx`, replace `{prompts.length > 1 && \`${prompts.length} prompts\`}` with a list of links, one per prompt id (`<Link href={`/b/${id}/prompts/${p}`}>{p.slice(0, 8)}</Link>` separated by spaces), and, when `ev.page_type` exists, a muted line "Brief: {page_type}". Extend the local `Evidence` type with `page_type?: string`.

- [ ] **Step 4: Layout tab** after Prompts: `<Link href={`/b/${id}/clusters`}>Clusters</Link>`.

- [ ] **Step 5: Gate, commit**

`npm run gate` must print "Compiled successfully" with no warnings.
```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add "apps/web/src/app/(app)/b/[id]/clusters" "apps/web/src/app/(app)/b/[id]/layout.tsx" "apps/web/src/app/(app)/b/[id]/recommendations/page.tsx" apps/web/src/lib/types.ts apps/web/src/lib/format.ts && git commit -m "feat(web): Clusters tab with gap briefs; prompt links on cluster recommendations

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Live labelling of Run 1, findings, index

**Files:** Create `docs/findings-slice10.md`; modify `docs/README.md`.

- [ ] **Step 1: Label Run 1 (approved spend ≈ $0.01).** With Docker up and `.env` loaded (`set -a && source .env && set +a`): queue via the API with Run 1's key from the handoff (`curl -X POST -H "Authorization: Bearer <key>" http://localhost:8000/v1/brands/34db213a-f484-4991-a969-c52cfa5e1c10/prompts/label`), or `enqueue_job` in a `system_session`; run one worker pass (`uv run python -c "import bsi_workers.worker as w; ..."` calling `process_job` once with the real adapter/generator/embedder as `main()` builds them — read `main()` for the constructors). Confirm: `SELECT count(intent), count(topic), count(embedding) FROM prompt WHERE brand_id=...` → 20|20|20; the job's `cost_micros`; the spend ledger total (`scripts/` has the spend query used in earlier findings).
- [ ] **Step 2: Read-only calls.** In a tenant session: `gaps.clusters()`, `unlabelled()`, and `generate()` + `top_by_type()`; roll back / do not call `refresh`. Confirm `recommendation`, `task`, `site_audit` are `0|0|0` afterwards.
- [ ] **Step 3: `docs/findings-slice10.md`** (shape of findings-slice9): sources and method; the 20 labels (intent, topic per prompt); the clusters table (key, prompts, n, brand rate with interval, top rival, absent, spread, gap); each gap's brief; where the cluster `create_content` recs land in `top_by_type` against the other types; how many per-prompt recs the cluster rule replaced; label quality remarks (topics too fine/coarse); deferred (URL optimizer; embedding merging; relabelling; per-engine cluster metrics; stored clusters; alerts); spend (job cost, new total).
- [ ] **Step 4: README** Slice 10 section (spec, plan, findings rows, same table shape as Slice 9).
- [ ] **Step 5: Gate, commit**
```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add docs/findings-slice10.md docs/README.md && git commit -m "docs: slice 10 findings and index

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After the tasks

Whole-branch review, one fix wave, scoped re-review, then `finishing-a-development-branch`: push, PR via `GH_TOKEN=$(gh auth token -u aiagencyindia-lab) gh pr create …` (body ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`), `gh pr checks --watch`, read the run log. Merge only when the user says so.

## Verification

- Gate green locally and in CI.
- Run 1 labelled 20/20; the Clusters page lists its clusters (`curl -b "bsi_key=…" http://localhost:3000/b/<id>/clusters`, optional); dev rec/task/audit tables still empty; spend recorded.
