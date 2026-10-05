# Slice 41 design: the DataForSEO call waits up to 120 s; a timeout is recorded

## Context

Codebase facts: main `d049be7`, checked 2026-10-05.

The slice 37 live check was re-run on 2026-10-05 after the user said DataForSEO support had lifted the pause (observation log; recorded in findings-slice37 §2 by this slice). Both searches ended with status 0 and `ReadTimeout('The read operation timed out')` after 15.45 s and 15.53 s; the job failed `http` with cost 0; the free account call showed the balance go from `1` to `0.996` (inferred: the two calls were billed $0.004 in total). The user chose a slice for a longer timeout, then a re-run of the live check.

Facts read before the approaches:
- packages/core/bsi_core/crawl.py:47-49: `PHASE_TIMEOUT_SECONDS = 15` (connect, each read), `DEADLINE_SECONDS = 30` (the whole fetch). `http_fetch` sets `deadline = time.monotonic() + DEADLINE_SECONDS` (line 266) and passes `httpx.Timeout(min(PHASE_TIMEOUT_SECONDS, left))` to each request (line 315). A live SERP call sends nothing until the provider finishes, so the first read waits 15 s. An httpx timeout becomes `Response(0, "", repr(e))` (line 356).
- `http_fetch` is shared: crawl audits, entity, rival sitemaps (`SITEMAP_FETCH`), product feeds (`FEED_FETCH`), webhook delivery and the SERP adapter. Tests monkeypatch `crawl.DEADLINE_SECONDS` (tests/unit/test_http_fetch.py:385) and `DNS_TIMEOUT_SECONDS`.
- DataForSEO's help centre advises a 120-second timeout for SERP API calls (https://dataforseo.com/help-center/best-practices-live-endpoints-in-dataforseo-api).
- apps/workers/bsi_workers/worker.py: `MAX_SERP_LOCALES = 5` (line 120), two queries per locale, calls made one after another; `SERP_JOB_MICROS = 40_000`. `claim_job()` (migration 0007) fails a job `running` for over 10 minutes as `stale` on the next claim; `_finish_job` then discards the late outcome but keeps the spend.
- packages/core/bsi_core/providers/dataforseo.py: `serp()` returns `_refused(resp)` for any non-ok response; a status-0 response has an empty body, so it is `http` with cost 0 (`test_an_http_failure_is_http` pins `Response(0, error="timeout")` and a 500).
- apps/web/src/lib/format.ts `SERP_ERRORS` labels every adapter code; an unknown code is shown as is.

Classification: **bounded** — two keyword parameters on an existing function, the adapter passing them, one constant, one error branch and one label; said in chat as the first line of the first brainstorming reply. The user's process rule asks for a spec even for small changes, so this file exists.

Decisions approved in chat (brainstorming on Opus 5.5, 2026-10-05), each after approaches with trade-offs, the facts above and a recommendation written in a chat message before the question:
1. A SERP call waits up to 120 s, and an audit covers at most 2 locales (R1), over 120 s with a time-boxed job, or 55 s with 5 locales.
2. A call that times out records the expected price (4,000 micros) and error `timeout` with a page label (R2), over leaving it `http` at cost 0, or the expected price with `http`.
3. Design Sections 1 and 2, the text of each in chat before its approval question (the user answered "go ahead" to each; the controller read both as approval and said so in chat).

## Design

### `http_fetch`

packages/core/bsi_core/crawl.py, as a diff against main `d049be7`:

```diff
@@ -246,2 +246,4 @@ def http_fetch(
     headers: Mapping[str, str] | None = None,
+    deadline_seconds: float | None = None,
+    phase_seconds: float | None = None,
 ) -> Response:
@@ -263,5 +265,9 @@ def http_fetch(
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
@@ -314,3 +320,3 @@ def http_fetch(
                     extensions=ext,
-                    timeout=httpx.Timeout(min(PHASE_TIMEOUT_SECONDS, left)),
+                    timeout=httpx.Timeout(min(phase, left)),
                 ) as r:
```

Every other caller passes neither parameter, so its limits are unchanged; the defaults are read at call time, so monkeypatching the constants still works. The `_TIMED_OUT` message keeps saying "30 s"; it reaches only `Response.error`, which the SERP adapter does not store.

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
- A `ConnectTimeout`, a refused or unresolved host, and `http_fetch`'s own deadline message (which mostly fires before sending) stay `http` with cost 0. A deadline hit while a body is being read is a known limit: it stays `http`.

### The worker

apps/workers/bsi_workers/worker.py:

```diff
@@ -119,3 +119,3 @@ class Poster(Protocol):
 SERP_JOB_MICROS = 40_000
-MAX_SERP_LOCALES = 5
+MAX_SERP_LOCALES = 2  # 4 calls x 120 s stays under claim_job()'s 10 minutes
 
```

`SERP_JOB_MICROS` stays 40,000; it now overestimates (4 calls × 4,000 = 16,000), which fails closed.

### The page

apps/web/src/lib/format.ts: `SERP_ERRORS` gains, after `rate`:

```ts
  timeout: "the SERP provider took too long to answer",
```

No schema, migration or API change; the OpenAPI types are unaffected.

### Tests

tests/unit/test_http_fetch.py:

```diff
@@ -340,2 +340,16 @@ def test_a_transport_error_is_a_response_not_an_exception():
 
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
 def test_each_request_timeout_is_capped_by_the_time_left(monkeypatch):
@@ -393,2 +407,19 @@ def test_the_lookup_wait_is_capped_by_the_time_left(monkeypatch, hang):
 
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
@@ -149,2 +149,19 @@ def test_an_http_failure_is_http(response):
 
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
+def test_a_connect_timeout_is_http():
+    resp = Response(0, error="ConnectTimeout('timed out')")
+    assert _serp(Fetch(resp)) == SerpPage([], 0, "http")
+
+
 def test_a_cut_body_is_truncated():
```

tests/integration/test_serp_audit.py:

```diff
@@ -214,3 +214,3 @@ def test_missing_credentials_fail_with_no_call_and_no_rows(
 
-def test_only_the_first_five_locales_are_audited(
+def test_only_the_first_two_locales_are_audited(
     configured, owner, make_org, make_brand
@@ -229,5 +229,5 @@ def test_only_the_first_five_locales_are_audited(
     assert _run(fetch) is True
-    assert len(fetch.calls) == 10 and len(_rows(owner, bid)) == 10
+    assert len(fetch.calls) == 4 and len(_rows(owner, bid)) == 4
     job = _load_job(owner, job_id)
-    assert (job.status, job.cost_micros) == ("done", 40_000)
+    assert (job.status, job.cost_micros) == ("done", 16_000)
 
```

apps/web/src/lib/format.test.ts, after the "unverified or paused" test:

```ts
test("serpError labels a SERP call that timed out", () => {
  expect(serpError("timeout")).toBe(
    "the SERP provider took too long to answer",
  );
});
```

5 new backend tests and 1 renamed (backend 1693 → 1698, computed); 1 new vitest (48 → 49).

### Proof

Run 2026-10-05 in the scratchpad (copies of `packages/core/bsi_core` and `apps/workers/bsi_workers` imported via `PYTHONPATH`, each run's `bsi_core.crawl.__file__` and `bsi_workers.worker.__file__` checked to be the copy; the three test files are the repo's with the changes above; the integration file ran against the shared test DB):

| Code | Result | Failing tests |
|---|---|---|
| main (`d049be7`) | `5 failed, 141 passed` | `test_a_fetch_can_ask_for_its_own_phase_timeout`, `test_a_fetch_can_ask_for_its_own_deadline`, `test_the_call_waits_for_the_serp_timeout`, `test_a_read_timeout_is_timeout_with_the_expected_cost`, `test_only_the_first_two_locales_are_audited` |
| patched | `146 passed` | — |
| m1: the adapter passes no timeouts | `1 failed, 145 passed` | `test_the_call_waits_for_the_serp_timeout` |
| m2: `ReadTimeout` not recognised | `1 failed, 145 passed` | `test_a_read_timeout_is_timeout_with_the_expected_cost` |
| m3: a timeout records cost 0 | `1 failed, 145 passed` | `test_a_read_timeout_is_timeout_with_the_expected_cost` |
| m4: any error containing "Timeout" counts | `1 failed, 145 passed` | `test_a_connect_timeout_is_http` |
| m5: `http_fetch` ignores `phase_seconds` | `1 failed, 145 passed` | `test_a_fetch_can_ask_for_its_own_phase_timeout` |
| m6: `http_fetch` ignores `deadline_seconds` | `2 failed, 144 passed` | the phase test (its 40 s is capped by the 30 s left); `test_a_fetch_can_ask_for_its_own_deadline` |
| m7: `MAX_SERP_LOCALES` back to 5 | `1 failed, 145 passed` | `test_only_the_first_two_locales_are_audited` |

`test_a_connect_timeout_is_http` passes on main (it pins existing behaviour against m4). `ruff check` and `ruff format --check` on the three patched modules and three test files: pass; `mypy --strict` on the patched `bsi_core`: no issues. The web label and its vitest were not run in scratch (vitest cannot run files outside the repo); execution shows them red and green in the repo.

### Docs

- Code PR: this spec, the plan, two docs/README.md rows, and this dated note appended to docs/findings-slice37.md §2 (after its last bullet, before "## 3."):

- Note (2026-10-05, slice 41): a fourth attempt ran on 2026-10-05, after the user said support had lifted the pause; it returned no page. Observed (controller's terminal output, dev queries and the observation log): `.env` login 14 characters (22 on 2026-10-03), password 16; the free account call at 13:17:41 UTC returned HTTP 200, `20000`/`20000`, balance `1`; `POST /v1/brands/1eb6c00a-…/audits/serp` returned 202, job `033eccf7`; one `process_job` run with a recording wrapper: "Walkaroo" India/en at 13:18:25 and "Walkaroo reviews" at 13:18:41 each ended with status 0 and `ReadTimeout('The read operation timed out')` after 15.45 s and 15.53 s; the job failed `http`, cost 0, with two `http` rows at cost 0; the free account call at 13:18:56 returned balance `0.996`. Inferred: the two timed-out searches were billed $0.004 in total (split unknown) and recorded as 0. Cause: `http_fetch` gives each read 15 s (`PHASE_TIMEOUT_SECONDS`) inside a 30 s deadline; DataForSEO advises a 120 s timeout for SERP calls. Fixed in slice 41 (docs/superpowers/specs/2026-10-05-slice41-serp-timeout-design.md). Still unconfirmed: `location_name` "India", the latency of a successful call, the real cost per call, the classification of a real page.

- Post-merge docs PR: the plan's "Changes made during execution", rulings from execution, deferred minors.
- After merge: the slice 37 live check is re-run only after the user is asked (free account call, then one audit of 2 searches, about $0.008 inferred), recorded in its own docs PR.

### Out of scope

- A deadline hit mid-body stays `http` at cost 0 (rare with a 120 s read timeout).
- Brands with 3 or more locales have the extra ones skipped (the job's summary counts them; every dev brand has one).
- `SERP_JOB_MICROS` is not lowered (it overestimates; fails closed).

## Rulings

- **R1: 120 s per SERP call; at most 2 locales per audit.** Decided: `SERP_TIMEOUT_SECONDS = 120` passed as both `deadline_seconds` and `phase_seconds`; `MAX_SERP_LOCALES = 2`; the user chose this over 120 s with a time-boxed job, or 55 s with 5 locales. Found by: the brainstorm, after the 2026-10-05 live check. Why: DataForSEO's advice; 4 calls × 120 s stays under `claim_job()`'s 10 minutes. Cost if wrong: brands with 3+ locales are audited on their first 2 only. Asked in chat.
- **R2: a timed-out call records the expected price as `timeout`.** Decided: a status-0 `ReadTimeout` gives `SerpPage(cost_micros=4_000, error="timeout")` and a page label; the user chose this over leaving it `http` at cost 0, or the expected price with `http`. Found by: the brainstorm (the balance fell $0.004 while 0 was recorded). Why: the budget fails closed and the cause is visible. Cost if wrong: $0.004 overcounted for a timeout the provider did not bill. Asked in chat.
- **R3: the two-locale test does not check `skipped_locales`.** Decided: the test checks 4 calls, 4 rows and a 16,000-micro job cost; Section 2 had said it would check `skipped_locales`, but `run_serp_audit`'s summary string is neither stored nor returned by `process_job`. Found by: the controller, writing the proof. Why: a test can only check what the code exposes. Cost if wrong: none. Named in chat when made.
- **R4: commits carry the Opus 5.5 trailer.** Decided: slice 41 commits end with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>", and subagents are dispatched with no `model` parameter (the session is on Opus 5.5). Found by: the controller at the start of the slice. Why: the memory rules. Cost if wrong: none. Named in chat when made.
