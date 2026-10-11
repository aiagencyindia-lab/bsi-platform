# Slice 60 design: test hardening (the deferred test-only minors)

Classification: architectural, said first in chat on 2026-10-11, before the first question: a tests-only slice, but it touches thirteen files across the backend and the web app, and the project rule is that every slice gets a brainstorm, a spec and a plan. Session model Fable 5.1 for the brainstorm, the approaches, the proof and this spec; implementation and reviews on Opus 5.5.

## Context

"Fix every item" (user, 2026-10-09) was split into four slices: 59 behaviour (merged, PRs #118 and #119, main a026e65), 60 test hardening (this one), 61 the slice 56 probe script, 62 the docs sweep. This slice closes the deferred minors that ask for a stronger test, and nothing else. No production behaviour changes; two production files change in form only (Section 4 and Section 5).

The items, by the file they touch (findings line numbers are as at main a026e65):

- A. serp_due edges: 59:126 (no case just inside or outside the 1-day or 7-day windows; no running-job case).
- B. Race-test diagnostics: 59:122 (no `t.is_alive()` after the wait), 59:123 (a raise in the thread fails as KeyError 'response'; a failed blocked-assert leaves the thread running), 59:127 (the no-wait test's 5-second join and the same KeyError).
- C. Shared helper: 59:128 (`_wait_until_blocked` imported privately from test_api_recommendations.py by three modules).
- D. Assertions: 59:121 (the archived 409 detail is not asserted), 59:124 (the 200-character host cap applies to the raw input).
- E. Clock and environment: 57:163 (`test_get_is_empty_before_any_audit` reads the real `.env` budget), 55:119 (the boundary test mixes Python's clock with the DB's).
- F. The page test: 58:119 (the audit cards are rendered by no test), 58:120 (hard-coded base URL), 58:121 (URL and Authorization asserted in case 1 only), 58:124 (the cookie mock ignores the name), 58:125 (the copied BUDGET string), 58:126 and 58:127 (`serp_configured`, `failed_7d` and `budget_room` pinned one way).
- G. Path scans: 59:130 (the formSeg scan is pinned to a parameter named `form`, double quotes and `String(...)`), 49:102 (a block comment holding an unclosed backtick).
- H. 59:131 (`formSeg` logs "missing" for a File field): a one-line log text, included at the user's choice.

Also closed here: 57:153 (a page passing a constant for `budget_room` passed the gate); slice 58's page test did not pin `budget_room` true on an active brand, and this slice's audit-cards case does (R3). Already closed before this slice, so no change: 49:105 (fixed in slice 58, noted at 49:106). Moot: 57:160 asked for a `serpSchedule` case with `jobStatus = null`; slice 59 (PR #118) replaced that parameter with `serp_due`, so there is nothing to add (a dated note closes it).

User decisions (2026-10-11), with the approaches text shown in chat before each:
1. Scope as listed above, including 57:160 and excluding 49:105/106 and 57:153. (The 57:160 moot finding came after this approval and was reported in Section 5 before its approval. 57:153 moved into scope by decision 8, after the spec review showed it was not already closed.)
2. Item H included in slice 60, over pushing it to slice 62 or won't-fix.
3. Approach 2 (shared helpers for the two repeated shapes, then one edit per item), over patching each item in place and over a `locked_holder` fixture.
4. Sections 1 to 6 each approved with "yes" after their text was shown in chat.
5. After mutant M10: 49:102 dropped and closed as already guarded, over keeping a block-comment strip no mutant distinguishes.
6. After the proof: the budget lock test keeps the proof's shape without the `done` Event (R2), over restoring the Event as Section 1 had said.
7. After the spec review (finding 4): `signedIn()` in api.test.ts gets the same name-checking cookie mock as the page test, over scoping the 58:124 note to page.test.tsx.
8. After the spec re-review (finding 2): 57:153 counts as closed by this slice's audit-cards case (R3), over leaving it to slice 62; the fact behind decision 1 ("already closed by slice 58") was wrong.

## Section 1 — The thread helpers (B, C)

New non-test module tests/integration/threads.py:

- `wait_until_blocked(holder, deadline=5.0)`: the function moved verbatim from test_api_recommendations.py, public name. The old definition goes; test_api_crud.py, test_recommend.py and test_budget.py import the new name.
- `run_in_thread(fn)`: starts a daemon thread running `fn` and returns a `ThreadHandle` with `is_alive()` and `result(timeout=5.0)`. `result()` joins with the timeout, asserts the thread finished ("the thread did not finish within 5.0 s"), then re-raises the exception the thread raised or returns its value. A request that raises inside the thread therefore fails the test with that exception, not with KeyError 'response'.

The five thread tests take one shape: `t = run_in_thread(...)`; `assert wait_until_blocked(holder)`; `assert t.is_alive()` (still waiting, not raced ahead); release; and in `finally`, close the holder then `t.result()`, so no thread outlives the test even when an assert fails.

- test_api_crud.py `test_a_simultaneous_duplicate_domain_is_409_not_500` gains the `is_alive` assert and the finally-join.
- test_api_recommendations.py `test_concurrent_accept_returns_409_not_500` and test_recommend.py `test_a_dismiss_racing_refresh_survives` switch to the helpers.
- test_api_serp.py `test_the_page_does_not_wait_on_the_orgs_budget_lock` calls `t.result()` while the holder still holds the lock, with no `wait_until_blocked` (nothing should block); a GET that took the lock fails on `result()`'s timeout (mutant M5). Its `finally` calls `t.result()` again after the rollback, so a GET that did wait is joined once the lock is gone (R4).
- test_budget.py `test_the_default_check_waits_for_the_orgs_lock` uses the helpers; `assert t.is_alive()` replaces the `done` Event, the `finally` joins with `verdict = t.result()`, and `assert verdict is True` pins the verdict after release (R2, R4).

The join timeout stays 5 seconds: CI runs the suite under load. When an assert inside the `try` fails and `result()` in the `finally` then raises too (a timeout, or the thread's own error), Python reports the thread's error and keeps the assert's message as its `__context__`; that is accepted (R6).

## Section 2 — serp_due edges on the DB clock (A, E)

In test_api_serp.py, `_audit` and `_aged` take a `timedelta` and write `func.now() - ago`, so every timestamp they set and every comparison inside `serp_due` and `due_serp_audits()` use Postgres `now()`. Module constants `MINUTE`, `DAY`, `WEEK` name the offsets. `_arrange` keeps its case names and gains these rows in `test_serp_due_agrees_with_due_serp_audits`, each asserted against the Python mirror and the SQL function as before:

| case | serp_due |
|---|---|
| both kinds a minute inside the week | False |
| both kinds a minute outside the week | True |
| a done job a minute inside the day | False |
| a done job a minute outside the day | True |
| a running job 8 days ago | False |
| three failures a minute inside the week | False |
| three failures a minute outside the week | True |

One minute each side is the margin `test_failed_7d_window_boundary` already uses. Both sides compare with strict `>`, so on one clock a one-minute offset is deterministic; it proves the window's length, not whether its edge is `>` or `>=`. `test_failed_7d_window_boundary` (55:119) now runs on the DB clock through the changed `_aged`, with no edit of its own. The `_job` helper's `minutes` argument sets `scheduled_slot`, which `serp_due` never reads, so it is unchanged (R1).

## Section 3 — Single assertions (D, E)

- 59:121: `test_an_archived_brand_accepts_no_new_domain` also asserts `detail == "Archived brands accept no new domains."`.
- 59:124: `test_a_host_is_capped_at_200_characters` posts `"https://www." + "a" * 192 + ".com"` (208 characters as sent, 196 after `normalize_domain`) and asserts 422 on `host`, with a comment that the cap is on the input as sent, as for every other `Host` field.
- 57:163: `_configured` builds one `Settings(dataforseo_login=..., dataforseo_password=..., daily_budget_usd=2.0)` and patches both `audits.get_settings` and `scheduling.get_settings`, so `budget_room` in `test_get_is_empty_before_any_audit` no longer depends on the developer's `.env`. This is the one item with a red run: with `DAILY_BUDGET_USD=0.01` in the environment, main's test fails (`{'budget_room': False} != {'budget_room': True}`) and the patched test passes.

## Section 4 — The page test (F)

apps/web/src/app/(app)/b/[id]/serp/page.test.tsx:

- 58:120: `BASE` is built from `API_URL` imported from `@/lib/api`.
- 58:124: the cookie store's `get(name)` returns the key only for `COOKIE` (from `@/lib/cookie`), so a wrong cookie name in `api()` sends no Bearer header. `signedIn()` in apps/web/src/lib/api.test.ts gets the same `get(name)` (decision 7). That file asserts no Authorization header today and its `redirect` mock does not throw, so the change pins nothing there yet (mutant M6 passes its 26 tests with the wrong name); it removes the blind spot for a future header assertion.
- 58:121: `render()` asserts the three URLs and `Bearer bsi_key_1` on every call before returning the markup, so every case checks them.
- 58:125: apps/web/src/lib/format.ts exports the budget sentence as `BUDGET_NOTE` and `serpSchedule` uses it; page.test.tsx and format.test.ts import it. A production export with no behaviour change.
- 58:126/127: `serp(over)` takes a partial override on defaults that put the brand at the budget check with no room (`budget_room: false`, `serp_due: true`, `serp_configured: true`, `failed_7d: 0`, `job: null`, `audits: []`). Two new cases pin the other side: `serp_configured: false` shows the "not configured" line and not the budget note; `failed_7d: 3` shows the failed line and not the budget note. `budget_room: true` on an active, due, configured brand is pinned by the audit-cards case below (R3).
- 58:119: one new case with two audits: a successful one with an owned organic result (https URL) and a knowledge panel (no URL), and a failed one. It asserts the query, "IN/en · desktop · 2026-10-11 09:30 UTC", "Ownership: 1 of 1 (100%)", "knowledge_panel 1 · official 1", "Knowledge Panel: yes · AI Overview: no", the result tag, the link's href, the host cell, the plain-text title for the result with no URL, the second card's query and its "Failed: the SERP provider took too long to answer" line (the mapped `timeout` text), that the failed card has no "Ownership: 0 of 0" line, that "No audit yet" is absent, and, since the case has budget room, the plain weekly line and not the budget note (R3; mutants M11 and M6).

The harness and its ponytail note stay.

## Section 5 — The path scan, the formSeg log, the moot item (G, H)

- 59:130: in apps/web/src/lib/api-paths.test.ts the RAW pattern keeps its scope (id-like names and `type`; body fields such as `notes` legitimately use `String(form.get(...))`) but no longer depends on spelling: any receiver name, either quote style, and the `as string` cast. It matches `String(<x>.get(<q>id-or-type<q>))`, `String(<x>.get(<variable>))`, `seg(String(`, and `<x>.get(<q>id-or-type<q>) as string`. Main's pattern lets `String(fd.get('brand_id'))` and `form.get("type") as string` through; the new one catches both (mutant M9).
- 49:102: no change (decision 5). Main's first scan already fails on a block comment holding an unclosed backtick, because its literal check requires the whole first argument to be one literal followed by `,` or `)`; mutant M10 shows the same failure on main's scan and on this one.
- 59:131 (H): `formSeg`'s log becomes "API form value missing or not text" (apps/web/src/lib/api.ts); the three tests that assert the old text (api.test.ts twice, serp/actions.test.ts once) assert the new one.
- 57:160: a dated note only.

## Section 6 — Testing

- Red: a tests-only slice has no red run; the new tests pass on main's code, except 57:163, whose red run is in Section 3. The evidence that the tests bite is the mutation table under Evidence.
- Green: backend 1796 → 1803 (seven parametrize rows; every other backend change edits an existing test); web vitest 88 → 91 (three page cases). ruff, mypy, typecheck and eslint clean; `npm run gate` at execution. No `npm run gen`: the API surface does not change.
- No live check: nothing user-visible changes.

## The change

Generated from the proof (a scratchpad copy of main a026e65 with the change applied), as a unified diff over tests/ and apps/web/src/:

```diff
diff -ruN -x __pycache__ -x .pytest_cache a/tests/integration/test_api_crud.py b/tests/integration/test_api_crud.py
--- a/tests/integration/test_api_crud.py	2026-10-11 18:14:42
+++ b/tests/integration/test_api_crud.py	2026-10-11 22:28:48
@@ -1,10 +1,8 @@
-import threading
-
 import pytest
 from bsi_core import models as m
 from sqlalchemy import func, select, update
 
-from tests.integration.test_api_recommendations import _wait_until_blocked
+from tests.integration.threads import run_in_thread, wait_until_blocked
 
 
 def test_health_needs_no_key(client):
@@ -211,6 +209,7 @@
     r = client.post(base, headers=org.headers, json={"host": "acme.com"})
     assert r.status_code == 409, r.text
     assert r.json()["title"] == "Brand is archived"
+    assert r.json()["detail"] == "Archived brands accept no new domains."
     assert client.get(base, headers=org.headers).json() == []
 
 
@@ -223,6 +222,14 @@
     r = client.post(base, headers=org.headers, json={"host": "a" + at_cap})
     assert r.status_code == 422, r.text
     assert r.json()["errors"][0]["loc"][-1] == "host"
+    # The cap is on the input as sent, before normalization strips the
+    # scheme and "www.", as for every other Host field.
+    scheme = "https://www." + "a" * 192 + ".com"
+    assert len(scheme) == 208
+    r = client.post(base, headers=org.headers, json={"host": scheme})
+    assert r.status_code == 422, r.text
+    assert r.json()["errors"][0]["loc"][-1] == "host"
+    assert r.json()["errors"][0]["loc"][-1] == "host"
 
 
 def test_a_simultaneous_duplicate_domain_is_409_not_500(
@@ -237,28 +244,23 @@
     holder.begin()
     holder.add(m.Domain(org_id=org.id, brand_id=bid, host="acme.com"))
     holder.flush()
-    result: dict[str, object] = {}
-
-    def post() -> None:
-        result["response"] = client.post(
+    t = run_in_thread(
+        lambda: client.post(
             f"/v1/brands/{bid}/domains",
             headers=org.headers,
             json={"host": "acme.com"},
         )
-
-    t = threading.Thread(target=post)
-    t.start()
+    )
     try:
-        assert _wait_until_blocked(holder), (
+        assert wait_until_blocked(holder), (
             "the POST never waited on the uncommitted row; the test would "
             "pass whether or not the insert handles the conflict"
         )
+        assert t.is_alive()  # still waiting, not raced ahead
         holder.commit()
-        t.join(timeout=5)
-        assert not t.is_alive()
     finally:
-        holder.close()
-    response = result["response"]
+        holder.close()  # releases the row even if an assert above failed
+        response = t.result()
     assert response.status_code == 409, response.text
     assert response.json()["title"] == "Domain already exists"
     with owner() as s:
diff -ruN -x __pycache__ -x .pytest_cache a/tests/integration/test_api_recommendations.py b/tests/integration/test_api_recommendations.py
--- a/tests/integration/test_api_recommendations.py	2026-10-11 18:14:42
+++ b/tests/integration/test_api_recommendations.py	2026-10-11 22:28:48
@@ -1,12 +1,12 @@
-import threading
-import time
 import uuid
 
 import pytest
 from bsi_core import models as m
-from sqlalchemy import select, text
+from sqlalchemy import select
 
+from tests.integration.threads import run_in_thread, wait_until_blocked
 
+
 @pytest.fixture
 def scene(owner, make_org, make_brand):
     org = make_org()
@@ -188,37 +188,6 @@
     assert [t["id"] for t in listed.json()] == [task["id"]]
 
 
-def _wait_until_blocked(holder, deadline=5.0):
-    """Poll pg_stat_activity for some *other* backend waiting on a lock,
-    so the test cannot pass just because the request happened to arrive
-    late. Postgres reports a row-lock wait via wait_event_type='Lock'
-    (wait_event='transactionid'); the query text it shows alongside a
-    blocked backend is not reliable (it can lag behind the statement
-    actually stuck), so filter on the wait state, not the query text.
-
-    Postgres caches the activity statistics for the rest of a transaction,
-    so each poll clears that snapshot first; otherwise a request that
-    connects after the first poll is never seen. Only this database's
-    backends count, so another database's lock wait cannot pass it.
-    """
-    my_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar()
-    end = time.monotonic() + deadline
-    while time.monotonic() < end:
-        holder.execute(text("SELECT pg_stat_clear_snapshot()"))
-        waiting = holder.execute(
-            text(
-                "SELECT count(*) FROM pg_stat_activity "
-                "WHERE wait_event_type = 'Lock' AND pid != :pid "
-                "AND datname = current_database()"
-            ),
-            {"pid": my_pid},
-        ).scalar()
-        if waiting:
-            return True
-        time.sleep(0.05)
-    return False
-
-
 def test_concurrent_accept_returns_409_not_500(client, owner, scene):
     """Two overlapping accepts on the same recommendation: the second
     must see 'accepted' and 409, never race a raw IntegrityError into a
@@ -239,15 +208,9 @@
         .with_for_update()
     ).scalar_one()
 
-    result: dict[str, object] = {}
-
-    def call_accept() -> None:
-        result["response"] = client.post(url, headers=org.headers)
-
-    t = threading.Thread(target=call_accept)
-    t.start()
+    t = run_in_thread(lambda: client.post(url, headers=org.headers))
     try:
-        assert _wait_until_blocked(holder), (
+        assert wait_until_blocked(holder), (
             "accept request never blocked on the row lock; the test "
             "would pass regardless of whether _open locks the row"
         )
@@ -257,13 +220,10 @@
         # releases the lock the second request is waiting on.
         locked.status = "accepted"
         holder.commit()
-
-        t.join(timeout=5)
-        assert not t.is_alive()
     finally:
         holder.close()
+        response = t.result()
 
-    response = result["response"]
     assert response.status_code == 409, response.text
 
 
diff -ruN -x __pycache__ -x .pytest_cache a/tests/integration/test_api_serp.py b/tests/integration/test_api_serp.py
--- a/tests/integration/test_api_serp.py	2026-10-11 18:14:42
+++ b/tests/integration/test_api_serp.py	2026-10-11 22:28:48
@@ -1,15 +1,16 @@
-import threading
 from datetime import UTC, datetime, timedelta
 from decimal import Decimal
 
 import pytest
 from bsi_api.routers import audits
 from bsi_core import models as m
+from bsi_core import scheduling
 from bsi_core.config import Settings
 from bsi_core.db import system_session
-from sqlalchemy import text, update
+from sqlalchemy import func, text, update
 
 from tests.integration.test_worker import _job
+from tests.integration.threads import run_in_thread
 
 OFFICIAL = {
     "position": 1,
@@ -32,7 +33,9 @@
 }
 
 
-def _audit(owner, org, bid, kind, minutes_ago, results=(), error=None):
+def _audit(owner, org, bid, kind, ago, results=(), error=None):
+    """An audit row fetched `ago` before the DB's now(), the clock
+    serp_due and due_serp_audits() compare against."""
     with owner() as s, s.begin():
         s.add(
             m.SerpAudit(
@@ -43,7 +46,7 @@
                 country="IN",
                 language="en",
                 results=list(results),
-                fetched_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
+                fetched_at=func.now() - ago,
                 cost_micros=4_000,
                 error=error,
             )
@@ -51,24 +54,32 @@
 
 
 def _configured(monkeypatch, login="me", password="pw"):
-    """The API's DataForSEO settings, patched where audits.py reads them
-    (the lambda bypasses get_settings' lru_cache; explicit kwargs win
-    over .env)."""
-    monkeypatch.setattr(
-        audits,
-        "get_settings",
-        lambda: Settings(dataforseo_login=login, dataforseo_password=password),
+    """The API's DataForSEO settings and a fixed $2.00 budget, patched
+    where audits.py and scheduling.py read them (the lambda bypasses
+    get_settings' lru_cache; explicit kwargs win over .env, so a local
+    DAILY_BUDGET_USD cannot change budget_room)."""
+    settings = Settings(
+        dataforseo_login=login,
+        dataforseo_password=password,
+        daily_budget_usd=2.0,
     )
+    monkeypatch.setattr(audits, "get_settings", lambda: settings)
+    monkeypatch.setattr(scheduling, "get_settings", lambda: settings)
 
 
+MINUTE = timedelta(minutes=1)
+DAY = timedelta(days=1)
+WEEK = timedelta(days=7)
+
+
 def _aged(owner, job_id, ago):
     """Set a job's created_at (_job sets scheduled_slot only; created_at
-    is the server default) to now() - ago."""
+    is the server default) to the DB's now() - ago."""
     with owner() as s, s.begin():
         s.execute(
             update(m.Job)
             .where(m.Job.id == job_id)
-            .values(created_at=datetime.now(UTC) - ago)
+            .values(created_at=func.now() - ago)
         )
 
 
@@ -121,11 +132,11 @@
 ):
     org = make_org()
     bid = make_brand(org)
-    _audit(owner, org, bid, "brand", 60, [OTHER])
-    _audit(owner, org, bid, "brand", 5, [OFFICIAL, OTHER, PANEL])
-    _audit(owner, org, bid, "reviews", 60, [OFFICIAL])
+    _audit(owner, org, bid, "brand", timedelta(hours=1), [OTHER])
+    _audit(owner, org, bid, "brand", MINUTE * 5, [OFFICIAL, OTHER, PANEL])
+    _audit(owner, org, bid, "reviews", timedelta(hours=1), [OFFICIAL])
     # The latest reviews row is an error: it is shown, not the older one.
-    _audit(owner, org, bid, "reviews", 5, error="rate")
+    _audit(owner, org, bid, "reviews", MINUTE * 5, error="rate")
     r = client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
     assert r.status_code == 200, r.text
     brand, reviews = r.json()["audits"]
@@ -261,8 +272,8 @@
     bid = make_brand(org)
     inside = _job(owner, org, bid, "audit_serp", "failed", minutes=-1)
     outside = _job(owner, org, bid, "audit_serp", "failed", minutes=-2)
-    _aged(owner, inside, timedelta(days=7) - timedelta(minutes=1))
-    _aged(owner, outside, timedelta(days=7) + timedelta(minutes=1))
+    _aged(owner, inside, WEEK - MINUTE)
+    _aged(owner, outside, WEEK + MINUTE)
     r = client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
     assert r.status_code == 200, r.text
     assert r.json()["failed_7d"] == 1
@@ -286,37 +297,55 @@
                 .where(m.Brand.id == bid)
                 .values(status="archived")
             )
-    week_ago = 8 * 24 * 60  # minutes: just outside the 7-day window
+    hour = timedelta(hours=1)
     if case in (
         "one kind this week",
         "both kinds this week",
         "one kind twice this week",
         "both kinds, one an error",
     ):
-        _audit(owner, org, bid, "brand", 60)
+        _audit(owner, org, bid, "brand", hour)
     if case == "both kinds this week":
-        _audit(owner, org, bid, "reviews", 60)
+        _audit(owner, org, bid, "reviews", hour)
     if case == "one kind twice this week":
-        _audit(owner, org, bid, "brand", 120)
+        _audit(owner, org, bid, "brand", hour * 2)
     if case == "both kinds, one an error":
-        _audit(owner, org, bid, "reviews", 60, error="timeout")
-    if case == "both kinds 8 days ago":
-        _audit(owner, org, bid, "brand", week_ago)
-        _audit(owner, org, bid, "reviews", week_ago)
-    if case == "a job today":
-        _job(owner, org, bid, "audit_serp", "done")
-    if case == "a queued job":
-        _aged(
-            owner,
-            _job(owner, org, bid, "audit_serp", "queued"),
-            timedelta(days=2),
-        )
-    if case in ("two failures", "three failures", "three failures 8 days ago"):
-        n = 2 if case == "two failures" else 3
-        days = 8 if case == "three failures 8 days ago" else 2
+        _audit(owner, org, bid, "reviews", hour, error="timeout")
+    # The 7-day window's edges: a minute inside keeps the brand covered, a
+    # minute outside does not (one minute proves the length, not > vs >=).
+    both_kinds = {
+        "both kinds 8 days ago": DAY * 8,
+        "both kinds a minute inside the week": WEEK - MINUTE,
+        "both kinds a minute outside the week": WEEK + MINUTE,
+    }
+    if case in both_kinds:
+        _audit(owner, org, bid, "brand", both_kinds[case])
+        _audit(owner, org, bid, "reviews", both_kinds[case])
+    # A job: done ones count for a day; queued or running ones at any age.
+    jobs = {
+        "a job today": ("done", None),
+        "a done job a minute inside the day": ("done", DAY - MINUTE),
+        "a done job a minute outside the day": ("done", DAY + MINUTE),
+        "a queued job": ("queued", DAY * 2),
+        "a running job 8 days ago": ("running", DAY * 8),
+    }
+    if case in jobs:
+        status, ago = jobs[case]
+        job = _job(owner, org, bid, "audit_serp", status)
+        if ago is not None:
+            _aged(owner, job, ago)
+    failures = {
+        "two failures": (2, DAY * 2),
+        "three failures": (3, DAY * 2),
+        "three failures 8 days ago": (3, DAY * 8),
+        "three failures a minute inside the week": (3, WEEK - MINUTE),
+        "three failures a minute outside the week": (3, WEEK + MINUTE),
+    }
+    if case in failures:
+        n, ago = failures[case]
         for i in range(n):
             job = _job(owner, org, bid, "audit_serp", "failed", minutes=-i)
-            _aged(owner, job, timedelta(days=days))
+            _aged(owner, job, ago)
 
 
 @pytest.mark.parametrize(
@@ -330,11 +359,18 @@
         ("one kind twice this week", True),
         ("both kinds, one an error", True),
         ("both kinds 8 days ago", True),
+        ("both kinds a minute inside the week", False),
+        ("both kinds a minute outside the week", True),
         ("a job today", False),
+        ("a done job a minute inside the day", False),
+        ("a done job a minute outside the day", True),
         ("a queued job", False),
+        ("a running job 8 days ago", False),
         ("two failures", True),
         ("three failures", False),
         ("three failures 8 days ago", True),
+        ("three failures a minute inside the week", False),
+        ("three failures a minute outside the week", True),
     ],
 )
 def test_serp_due_agrees_with_due_serp_audits(
@@ -362,20 +398,15 @@
         text("SELECT pg_advisory_xact_lock(hashtext(:org))"),
         {"org": str(org.id)},
     )
-    result: dict[str, object] = {}
-
-    def get() -> None:
-        result["response"] = client.get(
-            f"/v1/brands/{bid}/audits/serp", headers=org.headers
-        )
-
-    t = threading.Thread(target=get)
-    t.start()
-    t.join(timeout=5)
+    t = run_in_thread(
+        lambda: client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
+    )
     try:
-        assert not t.is_alive(), "the GET waited on the org's advisory lock"
+        # The lock is still held: a GET that took it would not finish, and
+        # result() fails after its timeout.
+        response = t.result()
     finally:
         holder.rollback()
         holder.close()
-        t.join()
-    assert result["response"].status_code == 200
+        t.result()  # a GET that waited finishes now; join it either way
+    assert response.status_code == 200, response.text
diff -ruN -x __pycache__ -x .pytest_cache a/tests/integration/test_budget.py b/tests/integration/test_budget.py
--- a/tests/integration/test_budget.py	2026-10-11 18:14:42
+++ b/tests/integration/test_budget.py	2026-10-11 22:28:48
@@ -1,4 +1,3 @@
-import threading
 from datetime import UTC, datetime, timedelta
 from decimal import Decimal
 from types import SimpleNamespace
@@ -9,7 +8,7 @@
 from bsi_core.db import system_session, tenant_session
 from sqlalchemy import func, text, update
 
-from tests.integration.test_api_recommendations import _wait_until_blocked
+from tests.integration.threads import run_in_thread, wait_until_blocked
 
 
 @pytest.fixture(autouse=True)
@@ -222,19 +221,12 @@
         text("SELECT pg_advisory_xact_lock(hashtext(:org))"),
         {"org": str(org.id)},
     )
-    done = threading.Event()
-
-    def check() -> None:
-        fits(org, 1)
-        done.set()
-
-    t = threading.Thread(target=check)
-    t.start()
+    t = run_in_thread(lambda: fits(org, 1))
     try:
-        assert _wait_until_blocked(holder), "budget_fits did not wait"
-        assert not done.is_set()
+        assert wait_until_blocked(holder), "budget_fits did not wait"
+        assert t.is_alive()  # still waiting on the lock
     finally:
         holder.rollback()
-        holder.close()
-    t.join(timeout=5)
-    assert done.is_set()
+        holder.close()  # releases the lock even if an assert above failed
+        verdict = t.result()
+    assert verdict is True
diff -ruN -x __pycache__ -x .pytest_cache a/tests/integration/test_recommend.py b/tests/integration/test_recommend.py
--- a/tests/integration/test_recommend.py	2026-10-11 18:14:42
+++ b/tests/integration/test_recommend.py	2026-10-11 22:28:48
@@ -1,4 +1,3 @@
-import threading
 from types import SimpleNamespace
 
 import pytest
@@ -7,9 +6,9 @@
 from bsi_core.recommend import _rival_content, generate, refresh
 from sqlalchemy import delete, func, select, update
 
-from tests.integration.test_api_recommendations import _wait_until_blocked
 from tests.integration.test_gaps import scene  # noqa: F401
 from tests.integration.test_rival_crawl import _page
+from tests.integration.threads import run_in_thread, wait_until_blocked
 
 
 def _mention(org, oid, etype, eid):
@@ -320,16 +319,14 @@
         with tenant_session(world.org.id) as s:
             refresh(s, world.org.id, world.brand)
 
-    t = threading.Thread(target=run)
-    t.start()
+    t = run_in_thread(run)
     try:
-        assert _wait_until_blocked(holder), "refresh never blocked"
+        assert wait_until_blocked(holder), "refresh never blocked"
         assert t.is_alive()
         holder.commit()
-        t.join(timeout=5)
-        assert not t.is_alive()
     finally:
         holder.close()
+        t.result()
     with owner() as s:
         got = s.get(m.Recommendation, rec.id)
         assert got is not None, "the dismissed row was deleted"
diff -ruN -x __pycache__ -x .pytest_cache a/tests/integration/threads.py b/tests/integration/threads.py
--- a/tests/integration/threads.py	1970-01-01 05:30:00
+++ b/tests/integration/threads.py	2026-10-11 18:46:03
@@ -0,0 +1,76 @@
+"""Helpers for the tests that race a request against a held lock."""
+
+import threading
+import time
+from collections.abc import Callable
+from typing import Any
+
+from sqlalchemy import text
+
+
+def wait_until_blocked(holder, deadline=5.0):
+    """Poll pg_stat_activity for some *other* backend waiting on a lock,
+    so the test cannot pass just because the request happened to arrive
+    late. Postgres reports a row-lock wait via wait_event_type='Lock'
+    (wait_event='transactionid'); the query text it shows alongside a
+    blocked backend is not reliable (it can lag behind the statement
+    actually stuck), so filter on the wait state, not the query text.
+
+    Postgres caches the activity statistics for the rest of a transaction,
+    so each poll clears that snapshot first; otherwise a request that
+    connects after the first poll is never seen. Only this database's
+    backends count, so another database's lock wait cannot pass it.
+    """
+    my_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar()
+    end = time.monotonic() + deadline
+    while time.monotonic() < end:
+        holder.execute(text("SELECT pg_stat_clear_snapshot()"))
+        waiting = holder.execute(
+            text(
+                "SELECT count(*) FROM pg_stat_activity "
+                "WHERE wait_event_type = 'Lock' AND pid != :pid "
+                "AND datname = current_database()"
+            ),
+            {"pid": my_pid},
+        ).scalar()
+        if waiting:
+            return True
+        time.sleep(0.05)
+    return False
+
+
+class ThreadHandle:
+    """A started thread and its outcome. result() joins and then returns
+    what fn returned, or re-raises what it raised, so a request that
+    fails inside the thread fails the test with that error rather than
+    with a KeyError on a result dict."""
+
+    def __init__(self, fn: Callable[[], Any]) -> None:
+        self._value: Any = None
+        self._error: Exception | None = None
+        self._thread = threading.Thread(target=self._run, args=(fn,))
+        self._thread.daemon = True
+        self._thread.start()
+
+    def _run(self, fn: Callable[[], Any]) -> None:
+        try:
+            self._value = fn()
+        except Exception as e:
+            self._error = e
+
+    def is_alive(self) -> bool:
+        return self._thread.is_alive()
+
+    def result(self, timeout: float = 5.0) -> Any:
+        self._thread.join(timeout)
+        assert not self._thread.is_alive(), (
+            f"the thread did not finish within {timeout} s"
+        )
+        if self._error is not None:
+            raise self._error
+        return self._value
+
+
+def run_in_thread(fn: Callable[[], Any]) -> ThreadHandle:
+    """Run fn on a daemon thread; see ThreadHandle."""
+    return ThreadHandle(fn)
diff -ruN a/apps/web/src/app/(app)/b/[id]/serp/actions.test.ts b/apps/web/src/app/(app)/b/[id]/serp/actions.test.ts
--- a/apps/web/src/app/(app)/b/[id]/serp/actions.test.ts	2026-10-11 18:14:42
+++ b/apps/web/src/app/(app)/b/[id]/serp/actions.test.ts	2026-10-11 22:28:48
@@ -115,5 +115,8 @@
   await expect(action(f)).rejects.toThrow("NOT_FOUND");
   expect(fetchMock).not.toHaveBeenCalled();
   expect(redirect).not.toHaveBeenCalled();
-  expect(log).toHaveBeenCalledWith("API form value missing", '"brand_id"');
+  expect(log).toHaveBeenCalledWith(
+    "API form value missing or not text",
+    '"brand_id"',
+  );
 });
diff -ruN a/apps/web/src/app/(app)/b/[id]/serp/page.test.tsx b/apps/web/src/app/(app)/b/[id]/serp/page.test.tsx
--- a/apps/web/src/app/(app)/b/[id]/serp/page.test.tsx	2026-10-11 18:14:42
+++ b/apps/web/src/app/(app)/b/[id]/serp/page.test.tsx	2026-10-11 22:28:48
@@ -1,10 +1,15 @@
 import { renderToStaticMarkup } from "react-dom/server";
 import { afterEach, expect, test, vi } from "vitest";
+import { COOKIE } from "@/lib/cookie";
 import type { Brand, Domain, SerpAudits } from "@/lib/types";
-import type { Params } from "@/lib/format";
+import { BUDGET_NOTE, type Params } from "@/lib/format";
 
 vi.mock("server-only", () => ({}));
-const cookieStore = { get: () => ({ value: "bsi_key_1" }) };
+// Only the cookie api() reads carries the key, so a wrong name sends none.
+const cookieStore = {
+  get: (name: string) =>
+    name === COOKIE ? { value: "bsi_key_1" } : undefined,
+};
 vi.mock("next/headers", () => ({ cookies: vi.fn(async () => cookieStore) }));
 vi.mock("next/navigation", () => ({
   notFound: () => {
@@ -14,9 +19,10 @@
 }));
 
 const { default: Serp } = await import("./page");
+const { API_URL } = await import("@/lib/api");
 
 const ID = "1eb6c00a-4b18-4512-b515-dd1d8039511f";
-const BASE = `http://localhost:8000/v1/brands/${ID}`;
+const BASE = `${API_URL}/v1/brands/${ID}`;
 
 const brand = (status: string): Brand => ({
   id: ID,
@@ -32,18 +38,33 @@
   webhook_url: null,
 });
 const DOMAIN: Domain = { id: ID, host: "walkaroo.in", is_primary: true };
-const serp = (
-  budget_room: boolean,
-  job: SerpAudits["job"] = null,
-  serp_due = true,
-): SerpAudits => ({
-  job,
+// Defaults put the brand at the budget check with no room, so a case
+// that overrides one field pins that field against the budget note.
+const serp = (over: Partial<SerpAudits> = {}): SerpAudits => ({
+  job: null,
   audits: [],
   serp_configured: true,
   failed_7d: 0,
-  budget_room,
-  serp_due,
+  budget_room: false,
+  serp_due: true,
+  ...over,
 });
+type Audit = SerpAudits["audits"][number];
+const audit = (over: Partial<Audit> = {}): Audit => ({
+  id: "0a6a1b3e-0d7c-4d55-9a6b-2a0b1c2d3e4f",
+  kind: "brand",
+  query: "walkaroo",
+  country: "IN",
+  language: "en",
+  device: "desktop",
+  fetched_at: "2026-10-11T09:30:00Z",
+  cost_micros: 4000,
+  error: null,
+  owned: 1,
+  organic: 1,
+  results: [],
+  ...over,
+});
 
 afterEach(() => {
   vi.unstubAllGlobals();
@@ -51,8 +72,9 @@
 
 // ponytail: the harness lives here while one page has a test; factor it
 // out to src/test/ when a second page gets one.
-/** Renders the page with the three API responses stubbed by URL; returns
- * the markup and the (url, Authorization) pairs fetch received. */
+/** Renders the page with the three API responses stubbed by URL, checks
+ * that fetch received exactly those URLs with the cookie's key, and
+ * returns the markup. */
 async function render(
   data: { serp: SerpAudits; brand: Brand; domains: Domain[] },
   sp: Params = {},
@@ -77,22 +99,19 @@
     params: Promise.resolve({ id: ID }),
     searchParams: Promise.resolve(sp),
   });
-  return { html: renderToStaticMarkup(element), calls };
+  expect(calls.map(([url]) => url).sort()).toEqual(
+    [`${BASE}/audits/serp`, BASE, `${BASE}/domains`].sort(),
+  );
+  expect(calls.every(([, auth]) => auth === "Bearer bsi_key_1")).toBe(true);
+  return { html: renderToStaticMarkup(element) };
 }
 
-const BUDGET =
-  "Audited automatically once a week; today the daily budget has no room for a Brand SERP audit, so a due audit waits until there is room. The budget resets at midnight UTC.";
-
 test("an active brand with no domain gets the no-domain line and the form", async () => {
-  const { html, calls } = await render({
-    serp: serp(false),
+  const { html } = await render({
+    serp: serp(),
     brand: brand("active"),
     domains: [],
   });
-  expect(calls.map(([url]) => url).sort()).toEqual(
-    [`${BASE}/audits/serp`, BASE, `${BASE}/domains`].sort(),
-  );
-  expect(calls.every(([, auth]) => auth === "Bearer bsi_key_1")).toBe(true);
   expect(html).toContain(
     "Not audited automatically: the brand has no declared domain.",
   );
@@ -105,10 +124,10 @@
 
 test("with a domain and no room, the budget note and the domain note show without the form", async () => {
   const { html } = await render(
-    { serp: serp(false), brand: brand("active"), domains: [DOMAIN] },
+    { serp: serp(), brand: brand("active"), domains: [DOMAIN] },
     { domain: "exists" },
   );
-  expect(html).toContain(BUDGET);
+  expect(html).toContain(BUDGET_NOTE);
   expect(html).toContain(
     "Not added: that domain is already declared for this brand.",
   );
@@ -118,18 +137,104 @@
 test("a brand that is not due shows no budget note", async () => {
   const { html } = await render({
     // The brand's own queued audit makes it not due (due_serp_audits()).
-    serp: serp(false, { status: "queued", error: null }, false),
+    serp: serp({ job: { status: "queued", error: null }, serp_due: false }),
     brand: brand("active"),
     domains: [DOMAIN],
   });
   expect(html).toContain("Audited automatically once a week.");
-  expect(html).not.toContain(BUDGET);
+  expect(html).not.toContain(BUDGET_NOTE);
   expect(html).toContain("Audit in progress");
 });
 
+test("an unconfigured provider outranks the budget note", async () => {
+  const { html } = await render({
+    serp: serp({ serp_configured: false }),
+    brand: brand("active"),
+    domains: [DOMAIN],
+  });
+  expect(html).toContain(
+    "Not audited automatically: the SERP provider is not configured.",
+  );
+  expect(html).not.toContain(BUDGET_NOTE);
+});
+
+test("three failed audits outrank the budget note", async () => {
+  const { html } = await render({
+    serp: serp({ failed_7d: 3 }),
+    brand: brand("active"),
+    domains: [DOMAIN],
+  });
+  expect(html).toContain(
+    "Not audited automatically: 3 audits failed in the last 7 days;",
+  );
+  expect(html).not.toContain(BUDGET_NOTE);
+});
+
+test("each audit gets a card: ownership, panels, the results, or the error", async () => {
+  const { html } = await render({
+    serp: serp({
+      budget_room: true,
+      audits: [
+        audit({
+          results: [
+            {
+              position: 1,
+              item_type: "organic",
+              result_type: "official",
+              url: "https://walkaroo.in/",
+              domain: "walkaroo.in",
+              title: "Walkaroo",
+              sitelinks: true,
+            },
+            {
+              position: 2,
+              item_type: "knowledge_graph",
+              result_type: "knowledge_panel",
+              url: "",
+              domain: "",
+              title: "Walkaroo (panel)",
+              sitelinks: false,
+            },
+          ],
+        }),
+        audit({
+          id: "6f1d2c3b-4a59-4e68-8d7c-9b0a1f2e3d4c",
+          kind: "reviews",
+          query: "walkaroo reviews",
+          error: "timeout",
+          owned: 0,
+          organic: 0,
+        }),
+      ],
+    }),
+    brand: brand("active"),
+    domains: [DOMAIN],
+  });
+  expect(html).not.toContain("No audit yet");
+  expect(html).toContain("<strong>walkaroo</strong>");
+  expect(html).toContain("IN/en · desktop · 2026-10-11 09:30 UTC");
+  expect(html).toContain("Ownership: 1 of 1 (100%)");
+  expect(html).toContain("knowledge_panel 1 · official 1");
+  expect(html).toContain("Knowledge Panel: yes · AI Overview: no");
+  expect(html).toContain('<span class="tag">official</span>');
+  expect(html).toContain('href="https://walkaroo.in/"');
+  expect(html).toContain('<td class="muted">walkaroo.in</td>');
+  // A result with no http(s) URL gets its title as text, not a link.
+  expect(html).toContain("<td>Walkaroo (panel)</td>");
+  expect(html).toContain("<strong>walkaroo reviews</strong>");
+  expect(html).toContain(
+    '<p class="down">Failed: the SERP provider took too long to answer</p>',
+  );
+  // The failed card renders the error in place of the results.
+  expect(html).not.toContain("Ownership: 0 of 0");
+  // Room in the budget: the plain weekly line, not the budget note.
+  expect(html).toContain("Audited automatically once a week.");
+  expect(html).not.toContain(BUDGET_NOTE);
+});
+
 test("an archived brand gets no form", async () => {
   const { html } = await render({
-    serp: serp(true),
+    serp: serp({ budget_room: true }),
     brand: brand("archived"),
     domains: [],
   });
diff -ruN a/apps/web/src/lib/api-paths.test.ts b/apps/web/src/lib/api-paths.test.ts
--- a/apps/web/src/lib/api-paths.test.ts	2026-10-11 18:14:42
+++ b/apps/web/src/lib/api-paths.test.ts	2026-10-11 22:28:48
@@ -53,8 +53,12 @@
   // String(form.get(...)) turns a missing field into "null", which seg()
   // passes; formSeg() refuses it. A field named by a variable
   // (String(form.get(k))) is caught too: label's actions read ids that way.
-  const RAW =
-    /String\(form\.get\("(?:[a-z_]*_id|type)"\)\)|String\(form\.get\(\w+\)\)|seg\(String\(/g;
+  // Any receiver name, either quote style, and the `as string` cast count.
+  const ID = String.raw`(?:"[a-z_]*_id"|'[a-z_]*_id'|"type"|'type')`;
+  const RAW = new RegExp(
+    String.raw`String\(\w+\.get\(${ID}\)\)|String\(\w+\.get\(\w+\)\)|seg\(String\(|\w+\.get\(${ID}\)\s+as\s+string`,
+    "g",
+  );
   const files = readdirSync(APP, { recursive: true, encoding: "utf8" }).filter(
     (f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f),
   );
diff -ruN a/apps/web/src/lib/api.test.ts b/apps/web/src/lib/api.test.ts
--- a/apps/web/src/lib/api.test.ts	2026-10-11 18:14:42
+++ b/apps/web/src/lib/api.test.ts	2026-10-11 22:28:48
@@ -9,7 +9,7 @@
   redirect: vi.fn(),
 }));
 
-const { api, formSeg, publicApi, seg } = await import("./api");
+const { api, COOKIE, formSeg, publicApi, seg } = await import("./api");
 const { cookies } = await import("next/headers");
 
 const stub = (status: number) =>
@@ -26,9 +26,11 @@
   vi.mocked(cookies).mockReset();
 });
 
+// Only the cookie api() reads carries the key, so a wrong name sends none.
 const signedIn = () =>
   vi.mocked(cookies).mockResolvedValue({
-    get: () => ({ value: "bsi_key_1" }),
+    get: (name: string) =>
+      name === COOKIE ? { value: "bsi_key_1" } : undefined,
   } as never);
 
 test.each([404, 422])("publicApi maps %i to notFound", async (status) => {
@@ -152,7 +154,10 @@
   const log = vi.spyOn(console, "error").mockImplementation(() => {});
   expect(() => formSeg(new FormData(), "brand_id")).toThrow("NOT_FOUND");
   expect(log).toHaveBeenCalledTimes(1);
-  expect(log).toHaveBeenCalledWith("API form value missing", '"brand_id"');
+  expect(log).toHaveBeenCalledWith(
+    "API form value missing or not text",
+    '"brand_id"',
+  );
 });
 
 test("formSeg refuses a file field and a value seg() refuses", () => {
@@ -162,6 +167,9 @@
   f.set("brand_id", "a/b");
   expect(() => formSeg(f, "csv")).toThrow("NOT_FOUND");
   expect(() => formSeg(f, "brand_id")).toThrow("NOT_FOUND");
-  expect(log).toHaveBeenCalledWith("API form value missing", '"csv"');
+  expect(log).toHaveBeenCalledWith(
+    "API form value missing or not text",
+    '"csv"',
+  );
   expect(log).toHaveBeenCalledWith("API path value refused", '"a/b"', 3);
 });
diff -ruN a/apps/web/src/lib/api.ts b/apps/web/src/lib/api.ts
--- a/apps/web/src/lib/api.ts	2026-10-11 18:14:42
+++ b/apps/web/src/lib/api.ts	2026-10-11 22:28:48
@@ -27,7 +27,7 @@
 export function formSeg(form: FormData, name: string): string {
   const value = form.get(name);
   if (typeof value === "string") return seg(value);
-  console.error("API form value missing", shown(name));
+  console.error("API form value missing or not text", shown(name));
   notFound();
 }
 
diff -ruN a/apps/web/src/lib/format.test.ts b/apps/web/src/lib/format.test.ts
--- a/apps/web/src/lib/format.test.ts	2026-10-11 18:14:42
+++ b/apps/web/src/lib/format.test.ts	2026-10-11 22:28:48
@@ -4,6 +4,7 @@
   alertNote,
   apiQuery,
   auditNote,
+  BUDGET_NOTE,
   ciText,
   crawlNote,
   domainNote,
@@ -282,8 +283,7 @@
     "Not audited automatically: the SERP provider is not configured.";
   const failed = (n: number) =>
     `Not audited automatically: ${n} audits failed in the last 7 days; the sweep tries again once fewer than 3 remain in that window.`;
-  const noBudget =
-    "Audited automatically once a week; today the daily budget has no room for a Brand SERP audit, so a due audit waits until there is room. The budget resets at midnight UTC.";
+  const noBudget = BUDGET_NOTE;
   const inactive = "Not audited automatically: the brand is not active.";
   expect(serpSchedule("active", 1, true, 1, true, true)).toBe(weekly);
   expect(serpSchedule("active", 1, true, 2, true, true)).toBe(weekly);
diff -ruN a/apps/web/src/lib/format.ts b/apps/web/src/lib/format.ts
--- a/apps/web/src/lib/format.ts	2026-10-11 18:14:42
+++ b/apps/web/src/lib/format.ts	2026-10-11 22:28:48
@@ -201,6 +201,10 @@
 /** failed audit_serp jobs in 7 days that stop the sweep (migration 0024). */
 const SERP_MAX_FAILURES = 3;
 
+/** The schedule line while the org's budget has no room for a due audit. */
+export const BUDGET_NOTE =
+  "Audited automatically once a week; today the daily budget has no room for a Brand SERP audit, so a due audit waits until there is room. The budget resets at midnight UTC.";
+
 /**
  * The Brand SERP page's schedule line. due_serp_audits() (migration 0024)
  * only considers active brands with at least one declared domain, and
@@ -229,7 +233,7 @@
           : failed7d >= SERP_MAX_FAILURES
             ? `Not audited automatically: ${failed7d} audits failed in the last 7 days; the sweep tries again once fewer than ${SERP_MAX_FAILURES} remain in that window.`
             : due && !budgetRoom
-              ? "Audited automatically once a week; today the daily budget has no room for a Brand SERP audit, so a due audit waits until there is room. The budget resets at midnight UTC."
+              ? BUDGET_NOTE
               : "Audited automatically once a week.";
 
 /** "3 of 10 (30%)"; no percentage when the page has no organic results. */
```

## Evidence

Proof directory: a fresh scratchpad copy of main a026e65 (`proof60-1791724431`), written only by the controller through an edit script with assert-counted replacements.

- Green, patched (after the review-round edits): the five changed backend files 111 passed (main collects 104 in them); the whole backend suite 1803 passed, 2 deselected, 2 warnings (the known Starlette/anyio warnings) with metrics coverage 100%; `npx vitest run` 91 passed (91); `tsc --noEmit` clean; `eslint .` clean; `ruff format --check` and `ruff check` clean on tests/.
- Red on main for 57:163: `DAILY_BUDGET_USD=0.01 uv run pytest tests/integration/test_api_serp.py::test_get_is_empty_before_any_audit` → 1 failed on main, 1 passed on the proof.
- The spec's first draft of the api-paths change included a block-comment strip; M10 showed main's scan already fails on that plant, so decision 5 dropped it.
- Spec review round 1 (Opus 5.5, 2026-10-11): the reviewer showed that a constant `false` for `budget_room` survived the page tests (7 passed), which the controller reproduced; R3 to R6 and decision 7 followed. The diff above is the proof after those edits: vitest 91 passed (91), tsc and eslint clean, the five backend files 111 passed, ruff clean; M4, M5, M6 and M11 re-run on it. The whole-suite count of 1803 is from the run before the round-1 edits, which changed no backend test count.

Mutations, each applied alone to the patched copy and reverted (the named test file run whole unless a single test is named):

| # | Mutation | Result |
|---|---|---|
| M1 | `SERP_AUDIT_DAYS = 6` in the Python mirror (SQL keeps 7) | killed: both kinds a minute inside the week, three failures a minute inside the week (2 failed, 28 passed in test_api_serp.py) |
| M2 | `SERP_RETRY_DAYS = 2` in the Python mirror (SQL keeps 1) | killed: a done job a minute outside the day (1 failed, 29 passed) |
| M3 | `serp_due` drops the queued-or-running clause | killed: a queued job, a running job 8 days ago (2 failed, 28 passed) |
| M4 | the crud race test's thread runs `1 / 0` | the failure is `ZeroDivisionError: division by zero` at the test's own line, not KeyError 'response' (1 failed) |
| M5 | the Brand SERP GET passes `lock=True` to `serp_budget_fits` | killed: `AssertionError: the thread did not finish within 5.0 s` (1 failed) |
| M6 | `api()` reads cookie `bsi_key_x` | killed: all 7 page cases (7 failed); api.test.ts's 26 tests pass, see Section 4 |
| M11 | the page passes a constant `false` for `budget_room` | killed: each audit gets a card (1 failed, 6 passed); before R3 the same mutant passed all 7 |
| M7 | `serpSchedule` checks the budget before the failure pause | killed: three failed audits outrank the budget note (1 failed, 6 passed) |
| M8 | `serpSchedule` checks the budget before "not configured" | killed: an unconfigured provider outranks the budget note, three failed audits outrank the budget note (2 failed, 5 passed) |
| M9 | a server action adds `String(fd.get('brand_id'))` and `form.get("type") as string` | killed: server actions read path values with formSeg() (1 failed, 1 passed); main's scan passes the same plant |
| M10 | a server action adds `/* see api(\`/brands */` and a template whose `${id}` skips `seg()` | killed by test 1 on this scan and on main's (1 failed, 1 passed each): already guarded, hence decision 5 |

## Rulings

Ruling: R1. Decided: `_job`'s `minutes` argument stays as it is; only `_audit` and `_aged` move to the DB clock. Found by: the controller, writing the proof. Why: Section 2's text said the `_job(minutes=...)` offsets would become timedeltas, but `minutes` sets `scheduled_slot`, which `serp_due` and `due_serp_audits()` never read; the offsets only keep the rows distinct. Cost if wrong: none to behaviour. How named: this spec and chat.

Ruling: R2. Decided: test_budget.py's lock test drops the `done` Event: `assert t.is_alive()` while blocked and, after release, the verdict from `t.result()` asserted True (the join moved into `finally` by R4). Found by: the controller, writing the proof; confirmed by the user (decision 6). Why: the Event duplicated `is_alive()`, and `result()` pins the verdict the old test never checked. Cost if wrong: none to behaviour. How named: this spec and chat.

Ruling: R3. Decided: the audit-cards case also asserts the plain weekly line, that the budget note is absent, the mapped `timeout` text and that the failed card has no "Ownership: 0 of 0" line; 57:153 moves from "already closed" to closed by this slice. Found by: the spec reviewer (Opus 5.5), 2026-10-11, findings 1 and 5. Why: the spec claimed 58:127 closed and 57:153 already closed, but no case pinned `budget_room` true on a brand that reaches the budget check, so a constant `false` passed all 7 page cases (reproduced); and Section 4 said the error branch was pinned when only "Failed: " was. Cost if wrong: none to behaviour. How named: this spec and chat.

Ruling: R4. Decided: the budget lock test and the no-wait test join in their `finally` blocks (`verdict = t.result()`; a second `t.result()` after the rollback). Found by: the spec reviewer, finding 2. Why: Section 1 said no thread outlives a test even when an assert fails, and those two tests did not do that. Cost if wrong: none to behaviour. How named: this spec and chat.

Ruling: R5. Decided: the dated note under 59:127 says the KeyError half is fixed and the 5-second judgement is kept by decision (Section 1), not fixed. Found by: the spec reviewer, finding 3. Why: the closure list claimed the whole item. Cost if wrong: none. How named: this spec and chat.

Ruling: R6. Decided: the `result()`-in-`finally` shape stays, with Section 1 saying what is reported when both the assert and `result()` raise. Found by: the spec reviewer, finding 6. Why: the shape trades a clearer first message for a join that always happens; stating the trade is enough. Cost if wrong: a less direct failure message. How named: this spec and chat.

Ruling: R7. Decided: the host-cap test's scheme post also asserts `errors[0]["loc"][-1] == "host"`, as Section 3 says; the diff above is regenerated from the proof with it (test_api_crud.py still 19 passed). Found by: the plan reviewer (Opus 5.5), 2026-10-11, finding 4. Why: Section 3 promised the `loc` assertion and the proof's diff had it only on the 201-character post. Cost if wrong: none to behaviour. How named: this spec, the plan and chat.

## Out of scope (slice 62 unless said otherwise)

- The "2 warnings" report items (57:157, 59:125, 59:129), 57:155 and 57:158 (behaviour and lock design), 59:120 and 59:132 (`${seg(id)}` after `formSeg` checks each value twice, a design choice), and the docs items.
- A shared render helper for a second page.

## Docs follow-ups

- Dated notes under every closed minor: findings-slice49.md line 102; findings-slice55.md line 119; findings-slice57.md lines 153 (closed by R3's assertions, not by slice 58), 160 and 163; findings-slice58.md lines 119, 120, 121, 124, 125, 126 and 127; findings-slice59.md lines 121 to 124, 126 to 128 (127's note: the KeyError half fixed, the 5-second judgement kept by decision, R5), 130 and 131.
- README rows for the slice 60 spec, plan and findings.
