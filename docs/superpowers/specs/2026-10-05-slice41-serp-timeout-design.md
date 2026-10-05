# Slice 41 design: the DataForSEO call waits up to 120 s; a timeout is recorded

## Context

Codebase facts: main `d049be7`, checked 2026-10-05.

The slice 37 live check was re-run on 2026-10-05 after the user said DataForSEO support had lifted the pause (observation log; recorded in findings-slice37 §2 by this slice). Both searches ended with status 0 and `ReadTimeout('The read operation timed out')` after 15.45 s and 15.53 s; the job failed `http` with cost 0; the free account call showed the balance go from `1` to `0.996` (inferred: the two calls were billed $0.004 in total). The user chose a slice for a longer timeout, then a re-run of the live check.

Facts read before the approaches:
- packages/core/bsi_core/crawl.py:47-49: `PHASE_TIMEOUT_SECONDS = 15` (connect, each read), `DEADLINE_SECONDS = 30` (the whole fetch). `http_fetch` (line 235) sets `deadline = time.monotonic() + DEADLINE_SECONDS` (line 266) and passes `httpx.Timeout(min(PHASE_TIMEOUT_SECONDS, left))` to each request (line 315); the deadline itself is checked before the lookup, before sending (lines 285, 296) and after each body chunk (line 333), so one fetch can take up to the deadline plus one phase, assuming the connect and send are quick and the headers arrive in one read (worker.py:85-90 budgets the rival crawl the same way); otherwise connect, write and each header read can each wait a full phase. An httpx exception becomes `Response(0, "", repr(e))` (line 356).
- Inferred, not read from code: a live SERP call sends nothing until the provider finishes, so its first read waits the whole processing time (consistent with the two 15.5 s timeouts).
- `http_fetch` is shared: crawl audits, entity, rival sitemaps (`SITEMAP_FETCH`), product feeds (`FEED_FETCH`), webhook delivery, the page audit (`run_page_audit`), scripts/score_page.py, scripts/snapshot_rival.py, and the SERP adapter. Tests monkeypatch `crawl.DEADLINE_SECONDS` (tests/unit/test_http_fetch.py:385) and `DNS_TIMEOUT_SECONDS`; no test monkeypatches `PHASE_TIMEOUT_SECONDS`.
- DataForSEO's help centre advises a 120-second timeout for SERP API calls (https://dataforseo.com/help-center/best-practices-live-endpoints-in-dataforseo-api).
- apps/workers/bsi_workers/worker.py: `MAX_SERP_LOCALES = 5` (line 120), two queries per locale, calls made one after another; `SERP_JOB_MICROS = 40_000` with the comment "5 locales x 2 queries x $0.004". `claim_job()` (migration 0007) fails a job `running` for over 10 minutes as `stale` on the next claim; `_finish_job` then discards the late outcome but keeps the spend.
- packages/core/bsi_core/providers/dataforseo.py: `serp()` returns `_refused(resp)` for any non-ok response; a status-0 response has an empty body, so it is `http` with cost 0 (`test_an_http_failure_is_http` pins `Response(0, error="timeout")` and a 500).
- apps/web/src/lib/format.ts `SERP_ERRORS` labels every adapter code; an unknown code is shown as is.

Classification: **bounded** — two keyword parameters on an existing function, the adapter passing them, one constant, one error branch and one label; said in chat as the first line of the first brainstorming reply. The user's process rule asks for a spec even for small changes, so this file exists.

Decisions approved in chat (brainstorming on Opus 5.5, 2026-10-05), each after approaches with trade-offs, the facts above and a recommendation written in a chat message before the question:
1. A SERP call waits up to 120 s (R1), over 55 s; the first answer also chose 2 locales per audit, superseded by decision 4.
2. A call that times out records the expected price (4,000 micros) and error `timeout` with a page label (R2), over leaving it `http` at cost 0, or the expected price with `http`.
3. Design Sections 1 and 2, the text of each in chat before its approval question (the user answered "go ahead" to each; the controller read both as approval and said so in chat, and flagged this reading again after the spec review).
4. After the spec review of e69a73e showed a call can take about 240 s (a 120 s read, then up to a 120 s body read before the deadline check), so 2 locales could reach about 16 minutes: an audit covers 1 locale (R5), over 2 locales with a time-boxed job, or 2 locales with the bound as a known limit.
5. After the re-review of 8a83d47 showed the ~240 s bound assumes a quick connect and send and headers in one read: the assumption is stated and the rest is a known limit (R8), over a separate 120 s read timeout with connect and write kept at 15 s.

## Design

### `http_fetch`

packages/core/bsi_core/crawl.py, as a diff against main `d049be7`:

```diff
@@ -246,2 +246,4 @@ def http_fetch(
     headers: Mapping[str, str] | None = None,
+    deadline_seconds: float | None = None,
+    phase_seconds: float | None = None,
 ) -> Response:
@@ -251,5 +253,6 @@ def http_fetch(
     The body is decoded here, not by httpx, so a compressed body never
-    inflates past `cap`. The 30 s deadline covers resolving,
-    connecting, sending and reading on every hop; a lookup waits at most
-    DNS_TIMEOUT_SECONDS or the time left, whichever is less.
+    inflates past `cap`. The deadline (DEADLINE_SECONDS unless
+    `deadline_seconds` is given) covers resolving, connecting, sending and
+    reading on every hop; a lookup waits at most DNS_TIMEOUT_SECONDS or the
+    time left, whichever is less.
 
@@ -263,5 +266,9 @@ def http_fetch(
     bytes back. `headers` go on every hop; Host, User-Agent and
-    Accept-Encoding are always the pinned ones.
+    Accept-Encoding are always the pinned ones. `deadline_seconds` and
+    `phase_seconds` replace DEADLINE_SECONDS and PHASE_TIMEOUT_SECONDS for
+    this fetch.
     """
-    deadline = time.monotonic() + DEADLINE_SECONDS
+    limit = DEADLINE_SECONDS if deadline_seconds is None else deadline_seconds
+    phase = PHASE_TIMEOUT_SECONDS if phase_seconds is None else phase_seconds
+    deadline = time.monotonic() + limit
     try:
@@ -314,3 +321,3 @@ def http_fetch(
                     extensions=ext,
-                    timeout=httpx.Timeout(min(PHASE_TIMEOUT_SECONDS, left)),
+                    timeout=httpx.Timeout(min(phase, left)),
                 ) as r:
```

Every other caller passes neither parameter, so its limits are unchanged (pinned by `test_a_plain_fetch_keeps_the_15_s_phase_timeout` and the existing deadline tests). The defaults are read at call time; monkeypatching `DEADLINE_SECONDS` still works (pinned at test_http_fetch.py:385). The `_TIMED_OUT` message keeps saying "30 s"; it reaches only `Response.error`, which the SERP adapter does not store.

### The adapter

packages/core/bsi_core/providers/dataforseo.py:

```diff
@@ -16,2 +16,4 @@ SERP_UA = "bsi-platform-serp/1.0"
 SERP_CAP_BYTES = 4 * 1024 * 1024
+SERP_TIMEOUT_SECONDS = 120  # DataForSEO's advice for live SERP calls
+TIMEOUT_MICROS = 4_000  # one call's expected price, about $0.004
 # ponytail: a static table of the provider's location names, one line
@@ -52,2 +54,4 @@ class SerpFetch(Protocol):
         headers: Mapping[str, str] | None = None,
+        deadline_seconds: float | None = None,
+        phase_seconds: float | None = None,
     ) -> Response: ...
@@ -210,4 +214,9 @@ def serp(
         headers={"Authorization": f"Basic {token}"},
+        deadline_seconds=SERP_TIMEOUT_SECONDS,
+        phase_seconds=SERP_TIMEOUT_SECONDS,
     )
     if not resp.ok:
+        if resp.status == 0 and (resp.error or "").startswith("ReadTimeout"):
+            # Sent but not answered in time: the provider may bill it.
+            return SerpPage(cost_micros=TIMEOUT_MICROS, error="timeout")
         return _refused(resp)
```

- Only httpx's `ReadTimeout` counts as `timeout`: the request was sent and the answer did not arrive, as on 2026-10-05. It records 4,000 micros, about $0.004, the expected price inferred from the published prices (findings-slice37 line 59).
  - Note (2026-10-05, R14): the re-run before merge observed $0.002 per call, so `TIMEOUT_MICROS` is 2,000 (fix commit after the three tasks; the ruling is in the ledger and goes into this spec's Rulings after merge).
- Every other status-0 response stays `http` with cost 0: `ConnectTimeout`, `WriteTimeout`, `PoolTimeout`, `ConnectError`, a refused or unresolved host, and `http_fetch`'s own deadline message. For the SERP fetch (deadline = phase = 120 s, lookup at most 10 s) the deadline message cannot fire before sending; it fires only mid-body, after the provider answered, so that case is likely billed yet recorded at 0 (Out of scope).

### The worker

apps/workers/bsi_workers/worker.py:

```diff
@@ -117,5 +117,9 @@ class Poster(Protocol):
 
-# 5 locales x 2 queries x $0.004 (a live page plus AI Overview loading).
+# Kept from 5 locales x 2 queries x $0.004 (a live page plus AI Overview
+# loading); with one locale it overestimates, which fails closed.
 SERP_JOB_MICROS = 40_000
-MAX_SERP_LOCALES = 5
+# One locale: 2 calls of up to ~240 s each (a 120 s read, then up to a
+# 120 s body read before the deadline check) stay under claim_job()'s
+# 10 minutes, assuming a quick connect and send and headers in one read.
+MAX_SERP_LOCALES = 1
 
@@ -1168,4 +1172,4 @@ def tick(
     A job is claimed before an observation: jobs are rare, user-facing
-    and about a minute long, so a 9,000-observation run must not delay
-    one for hours.
+    and at most a few minutes long (a SERP audit up to about 8), so a
+    9,000-observation run must not delay one for hours.
     """
```

One locale is 2 calls; at up to about 240 s each (plus at most 10 s of lookup inside each call's deadline) the audit stays under 10 minutes, assuming a quick connect and send and headers in one read (R8). `SERP_JOB_MICROS` stays 40,000; it overestimates (2 calls × 4,000 = 8,000), which fails closed.

### The page

apps/web/src/lib/format.ts: `SERP_ERRORS` gains, after `rate`:

```ts
  timeout: "the SERP provider took too long to answer",
```

No schema, migration or API change; the OpenAPI types are unaffected.

### Tests

tests/unit/test_http_fetch.py:

```diff
@@ -340,2 +340,22 @@ def test_a_transport_error_is_a_response_not_an_exception():
 
+def test_a_fetch_can_ask_for_its_own_phase_timeout():
+    t = server(ok)
+    r = http_fetch(
+        "https://nike.com/",
+        "UA",
+        resolve=dns({"nike.com": [PUBLIC]}),
+        transport=t,
+        deadline_seconds=120,
+        phase_seconds=40,
+    )
+    assert r.status == 200
+    assert set(t.seen[0].extensions["timeout"].values()) == {40.0}
+
+
+def test_a_plain_fetch_keeps_the_15_s_phase_timeout():
+    r, seen = fetch("https://nike.com/", {"nike.com": [PUBLIC]})
+    assert r.status == 200
+    assert set(seen[0].extensions["timeout"].values()) == {15.0}
+
+
 def test_each_request_timeout_is_capped_by_the_time_left(monkeypatch):
@@ -393,2 +413,19 @@ def test_the_lookup_wait_is_capped_by_the_time_left(monkeypatch, hang):
 
+def test_a_fetch_can_ask_for_its_own_deadline(monkeypatch, hang):
+    # The 10 s lookup wait is cut to this fetch's 0.2 s deadline.
+    monkeypatch.setattr("bsi_core.crawl.DNS_TIMEOUT_SECONDS", 10)
+    t = server(ok)
+    start = time.monotonic()
+    r = http_fetch(
+        "https://nike.com/",
+        "UA",
+        resolve=hang,
+        transport=t,
+        deadline_seconds=0.2,
+    )
+    assert time.monotonic() - start < 1
+    assert r.error == "refused: nike.com did not resolve in time"
+    assert t.seen == []
+
+
 def test_an_abandoned_lookup_still_queued_never_runs(monkeypatch, hang):
```

tests/unit/test_dataforseo.py:

```diff
@@ -149,2 +149,29 @@ def test_an_http_failure_is_http(response):
 
+def test_the_call_waits_for_the_serp_timeout():
+    fetch = Fetch(Response(200, body()))
+    _serp(fetch)
+    [(_, _, kw)] = fetch.calls
+    assert (kw["deadline_seconds"], kw["phase_seconds"]) == (120, 120)
+
+
+def test_a_read_timeout_is_timeout_with_the_expected_cost():
+    resp = Response(0, error="ReadTimeout('The read operation timed out')")
+    assert _serp(Fetch(resp)) == SerpPage([], 4_000, "timeout")
+
+
+@pytest.mark.parametrize(
+    "error",
+    [
+        "ConnectTimeout('timed out')",
+        "WriteTimeout('timed out')",
+        "PoolTimeout('timed out')",
+        "ConnectError('boom')",
+        "refused: nike.com does not resolve",
+        "timeout: over the 30 s deadline",
+    ],
+)
+def test_other_status_0_failures_are_http(error):
+    assert _serp(Fetch(Response(0, error=error))) == SerpPage([], 0, "http")
+
+
 def test_a_cut_body_is_truncated():
```

tests/integration/test_serp_audit.py:

```diff
@@ -214,3 +214,3 @@ def test_missing_credentials_fail_with_no_call_and_no_rows(
 
-def test_only_the_first_five_locales_are_audited(
+def test_only_the_first_locale_is_audited(
     configured, owner, make_org, make_brand
@@ -229,5 +229,5 @@ def test_only_the_first_five_locales_are_audited(
     assert _run(fetch) is True
-    assert len(fetch.calls) == 10 and len(_rows(owner, bid)) == 10
+    assert len(fetch.calls) == 2 and len(_rows(owner, bid)) == 2
     job = _load_job(owner, job_id)
-    assert (job.status, job.cost_micros) == ("done", 40_000)
+    assert (job.status, job.cost_micros) == ("done", 8_000)
 
```

apps/web/src/lib/format.test.ts, after the "unverified or paused" test:

```ts
test("serpError labels a SERP call that timed out", () => {
  expect(serpError("timeout")).toBe(
    "the SERP provider took too long to answer",
  );
});
```

11 new backend test cases and 1 renamed test (backend 1693 → 1704, computed); 1 new vitest (the whole suite, 48 → 49).

### Proof

Run 2026-10-05 in the scratchpad (copies of `packages/core/bsi_core` and `apps/workers/bsi_workers` imported via `PYTHONPATH`, each run's `bsi_core.crawl.__file__` and `bsi_workers.worker.__file__` checked to be the copy; the three test files are the repo's with the changes above; the integration file ran against the shared test DB):

| Code | Result | Failing tests |
|---|---|---|
| main (`d049be7`) | `5 failed, 147 passed` | `test_a_fetch_can_ask_for_its_own_phase_timeout`, `test_a_fetch_can_ask_for_its_own_deadline`, `test_the_call_waits_for_the_serp_timeout`, `test_a_read_timeout_is_timeout_with_the_expected_cost`, `test_only_the_first_locale_is_audited` |
| patched | `152 passed` | — |
| m1: the adapter passes no timeouts | `1 failed, 151 passed` | `test_the_call_waits_for_the_serp_timeout` |
| m2: `ReadTimeout` not recognised | `1 failed, 151 passed` | `test_a_read_timeout_is_timeout_with_the_expected_cost` |
| m3: a timeout records cost 0 | `1 failed, 151 passed` | `test_a_read_timeout_is_timeout_with_the_expected_cost` |
| m4: any error containing "Timeout" counts | `3 failed, 149 passed` | `test_other_status_0_failures_are_http` for `ConnectTimeout`, `WriteTimeout`, `PoolTimeout` |
| m5: `http_fetch` ignores `phase_seconds` | `1 failed, 151 passed` | `test_a_fetch_can_ask_for_its_own_phase_timeout` |
| m6: `http_fetch` ignores `deadline_seconds` | `2 failed, 150 passed` | the phase test (its 40 s is capped by the 30 s left); `test_a_fetch_can_ask_for_its_own_deadline` |
| m7: `MAX_SERP_LOCALES` back to 5 | `1 failed, 151 passed` | `test_only_the_first_locale_is_audited` |
| m8: the default phase becomes the deadline | `1 failed, 151 passed` | `test_a_plain_fetch_keeps_the_15_s_phase_timeout` |
| m9: write and pool timeouts count as `timeout` | `2 failed, 150 passed` | `test_other_status_0_failures_are_http` for `WriteTimeout`, `PoolTimeout` |

`test_a_plain_fetch_keeps_the_15_s_phase_timeout` and the 6 `test_other_status_0_failures_are_http` cases pass on main (they pin existing behaviour against m8, m4 and m9). `ruff check` and `ruff format --check` on the three patched modules and three test files: pass; `mypy --strict` on the patched `bsi_core`: no issues. The web label and its vitest were not run in scratch (vitest cannot run files outside the repo); execution shows them red and green in the repo.

### Docs

- Code PR: this spec, the plan, two docs/README.md rows, and two dated notes in docs/findings-slice37.md: this one appended to §2 (after its last bullet, before "## 3."):

- Note (2026-10-05, slice 41): a fourth attempt ran on 2026-10-05, after the user said support had lifted the pause; it returned no page. Observed (controller's terminal output, dev queries and the observation log): Docker was not running and was started, with the dev DB left running afterwards; `.env` login 14 characters (22 on 2026-10-03), password 16; the free account call at 13:17:41 UTC returned HTTP 200, `20000`/`20000`, balance `1`; `POST /v1/brands/1eb6c00a-…/audits/serp` returned 202, job `033eccf7`, and a following `GET …/audits/serp` returned 200 (`api_key.last_used_at` read afterwards: 2026-10-05 13:17:56 UTC; that both requests wrote it is the writer's reading of the code); one `process_job` run with a recording wrapper: "Walkaroo" India/en ended at 13:18:25 and "Walkaroo reviews" at 13:18:41, each with status 0 and `ReadTimeout('The read operation timed out')` after 15.45 s and 15.53 s; the job failed `http`, cost 0, and wrote two `serp_audit` rows, `http` at cost 0; the free account call at 13:18:56 returned balance `0.996`; no retry was made. Inferred: the two timed-out searches were billed $0.004 in total (split unknown) and recorded as 0. Cause: `http_fetch` gives each read 15 s (`PHASE_TIMEOUT_SECONDS`) inside a 30 s deadline; DataForSEO advises a 120 s timeout for SERP calls. Addressed in slice 41 (a 120 s SERP timeout; docs/superpowers/specs/2026-10-05-slice41-serp-timeout-design.md); unconfirmed until the live check is re-run. Still unconfirmed: `location_name` "India", the latency of a successful call, the real cost per call, the classification of a real page.

  and this one under the §3 "Untested" line that names "which five locales the cap keeps":

  - Note (2026-10-05, slice 41): the cap is now one locale (`MAX_SERP_LOCALES = 1`, slice 41 R5), so this item reads "which locale the cap keeps".

  and, added by R11, this one under the §3 "Out of scope (spec)" line that names "a longer fetch deadline":

  - Note (2026-10-05, slice 41): the SERP call now has a longer fetch deadline: it passes 120 s as `http_fetch`'s new `deadline_seconds` and `phase_seconds` (slice 41 R1, R11).
- Post-merge docs PR: the plan's "Changes made during execution", rulings from execution, deferred minors.
- After merge: the slice 37 live check is re-run only after the user is asked (free account call, then one audit of 2 searches, about $0.008 inferred), recorded in its own docs PR.

### Out of scope

- A deadline hit mid-body (after the provider answered) stays `http` at cost 0, though likely billed.
- A slow connect or send, or headers arriving over several reads, can each wait up to 120 s, so one call could take about 360 s and the 10-minute bound would not hold (R8).
- Brands with 2 or more locales are audited on their first only (the job's summary counts the skipped ones; every dev brand has one).
- `SERP_JOB_MICROS` is not lowered (it overestimates; fails closed).

## Rulings

- **R1: 120 s per SERP call.** Decided: `SERP_TIMEOUT_SECONDS = 120` passed as both `deadline_seconds` and `phase_seconds`; the user chose this (with 2 locales, later changed by R5) over 120 s with a time-boxed job, or 55 s with 5 locales. Found by: the brainstorm, after the 2026-10-05 live check. Why: DataForSEO's advice. Cost if wrong: a call that needs more than 120 s still times out. Asked in chat.
- **R2: a timed-out call records the expected price as `timeout`.** Decided: a status-0 `ReadTimeout` gives `SerpPage(cost_micros=4_000, error="timeout")` and a page label; the user chose this over leaving it `http` at cost 0, or the expected price with `http`. Found by: the brainstorm (the balance fell $0.004 while 0 was recorded). Why: the budget fails closed and the cause is visible. Cost if wrong: $0.004 overcounted for a timeout the provider did not bill. Asked in chat.
- **R3: the locale test does not check `skipped_locales`.** Decided: the test checks the calls, the rows and the job cost; Section 2 had said it would check `skipped_locales`. Found by: the controller, writing the proof. Why: the summary string is neither stored nor returned by `process_job`; testing it (calling `run_serp_audit` directly, or reading the worker's log with caplog) was not pursued. Cost if wrong: the skipped count stays untested. Named in chat when made.
- **R4: commits carry the Opus 5.5 trailer.** Decided: slice 41 commits end with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>", and subagents are dispatched with no `model` parameter (the session is on Opus 5.5). Found by: the controller at the start of the slice. Why: the memory rules. Cost if wrong: none. Named in chat when made.
- **R5: an audit covers 1 locale.** Decided: `MAX_SERP_LOCALES = 1`; the user chose this over 2 locales with a time-boxed job, or 2 locales with the bound as a known limit; asked again because the fact behind R1's 2 locales was wrong. Found by: the spec review of e69a73e (Important 1: a call can take about 240 s, so 4 calls could reach about 16 minutes). Why: 2 calls × 240 s stays under `claim_job()`'s 10 minutes. Cost if wrong: a brand's later locales are not audited. Asked in chat.
- **R6: more pins.** Decided: `test_a_plain_fetch_keeps_the_15_s_phase_timeout` (mutant m8); `test_a_connect_timeout_is_http` becomes `test_other_status_0_failures_are_http` over six status-0 errors (mutants m4, m9); the monkeypatch claim names `DEADLINE_SECONDS` only. Found by: the spec review of e69a73e (Important 2; Minors 2, 3). Why: each stated behaviour has a failing mutant. Cost if wrong: none. Named in chat when made.
- **R7: the spec review's accuracy points.** Decided: the findings note says "Addressed … unconfirmed until the live check is re-run" and lists the check's dev writes and "ended at" times; the deadline-message bullet is corrected for the SERP fetch; the caller list is complete; the provider's behaviour is marked inferred; R3's reason is reworded; the stale `SERP_JOB_MICROS` comment, the `http_fetch` "30 s deadline" docstring and the `tick` "about a minute" docstring are updated in the code, and findings-slice37's "which five locales" line gets a dated note; the vitest count names the whole suite. Found by: the spec review of e69a73e (Important 3; Minors 1, 4–9). Why: no claim wider than its source. Cost if wrong: none. Named in chat when made.
- **R8: the per-call bound's assumption is stated.** Decided: the spec and the worker comment say the ~240 s per call assumes a quick connect and send and headers in one read; a slower call is a known limit in Out of scope; the user chose this over a separate 120 s read timeout with connect and write kept at 15 s. Found by: the re-review of 8a83d47 (N1: one call could take about 360 s). Why: no code change for a pathological case; the same assumption as the rival-crawl budget. Cost if wrong: a slow connect could push an audit past 10 minutes and let a second worker fail it as `stale`. Asked in chat.
- **R9: the re-review's other wording point, with no further re-review.** Decided: the findings note says the POST and a following GET wrote `api_key.last_used_at` (max 13:17:56 UTC by the DB clock) and that its other times are the controller's clock. Found by: the re-review of 8a83d47 (N2). Why: no claim wider than its source. Cost if wrong: none; wording only. Named in chat when made.
- **R10: the plan review's wording points.** (Added with the plan.) Decided: the plan's Task 3 Step 4 expects `Tests  28 passed (28)`, and its self-review names rulings R1–R9. Found by: the plan review of 840e66a (Minors 1, 2; "Ready to execute? Yes"). Why: an expected output the implementer will see. Cost if wrong: none. Named in chat when made.
- **R11: a dated note on findings-slice37's "a longer fetch deadline".** (Added with the plan.) Decided: the §3 "Out of scope (spec)" line gets a dated note in the code PR; the user chose this over adding it after merge, or leaving it. Found by: the plan review of 840e66a (Minor 3). Why: the findings stay consistent as soon as the code merges. Cost if wrong: none. Asked in chat.
