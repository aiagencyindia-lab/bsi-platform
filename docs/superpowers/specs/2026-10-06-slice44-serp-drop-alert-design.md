# Slice 44 design: the Brand SERP drop alert (PRD F15)

## Context

Codebase facts: main `ae465d3`, checked 2026-10-06.

PRD F15's alerts line ("Alerts on rolling windows only: ... Brand SERP change") names a "Brand SERP change" alert; the Brand SERP audit itself is F09. Slice 43 made the Brand SERP audit weekly, so each active brand with a declared domain now gets a `brand` and a `reviews` page about once a week, stored in `serp_audit`. This slice adds the alert: when the brand's own-site results on its Brand SERP fall, and the fall is seen on two later pages. Its "window" is the run of pages it compares, from the baseline page to the latest, so it never fires on one page.

Facts the design rests on:
- packages/core/bsi_core/alerts.py: three detectors (`detect_mention_drop`, `detect_competitor_shift`, `detect_new_source`) each take `(s, brand_id, to)` and return `Candidate`s; `scan()` runs `DETECTORS` under a per-brand advisory lock, skips a candidate when `is_duplicate()` finds an alert of the same `(brand, type, subject_key)` whose `window_to` is later than the candidate's `window_from`, and stores the rest. The worker's `scan_due_alerts()` runs `scan()` daily for every active brand; `POST /brands/{id}/alerts/scan` runs it on demand.
- The alert type list lives in four places: `ALERT_TYPES` in models.py (checked against the live `ck_alert_type` constraint by tests/integration/test_constraints.py), migration 0016's constraint, `ALERT_LABEL` in reports.py (the reports' "Alerts in period" table), and `ALERT_KIND` in apps/web/src/lib/format.ts (pinned by format.test.ts).
- packages/core/bsi_core/serp.py: `ownership(results)` returns `(official organic results, all organic results)`; a result is typed `official` at fetch time when its host matches a declared domain.
- Page variation: on 2026-10-05 the same query returned 0 of 3, then 1 of 6, own-site organic results 20 minutes apart (findings-slice37 §2). Dev holds one good page per kind for each of two brands, and every one of them has 0 own-site results: Walkaroo's 2026-10-05 pages are 0 of 3 and 0 of 2 (the 1-of-6 page was a diagnostic call, never stored), and BSOAgentTestBrand's 2026-10-06 pages have no walkaroo.in result (findings-slice43 §2).

Classification: **architectural** — a new alert type that changes the type list the database constraint, the reports and the web app depend on. It was the first line of the first brainstorming reply, after the skill loaded and before any exploration, and the session model (Opus 5.5) was said in the same reply.

Decisions approved in chat (brainstorming on Opus 5.5, 2026-10-06), each after approaches with trade-offs and a recommendation written in a chat message before the question:
1. What counts: the brand's own-site results fall; over page features (Knowledge Panel, AI Overview, top position, new review sites), or overall page turnover.
2. Confirmation: two later pages, each at least a day apart, both below a baseline page at least a day before them; over a confirming re-run, or comparing averages.
3. Size: the own-site result count falls (the alert text still shows the share); over a 15-point share drop, or only the site leaving page one.
4. Build: a fourth detector in the daily scan; over checking after each SERP job, or a separate feed outside alerts.
5. A renamed brand: only pages with the latest page's query are compared, as with the locale; over leaving it and documenting it, or putting the query into the alert's subject. Asked after the spec review (finding M3).
6. Live check: none in this slice; over a seeded check on dev, or manual Walkaroo audits a day apart. First chosen with Section 3 on wrong facts (an earliest alert of 2026-10-19), then asked again after the spec review (finding I3) with the facts above.

Design Sections 1, 2 and 3 were approved in chat, the text of each shown in its own message before its approval question.

## Design

### The rule

For each brand and each query kind, `detect_serp_drop(s, brand_id, to)`:
1. Takes the brand's good pages of that kind fetched before `to`: no error, and at least one organic result. Only pages with the newest page's query, country and language are compared, so a renamed brand or a new locale starts a new series.
2. Walks back from the newest: L, the latest page; P, the newest page at least `SERP_GAP` (1 day) before L; B, the baseline, the newest page at least 1 day before P. Pages in between are skipped. With fewer than three, there is no candidate.
3. Counts each page's organic `official` results, as `ownership()` does.
4. Fires when owned(L) < owned(B) and owned(P) < owned(B).

Consequences:
- Three pages a day or more apart are needed: about two weeks of weekly pages for a new brand. The baseline must have at least one own-site result, and no page on dev has one, so no page stored today can start an alert. With weekly pages only, Walkaroo needs a page showing walkaroo.in on 2026-10-12 or later and two lower pages after it: 2026-10-26 at the earliest, if the worker runs and Google shows the site.
- After an alert, the next week's page is judged against a baseline that is already low, so the same drop does not fire again; a recovery and a new drop fire against a new baseline.
- "Run audit now" pages count, but the one-day gap stops two quick presses confirming each other.
- Results are typed when a page is fetched, so declaring or removing a domain later does not re-type old pages.
- A renamed brand's pages under the old name are not compared with the new name's, so a rename means about two weeks with no alert.
- No lookback limit: after a gap in audits, the next two pages are judged against the last page before the gap; the alert's dates show the span.

### The alert

- Type `serp_drop`, labelled "Brand SERP drop"; subject `{kind}:{country}:{language}`; `window_from` = B's `fetched_at`, `window_to` = L's.
- Duplicates: the same pages scanned again are suppressed; a further drop (for example 2 → 1, then 1 → 0) or a drop after a recovery is new, because its baseline is at or after the earlier alert's latest page and `is_duplicate` compares with a strict "later than".
- Title, for example: `Own-site results for "Walkaroo" (IN/en) fell from 1 of 6 to 0 of 5 (0 of 3 on the page before)`.
- Detail: `kind`, `query`, `country`, `language`, `pages` (baseline, previous, latest: `serp_audit_id`, `fetched_at`, `owned`, `organic`), and empty `prompt_ids` and `observation_ids`.
- Delivery: unchanged; the webhook body already carries `type`, `title`, `subject_key` and `detail`.

### Code

packages/core/bsi_core/alerts.py, as a diff against main `ae465d3`:

```diff
@@ -1,7 +1,8 @@
 """Alerts (PRD F15, alerts only): changes worth telling the operator about.
 
-Each detector reads rolling windows of stored answers, so nothing here can
-fire from a single observation. `to` is a parameter everywhere so tests
-are deterministic. Copy states what was observed and never promises.
+Each detector reads rolling windows of stored answers, or a run of stored
+Brand SERP pages, so nothing here can fire from a single observation or
+page. `to` is a parameter everywhere so tests are deterministic. Copy
+states what was observed and never promises.
 """
 
@@ -23,4 +24,5 @@ from .matching import is_owned
 from .metrics import Filters, brand_deltas
 from .recommend import _rival_domains
+from .serp import ownership
 
 DROP_DAYS = 7
@@ -31,4 +33,7 @@ SOURCE_DAYS = 7
 # authority score, so a count of citing answers stands in for it.
 NEW_SOURCE_MIN_ANSWERS = 5
+# Pages compared by the Brand SERP drop alert are at least this far
+# apart, so two quick audits never confirm each other.
+SERP_GAP = timedelta(days=1)
 
 
@@ -192,11 +197,108 @@ def detect_new_source(
 
 
-DETECTORS = (detect_mention_drop, detect_competitor_shift, detect_new_source)
+def serp_copy(
+    query: str, country: str, language: str, pages: list[dict[str, Any]]
+) -> str:
+    """pages: baseline, previous, latest."""
+    base, prev, last = pages
+    return (
+        f'Own-site results for "{query}" ({country}/{language}) fell from '
+        f"{base['owned']} of {base['organic']} to "
+        f"{last['owned']} of {last['organic']} "
+        f"({prev['owned']} of {prev['organic']} on the page before)"
+    )
+
+
+def detect_serp_drop(
+    s: Session, brand_id: uuid.UUID, to: datetime
+) -> list[Candidate]:
+    """A Brand SERP page whose own-site organic results fell, confirmed
+    by the page before it: the latest page (L), the newest page at least
+    SERP_GAP before it (P) and the newest at least SERP_GAP before P (B,
+    the baseline). Fires when L and P both have fewer than B.
+
+    Only good pages count: no error and at least one organic result. Only
+    pages with the latest page's query, country and language are compared,
+    so a renamed brand or a new locale starts a new series.
+    """
+    # ponytail: loads every page of the brand; weekly pages stay few. Add
+    # a lookback window if the table grows.
+    rows = s.scalars(
+        select(m.SerpAudit)
+        .where(
+            m.SerpAudit.brand_id == brand_id,
+            m.SerpAudit.error.is_(None),
+            m.SerpAudit.fetched_at < to,
+        )
+        .order_by(m.SerpAudit.fetched_at.desc(), m.SerpAudit.id.desc())
+    ).all()
+    out = []
+    for kind in m.SERP_KINDS:
+        pages = [(r, *ownership(r.results)) for r in rows if r.kind == kind]
+        pages = [p for p in pages if p[2] > 0]
+        if not pages:
+            continue
+        latest = pages[0][0]
+        here = (latest.query, latest.country, latest.language)
+        picked = [pages[0]]
+        for p in pages[1:]:
+            if (p[0].query, p[0].country, p[0].language) != here:
+                continue
+            if picked[-1][0].fetched_at - p[0].fetched_at >= SERP_GAP:
+                picked.append(p)
+                if len(picked) == 3:
+                    break
+        if len(picked) < 3:
+            continue
+        (last, last_owned, _), (_, prev_owned, _), (base, base_owned, _) = (
+            picked
+        )
+        if not (last_owned < base_owned and prev_owned < base_owned):
+            continue
+        detail_pages = [
+            {
+                "serp_audit_id": r.id,
+                "fetched_at": r.fetched_at,
+                "owned": owned,
+                "organic": organic,
+            }
+            for r, owned, organic in reversed(picked)
+        ]
+        out.append(
+            Candidate(
+                "serp_drop",
+                f"{kind}:{last.country}:{last.language}",
+                serp_copy(
+                    last.query, last.country, last.language, detail_pages
+                ),
+                {
+                    "kind": kind,
+                    "query": last.query,
+                    "country": last.country,
+                    "language": last.language,
+                    "pages": detail_pages,
+                    "prompt_ids": [],
+                    "observation_ids": [],
+                },
+                base.fetched_at,
+                last.fetched_at,
+            )
+        )
+    return out
+
+
+DETECTORS = (
+    detect_mention_drop,
+    detect_competitor_shift,
+    detect_new_source,
+    detect_serp_drop,
+)
 
 
 def is_duplicate(s: Session, brand_id: uuid.UUID, c: Candidate) -> bool:
     """An alert for the same subject whose window ends after this one
-    starts. Windows of a type have one length, so that is "younger than
-    the window"."""
+    starts. For the fixed-length windows that is "younger than the
+    window"; for serp_drop it means the alert's latest page is after
+    this one's baseline page."""
     return (
         s.execute(
```

packages/core/bsi_core/models.py:

```diff
@@ -58,5 +58,10 @@ IMPACT_LABELS = (
     "not_comparable",
 )
-ALERT_TYPES = ("mention_drop", "competitor_shift", "new_source")
+ALERT_TYPES = (
+    "mention_drop",
+    "competitor_shift",
+    "new_source",
+    "serp_drop",
+)
 REPORT_TYPES = ("cmo", "seo", "content", "pr", "agency")
 REPORT_CADENCES = ("off", "weekly", "monthly")
@@ -458,4 +463,5 @@ class Alert(Tenant, Base):
     type: Mapped[str]
     # mention_rate | <competitor_id>:<up|down> | <domain>
+    # | <kind>:<country>:<language> (serp_drop)
     subject_key: Mapped[str]
     title: Mapped[str]
```

packages/core/bsi_core/reports.py:

```diff
@@ -62,4 +62,5 @@ ALERT_LABEL = {
     "competitor_shift": "Competitor shift",
     "new_source": "New source",
+    "serp_drop": "Brand SERP drop",
 }
 # Client-facing wording for source owners; every other non-audit code
```

migrations/versions/0025_serp_drop_alert.py (new):

```python
"""alert type serp_drop: the Brand SERP drop alert (slice 44, PRD F15)"""

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

OLD = ("mention_drop", "competitor_shift", "new_source")
NEW = (*OLD, "serp_drop")


def _check(types: tuple[str, ...]) -> None:
    op.drop_constraint("ck_alert_type", "alert")
    op.create_check_constraint(
        "ck_alert_type",
        "alert",
        "type IN (" + ", ".join(f"'{t}'" for t in types) + ")",
    )


def upgrade() -> None:
    _check(NEW)


def downgrade() -> None:
    op.execute("DELETE FROM alert WHERE type = 'serp_drop'")
    _check(OLD)
```

### Web

apps/web/src/lib/format.ts and its test:

```diff
@@ -211,4 +211,5 @@ export const ALERT_KIND: Record<string, string> = {
   competitor_shift: "Competitor shift",
   new_source: "New source",
+  serp_drop: "Brand SERP drop",
 };
 
```

```diff
@@ -179,4 +179,5 @@ test("ALERT_KIND labels every alert type", () =>
     competitor_shift: "Competitor shift",
     new_source: "New source",
+    serp_drop: "Brand SERP drop",
   }));
 
```

apps/web/src/app/(app)/b/[id]/alerts/page.tsx: the explanation names Google pages, and a `serp_drop` alert links to the brand's Brand SERP page:

```diff
@@ -74,5 +74,6 @@ export default async function Alerts({
       <p className="muted">
         The worker scans every active brand daily over rolling windows; no
-        alert comes from a single answer. Each new alert is posted to the
+        alert comes from a single answer or a single Google page. Each new
+        alert is posted to the
         webhook as JSON with a <code>text</code> field. With a signing
         secret set, each POST carries{" "}
@@ -121,4 +122,7 @@ export default async function Alerts({
                       ))}
                     {typeof domain === "string" && <code>{domain}</code>}
+                    {a.type === "serp_drop" && (
+                      <Link href={`/b/${id}/serp`}>Brand SERP</Link>
+                    )}
                   </td>
                   <td className="muted">{delivery(a)}</td>
```

No API schema change, so no `npm run gen`.

Out of scope: a Brand SERP section in the reports; alert types for other SERP changes (Knowledge Panel, AI Overview, new review or competitor sites); the `negative` result type; per-brand alert settings.

## Testing

tests/integration/test_alerts.py gains the imports `pytest`, `detect_serp_drop`, `ALERT_LABEL` and `IntegrityError`, and these helpers and tests (15 tests, one parametrized over 4 cases, so 18 test items). No test calls the network. Not tested: the alerts page's link and copy line (static markup), and the claim that a later domain change does not re-type old pages (it holds because the stored `result_type` is read).

```python
T0 = datetime(2026, 10, 5, 12, tzinfo=UTC)
WEEK = timedelta(days=7)
LATER = T0 + timedelta(days=60)


def _serp(
    owner,
    org,
    bid,
    at,
    owned,
    organic=6,
    *,
    kind="brand",
    error=None,
    country="IN",
    language="en",
    query=None,
    snippet=False,
):
    """One stored page with `owned` official organic results of
    `organic`; snippet adds an official featured snippet."""
    results = [
        {
            "position": i + 1,
            "item_type": "organic",
            "result_type": "official" if i < owned else "other",
            "url": f"https://site{i}.in/",
            "domain": f"site{i}.in",
            "title": "t",
            "sitelinks": False,
        }
        for i in range(organic)
    ]
    if snippet:
        results.insert(
            0,
            {
                "position": 0,
                "item_type": "featured_snippet",
                "result_type": "official",
                "url": "https://walkaroo.in/",
                "domain": "walkaroo.in",
                "title": "t",
                "sitelinks": False,
            },
        )
    if query is None:
        query = "Walkaroo" if kind == "brand" else "Walkaroo reviews"
    with owner() as s, s.begin():
        row = m.SerpAudit(
            org_id=org.id,
            brand_id=bid,
            kind=kind,
            query=query,
            country=country,
            language=language,
            results=results,
            fetched_at=at,
            error=error,
        )
        s.add(row)
        s.flush()
        return row.id


def _weekly(owner, org, bid, owned, kind="brand"):
    """One page a week from T0, with these own-site counts of 6."""
    return [
        _serp(owner, org, bid, T0 + i * WEEK, n, kind=kind)
        for i, n in enumerate(owned)
    ]


def _drops(org, bid, to=LATER):
    with tenant_session(org.id) as s:
        return detect_serp_drop(s, bid, to)


def test_serp_drop_fires_when_two_later_pages_have_fewer_own_results(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    b = _serp(owner, org, bid, T0, 1, 6)
    p = _serp(owner, org, bid, T0 + WEEK, 0, 3)
    last = _serp(owner, org, bid, T0 + 2 * WEEK, 0, 5)
    (c,) = _drops(org, bid)
    assert (c.type, c.subject_key) == ("serp_drop", "brand:IN:en")
    assert c.title == (
        'Own-site results for "Walkaroo" (IN/en) fell from 1 of 6 to '
        "0 of 5 (0 of 3 on the page before)"
    )
    assert (c.window_from, c.window_to) == (T0, T0 + 2 * WEEK)
    assert c.detail == {
        "kind": "brand",
        "query": "Walkaroo",
        "country": "IN",
        "language": "en",
        "pages": [
            {"serp_audit_id": b, "fetched_at": T0, "owned": 1, "organic": 6},
            {
                "serp_audit_id": p,
                "fetched_at": T0 + WEEK,
                "owned": 0,
                "organic": 3,
            },
            {
                "serp_audit_id": last,
                "fetched_at": T0 + 2 * WEEK,
                "owned": 0,
                "organic": 5,
            },
        ],
        "prompt_ids": [],
        "observation_ids": [],
    }


@pytest.mark.parametrize(
    "owned",
    [[1, 0, 1], [1, 1, 0], [1, 1, 1], [0, 1, 1]],
    ids=["recovered", "latest-only", "flat", "rise"],
)
def test_serp_drop_needs_both_later_pages_below_a_baseline(
    owner, make_org, make_brand, owned
):
    org = make_org()
    bid = make_brand(org)
    _weekly(owner, org, bid, owned)
    assert _drops(org, bid) == []


def test_serp_drop_needs_three_pages(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _weekly(owner, org, bid, [1, 0])
    assert _drops(org, bid) == []


def test_serp_drop_reads_only_pages_fetched_before_to(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _weekly(owner, org, bid, [1, 0, 0])
    assert _drops(org, bid, to=T0 + 2 * WEEK) == []
    (c,) = _drops(org, bid, to=T0 + 2 * WEEK + timedelta(seconds=1))
    assert c.window_to == T0 + 2 * WEEK


def test_serp_drop_counts_a_gap_of_exactly_one_day(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _serp(owner, org, bid, T0, 1)
    _serp(owner, org, bid, T0 + timedelta(days=1), 0)
    _serp(owner, org, bid, T0 + timedelta(days=2), 0)
    (c,) = _drops(org, bid)
    assert c.window_from == T0


def test_serp_drop_pages_are_at_least_a_day_apart(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    # A second press an hour after the latest page cannot confirm it.
    _serp(owner, org, bid, T0, 1)
    _serp(owner, org, bid, T0 + WEEK, 0)
    _serp(owner, org, bid, T0 + WEEK + timedelta(hours=1), 0)
    assert _drops(org, bid) == []
    # With a page a week later, the hour-later page is the previous page
    # and the page an hour before it is skipped: T0 is the baseline.
    _serp(owner, org, bid, T0 + 2 * WEEK, 0)
    (c,) = _drops(org, bid)
    assert c.window_from == T0
    assert [p["fetched_at"] for p in c.detail["pages"]] == [
        T0,
        T0 + WEEK + timedelta(hours=1),
        T0 + 2 * WEEK,
    ]


def test_serp_drop_ignores_error_and_empty_pages(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _weekly(owner, org, bid, [1, 0, 0])
    _serp(owner, org, bid, T0 + 3 * WEEK, 0, error="timeout")
    _serp(owner, org, bid, T0 + 4 * WEEK, 0, 0)  # no organic result
    (c,) = _drops(org, bid)
    assert c.window_to == T0 + 2 * WEEK
    # An empty page in the middle is skipped too: no baseline is left.
    other = make_brand(org, "Other")
    _serp(owner, org, other, T0, 1)
    _serp(owner, org, other, T0 + WEEK, 0, 0)
    _serp(owner, org, other, T0 + 2 * WEEK, 0)
    _serp(owner, org, other, T0 + 3 * WEEK, 0, error="http")
    assert _drops(org, other) == []


def test_serp_drop_compares_only_the_latest_pages_locale(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _weekly(owner, org, bid, [1, 0])
    _serp(owner, org, bid, T0 + 2 * WEEK, 0, country="US")
    assert _drops(org, bid) == []  # one US page; the IN pages are skipped
    _serp(owner, org, bid, T0 + 3 * WEEK, 0, country="IN")
    (c,) = _drops(org, bid)  # IN is latest again; the US page is skipped
    assert c.subject_key == "brand:IN:en"
    assert c.window_to == T0 + 3 * WEEK
    # Another language is another series: two IN/hi pages under an IN/en
    # baseline are not a drop.
    other = make_brand(org, "Other")
    _serp(owner, org, other, T0, 1)
    _serp(owner, org, other, T0 + WEEK, 0, language="hi")
    _serp(owner, org, other, T0 + 2 * WEEK, 0, language="hi")
    assert _drops(org, other) == []


def test_serp_drop_compares_only_the_latest_pages_query(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _weekly(owner, org, bid, [1, 0])
    _serp(owner, org, bid, T0 + 2 * WEEK, 0, query="Walkaroo Footwear")
    assert _drops(org, bid) == []  # a renamed brand starts a new series


def test_serp_drop_judges_each_query_kind_on_its_own(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _weekly(owner, org, bid, [1, 0, 0])
    _weekly(owner, org, bid, [1, 1, 1], kind="reviews")
    assert [c.subject_key for c in _drops(org, bid)] == ["brand:IN:en"]
    _serp(owner, org, bid, T0 + 3 * WEEK, 0, kind="reviews")
    _serp(owner, org, bid, T0 + 4 * WEEK, 0, kind="reviews")
    found = _drops(org, bid)
    assert [c.subject_key for c in found] == ["brand:IN:en", "reviews:IN:en"]
    assert found[1].title.startswith('Own-site results for "Walkaroo reviews"')


def test_serp_drop_counts_only_organic_official_results(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _serp(owner, org, bid, T0, 1)
    _serp(owner, org, bid, T0 + WEEK, 0, snippet=True)
    _serp(owner, org, bid, T0 + 2 * WEEK, 0, snippet=True)
    (c,) = _drops(org, bid)
    assert [p["owned"] for p in c.detail["pages"]] == [1, 0, 0]


def test_scan_stores_a_serp_drop_once_and_a_further_drop_again(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    weeks = [T0 + i * WEEK for i in range(5)]
    for at, n in zip(weeks[:3], [2, 1, 1], strict=True):
        _serp(owner, org, bid, at, n)
    with tenant_session(org.id) as s:
        (row,) = scan(s, org.id, bid, LATER, deliver=False)
        assert (row.type, row.window_to) == ("serp_drop", weeks[2])
        base = row.detail["pages"][0]["fetched_at"]
        assert datetime.fromisoformat(base) == weeks[0]
    with tenant_session(org.id) as s:
        assert scan(s, org.id, bid, LATER, deliver=False) == []
    for at in weeks[3:]:
        _serp(owner, org, bid, at, 0)
    with tenant_session(org.id) as s:
        (again,) = scan(s, org.id, bid, LATER, deliver=False)
        assert (again.window_from, again.window_to) == (weeks[2], weeks[4])
    with owner() as s:
        assert s.scalar(select(func.count(m.Alert.id))) == 2


def test_scan_stores_a_new_serp_drop_after_a_recovery(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    weeks = [T0 + i * WEEK for i in range(7)]
    for at, n in zip(weeks[:3], [1, 0, 0], strict=True):
        _serp(owner, org, bid, at, n)
    with tenant_session(org.id) as s:
        (first,) = scan(s, org.id, bid, LATER, deliver=False)
    for at, n in zip(weeks[3:], [1, 1, 0, 0], strict=True):
        _serp(owner, org, bid, at, n)
    with tenant_session(org.id) as s:
        (again,) = scan(s, org.id, bid, LATER, deliver=False)
    assert (first.window_from, first.window_to) == (weeks[0], weeks[2])
    assert (again.window_from, again.window_to) == (weeks[4], weeks[6])


def test_the_alert_type_check_accepts_serp_drop(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    assert _alert(owner, org, bid, type="serp_drop", subject_key="brand:IN:en")
    with pytest.raises(IntegrityError, match="ck_alert_type"):
        _alert(owner, org, bid, type="serp_change")


def test_every_alert_type_has_a_report_label():
    assert set(ALERT_LABEL) == set(m.ALERT_TYPES)
    assert ALERT_LABEL["serp_drop"] == "Brand SERP drop"
```

The web test pins `ALERT_KIND` with the new entry (see Web).

Expected gates: backend `1746 passed, 2 deselected` (1728 on main plus 18) with metrics coverage at 100%; web `49` vitest, unchanged in count (one existing test changes).

### Proof

Run 2026-10-06 in the scratchpad on a copy of main's backend, against the shared test database (R2). The edits it applied (the diffs above, as exact old-text/new-text replacements), the migration and the tests above are the ones it used.

- Red, main's code with the new tests: `1 error` — the module fails at import with `ImportError: cannot import name 'detect_serp_drop' from 'bsi_core.alerts'` (R1).
- Green, patched: `50 passed` over test_alerts.py and test_constraints.py (32 on main plus the 18 new items).
- `ruff check`, `ruff format --check` and `mypy --strict` pass on the patched Python files.
- The migration: up to 0025 (the constraint lists `serp_drop`), down to 0024 (it lists the three old types), up and down again; bsi_test was left at 0024.
- Not run in the proof: the web gate (vitest cannot run outside the repo); it runs in execution.

Each of these 17 changes to the code fails at least one test (the parts of the rule they cover: the comparisons, the one-day gap and its boundary, the `to` cut-off, the error and empty-page filters, the query, country and language series, the kind split, the organic-only count, the scan wiring, the window, the migration and the report label):

| Mutant | Change | Failed | Failing tests |
|---|---|---|---|
| M1 | either later page below the baseline is enough | 2 | `test_serp_drop_needs_both_later_pages_below_a_baseline[latest-only]`, `test_serp_drop_needs_both_later_pages_below_a_baseline[recovered]` |
| M2 | only the latest page is compared | 1 | `test_serp_drop_needs_both_later_pages_below_a_baseline[latest-only]` |
| M3 | `<` becomes `<=` (equal counts fire) | 4 | `test_serp_drop_judges_each_query_kind_on_its_own`, `test_serp_drop_needs_both_later_pages_below_a_baseline[flat]`, `test_serp_drop_needs_both_later_pages_below_a_baseline[latest-only]`, `test_serp_drop_needs_both_later_pages_below_a_baseline[recovered]` |
| M4 | `SERP_GAP` is 0 (pages any distance apart) | 1 | `test_serp_drop_pages_are_at_least_a_day_apart` |
| M5 | pages with no organic result are kept | 1 | `test_serp_drop_ignores_error_and_empty_pages` |
| M6 | error pages are kept | 1 | `test_serp_drop_ignores_error_and_empty_pages` |
| M7 | pages of every country are compared | 1 | `test_serp_drop_compares_only_the_latest_pages_locale` |
| M14 | pages of every language are compared | 1 | `test_serp_drop_compares_only_the_latest_pages_locale` |
| M15 | pages of every query are compared | 1 | `test_serp_drop_compares_only_the_latest_pages_query` |
| M16 | pages fetched at `to` are read (`<=`) | 1 | `test_serp_drop_reads_only_pages_fetched_before_to` |
| M17 | a gap of exactly one day does not count (`>`) | 1 | `test_serp_drop_counts_a_gap_of_exactly_one_day` |
| M8 | both query kinds' pages are mixed | 10 | `test_scan_stores_a_new_serp_drop_after_a_recovery`, `test_scan_stores_a_serp_drop_once_and_a_further_drop_again`, `test_serp_drop_compares_only_the_latest_pages_locale`, `test_serp_drop_counts_a_gap_of_exactly_one_day`, `test_serp_drop_counts_only_organic_official_results`, `test_serp_drop_fires_when_two_later_pages_have_fewer_own_results`, `test_serp_drop_ignores_error_and_empty_pages`, `test_serp_drop_judges_each_query_kind_on_its_own`, `test_serp_drop_pages_are_at_least_a_day_apart`, `test_serp_drop_reads_only_pages_fetched_before_to` |
| M9 | every `official` result counts, organic or not | 1 | `test_serp_drop_counts_only_organic_official_results` |
| M10 | `detect_serp_drop` left out of `DETECTORS` | 2 | `test_scan_stores_a_new_serp_drop_after_a_recovery`, `test_scan_stores_a_serp_drop_once_and_a_further_drop_again` |
| M11 | `window_from` is the latest page, not the baseline | 5 | `test_scan_stores_a_new_serp_drop_after_a_recovery`, `test_scan_stores_a_serp_drop_once_and_a_further_drop_again`, `test_serp_drop_counts_a_gap_of_exactly_one_day`, `test_serp_drop_fires_when_two_later_pages_have_fewer_own_results`, `test_serp_drop_pages_are_at_least_a_day_apart` |
| M12 | migration 0025 keeps the old three types | 4 | `test_scan_stores_a_new_serp_drop_after_a_recovery`, `test_scan_stores_a_serp_drop_once_and_a_further_drop_again`, `test_slice6_checks_match_their_constants[ck_alert_type-values4]`, `test_the_alert_type_check_accepts_serp_drop` |
| M13 | no report label for `serp_drop` | 1 | `test_every_alert_type_has_a_report_label` |

## Rulings

Quoted from the ledger:

> Ruling: R1. Decided: the red step is the whole test module failing at import (`ImportError: cannot import name 'detect_serp_drop'`), not each new test failing on its own; the per-rule red evidence is the mutation table, where each of 13 mutants fails at least one named test. Found by: the controller, running the proof. Why: the new tests import the new detector, so on main's code the module cannot load. Cost if wrong: the red step shows only that the code is missing, not that each test checks something; the mutants cover that. How named: in chat, 2026-10-06, after the proof run.

> Ruling: R2. Decided: the proof ran in a scratch copy of main's backend against the shared test database bsi_test, so the test session applied migration 0025 for real; afterwards the proof ran the migration down to 0024, up and down again through alembic, and read alembic_version (0024) and ck_alert_type. Found by: the controller, setting up the proof. Why: it exercises the migration file itself, as slice 43's R7 did. Cost if wrong: bsi_test left at 0025 would break test sessions on main until downgraded. How named: in chat, 2026-10-06, after the proof run.

> Ruling: R3. Decided: the spec review's other findings are fixed in the spec and the proof: the PRD section is F15, not F09, and the alert's window is its pages (I1); tests and mutants are added for the "fetched before `to`" filter, the exact one-day gap, the language part of the locale and a recovery followed by a new drop, and the table's claim is limited to what it covers (I2); the earliest-alert date and the dev facts are corrected (I3); the spec's diffs carry full hunks (M1); the module docstring, the `is_duplicate` docstring and the `subject_key` comment in models.py are updated (M2); "the page before them" is reworded as the baseline (M4); the scan test parses the stored time instead of comparing a string (M5); the bad-type assertion matches `ck_alert_type` (M6); "pairs" is defined and the two-page case moves to its own test (M7). Found by: the spec reviewer (Opus 5.5), 2026-10-06. Why: each is a wrong or incomplete statement or a test gap, not a design choice. Cost if wrong: none to behaviour beyond the added tests. How named: in chat, 2026-10-06, after the review.

## Deferred minors

None yet.

## Live check

None in this slice (decision 6). No page on dev can start an alert (see Context), and with weekly pages the earliest real alert for Walkaroo is 2026-10-26, and only if Google shows walkaroo.in on a page from 2026-10-12 on. A later check is a separate decision with its own approval, and it may show only "no alert".
