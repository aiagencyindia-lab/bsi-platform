# Slice 42 design: slice 41's three deferred minors

## Context

Codebase facts: main `afc5126`, checked 2026-10-05.

Slice 41 left three deferred minors (its spec, "Deferred minors"); the user asked to "do this Three deferred minors":
- apps/workers/bsi_workers/worker.py:118-120: the comment above `SERP_JOB_MICROS = 40_000` says "Kept from 5 locales x 2 queries x $0.004". On 2026-10-05 a live call was observed to cost $0.002 (findings-slice37 §2) and an audit is now 1 locale (2 calls, 4,000 micros). `SERP_JOB_MICROS` is `JOB_ESTIMATES["audit_serp"]`, the estimate passed to `budget_fits(..., extra_micros=...)` before a job runs (worker.py:1099-1100; nothing is reserved or spent by it); tests/integration/test_serp_audit.py:77 pins it at 40,000.
- packages/core/bsi_core/crawl.py:228: `_TIMED_OUT = f"timeout: over the {DEADLINE_SECONDS} s deadline"` is built once and returned at three places (lines 293, 304, 341), so a fetch that passed its own `deadline_seconds` (the SERP call's 120 s) reports "30 s". tests/unit/test_http_fetch.py:330 asserts "timeout: over the 30 s deadline" for a default fetch; tests/unit/test_dataforseo.py:170 feeds that text to `serp()` as one of the "stays `http`" inputs. Nothing outside crawl.py imports `_TIMED_OUT`.
- No test drives a real `httpx.ReadTimeout` through `http_fetch` into `serp()`: `serp()` recognises a timeout by `resp.error.startswith("ReadTimeout")`, and `http_fetch` sets the error to `repr(e)` (crawl.py:363); the tests feed a hand-written string. Slice 41's final review checked the real path by hand (`SerpPage([], 2000, "timeout")`).

Classification: **bounded** — one comment, one helper replacing a module constant, and two tests, in existing code; said in chat as the first line of the first brainstorming reply. The user's process rule asks for a spec even for small changes, so this file exists.

Decisions approved in chat (brainstorming on Opus 5.5, 2026-10-05), each after approaches with trade-offs, the facts above and a recommendation written in a chat message before the question:
1. The worker comment is fixed and `SERP_JOB_MICROS` stays 40,000 (R1), over lowering it to 8,000, or to exactly 4,000.
2. The timeout message reports the deadline actually used (R2), over dropping the number, or leaving it.

Design Sections 1 and 2 were approved in chat, the text of each shown before its approval question.

## Design

### `http_fetch`'s timeout message

packages/core/bsi_core/crawl.py, as a diff against main `afc5126`:

```diff
@@ -227,3 +227,7 @@ _PINNED = frozenset({"host", "user-agent", "accept-encoding"})
 _REDIRECTS_REFUSED = "too many redirects"
-_TIMED_OUT = f"timeout: over the {DEADLINE_SECONDS} s deadline"
+
+
+def _timed_out(limit: float) -> Response:
+    """The Response for a fetch past its deadline of `limit` seconds."""
+    return Response(0, "", f"timeout: over the {limit:g} s deadline")
 
@@ -292,3 +296,3 @@ def http_fetch(
                 if left <= 0:
-                    return Response(0, "", _TIMED_OUT)
+                    return _timed_out(limit)
                 wait = min(DNS_TIMEOUT_SECONDS, left)
@@ -303,3 +307,3 @@ def http_fetch(
                 if left <= 0:
-                    return Response(0, "", _TIMED_OUT)
+                    return _timed_out(limit)
                 sent = {
@@ -340,3 +344,3 @@ def http_fetch(
                         if time.monotonic() > deadline:
-                            return Response(0, "", _TIMED_OUT)
+                            return _timed_out(limit)
                         if len(buf) >= cap:
```

`limit` is the deadline `http_fetch` already resolves (`deadline_seconds`, else `DEADLINE_SECONDS` read at call time). With the real default (30) the message is unchanged character for character; a SERP call cut off at its deadline now says "120 s". The message now follows `DEADLINE_SECONDS` at call time, so a test that monkeypatches it (for example to 0.2) would see "0.2 s" where main said "30 s" (no existing test asserts that). `:g` drops the ".0" from a float such as 60.0 or 120.0 (pinned by the new pre-send test, which passes 60.0). All three sites, the two before sending (crawl.py:293, 304) and the one while reading the body (line 341), use the deadline in force. The SERP adapter matches only `ReadTimeout…` errors, so that message stays `http`.

### The worker comment

apps/workers/bsi_workers/worker.py:

```diff
@@ -117,4 +117,4 @@ class Poster(Protocol):
 
-# Kept from 5 locales x 2 queries x $0.004 (a live page plus AI Overview
-# loading); with one locale it overestimates, which fails closed.
+# A SERP audit is 2 calls at the observed $0.002 (2026-10-05), 4,000
+# micros; 40,000 is kept as a 10x margin, which fails closed.
 SERP_JOB_MICROS = 40_000
```

No behaviour change.

### Tests

tests/unit/test_http_fetch.py:

```diff
@@ -332,2 +332,45 @@ def test_the_whole_fetch_has_a_deadline(monkeypatch):
 
+def test_a_fetch_reports_its_own_deadline(monkeypatch):
+    # As the 30 s test above, with a 60 s deadline of this fetch's own.
+    clock = itertools.count(0.0, 1.0)
+    monkeypatch.setattr("bsi_core.crawl.time.monotonic", lambda: next(clock))
+
+    def drip():
+        while True:
+            yield b"x"
+
+    t = server(lambda q: httpx.Response(200, content=drip()))
+    r = http_fetch(
+        "https://nike.com/",
+        "UA",
+        resolve=dns({"nike.com": [PUBLIC]}),
+        transport=t,
+        deadline_seconds=60,
+    )
+    assert (r.status, r.body) == (0, "")
+    assert r.error == "timeout: over the 60 s deadline"
+
+
+@pytest.mark.parametrize(
+    "clock",
+    [
+        [0.0, 61.0],  # out of time before the lookup
+        [0.0, 1.0, 61.0],  # out of time after the lookup, before sending
+    ],
+)
+def test_a_timeout_before_sending_reports_its_own_deadline(monkeypatch, clock):
+    readings = iter(clock + [61.0] * 10)
+    monkeypatch.setattr("bsi_core.crawl.time.monotonic", lambda: next(readings))
+    t = server(ok)
+    r = http_fetch(
+        "https://nike.com/",
+        "UA",
+        resolve=dns({"nike.com": [PUBLIC]}),
+        transport=t,
+        deadline_seconds=60.0,
+    )
+    assert r.error == "timeout: over the 60 s deadline"
+    assert t.seen == []
+
+
 def test_a_transport_error_is_a_response_not_an_exception():
```

tests/unit/test_dataforseo.py:

```diff
@@ -2,5 +2,7 @@ import base64
 import json
+from functools import partial
 
+import httpx
 import pytest
-from bsi_core.crawl import Response
+from bsi_core.crawl import Response, http_fetch
 from bsi_core.providers.dataforseo import (
@@ -161,2 +163,15 @@ def test_a_read_timeout_is_timeout_with_the_expected_cost():
 
+def test_a_real_read_timeout_from_http_fetch_is_timeout():
+    # A real httpx.ReadTimeout through the real http_fetch into serp().
+    def slow(request):
+        raise httpx.ReadTimeout("The read operation timed out", request=request)
+
+    fetch = partial(
+        http_fetch,
+        resolve=lambda host, port: ["93.184.216.34"],
+        transport=httpx.MockTransport(slow),
+    )
+    assert _serp(fetch) == SerpPage([], 2_000, "timeout")
+
+
 @pytest.mark.parametrize(
```

4 new test cases; backend 1704 → 1708 selected (`--collect-only`, 2 deselected; computed). No web change; no schema, migration or API change.

### Proof

Run 2026-10-05 in the scratchpad (copies of `packages/core/bsi_core` and `apps/workers/bsi_workers` imported via `PYTHONPATH`, `bsi_core.crawl.__file__` checked to be the copy; the two test files are the repo's with the changes above):

| Code | Result | Failing tests |
|---|---|---|
| main (`afc5126`) | `3 failed, 142 passed` | `test_a_fetch_reports_its_own_deadline`; the 2 `test_a_timeout_before_sending_reports_its_own_deadline` cases |
| patched | `145 passed` | — |
| m1: the message uses `DEADLINE_SECONDS`, not the deadline used | `3 failed, 142 passed` | the 3 message tests |
| m2: `serp()` does not recognise `ReadTimeout` | `2 failed, 143 passed` | `test_a_read_timeout_is_timeout_with_the_expected_cost`, `test_a_real_read_timeout_from_http_fetch_is_timeout` |
| m3: `http_fetch` reports `str(e)`, not `repr(e)` | `2 failed, 143 passed` | `test_a_transport_error_is_a_response_not_an_exception`, `test_a_real_read_timeout_from_http_fetch_is_timeout` |
| m4: `http_fetch` prefixes its error text (`f"error {e!r}"`) | `1 failed, 144 passed` | `test_a_real_read_timeout_from_http_fetch_is_timeout` |
| m5: the two pre-send sites use `DEADLINE_SECONDS` | `2 failed, 143 passed` | the 2 `test_a_timeout_before_sending_reports_its_own_deadline` cases |
| m6: no `:g` in the message | `2 failed, 143 passed` | the 2 `test_a_timeout_before_sending_reports_its_own_deadline` cases (they pass 60.0) |

`test_a_real_read_timeout_from_http_fetch_is_timeout` passes on main (it pins existing behaviour); m4 is the change only it catches (the transport-error test still finds "ConnectError" in a prefixed message). The worker change is a comment and has no mutant. `ruff check` and `ruff format --check` on the patched modules and both test files: pass; `mypy --strict` on the patched `bsi_core`: no issues.

### Docs

- Code PR: this spec, the plan, two docs/README.md rows, and a dated note in the slice 41 spec under each of the five quoted deferred minors this slice closes (the two `_TIMED_OUT` lines, the repr-shape line, the end-to-end test line, the worker comment line).
- Post-merge docs PR: the plan's "Changes made during execution", rulings from execution, deferred minors.

### Out of scope

- `SERP_JOB_MICROS`'s value (decision 1).
- No live check: nothing here changes a DataForSEO request.

## Rulings

- **R1: the worker comment is fixed; `SERP_JOB_MICROS` stays 40,000.** Decided: the comment states the observed $0.002, 2 calls (4,000 micros) and the 10x margin that fails closed; the user chose this over 8,000 or 4,000. Found by: the brainstorm. Why: the deferred minor is about the comment; the budget check asks for $0.04 of headroom, 10x the observed $0.004 a run costs ($2 is the default daily cap, `daily_budget_usd`, which an org can override). Cost if wrong: an audit can be refused as `budget` when between about $0.004 and $0.04 of headroom remains. Asked in chat.
- **R2: the timeout message reports the deadline used.** Decided: `_timed_out(limit)` builds `f"timeout: over the {limit:g} s deadline"`; the user chose this over dropping the number, or leaving it. Found by: the brainstorm. Why: the SERP path said "30 s" for a 120 s deadline. Cost if wrong: none. Asked in chat.
- **R3: commits carry the Opus 5.5 trailer.** Decided: slice 42 commits end with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>", and subagents are dispatched with no `model` parameter (the session is on Opus 5.5). Found by: the controller at the start of the slice. Why: the memory rules. Cost if wrong: none. Named in chat when made.
- **R4: mutant m4 in the proof.** Decided: the proof adds m4 (a prefixed error text), the one change only the new end-to-end test catches; Section 2 named m1-m3 only. Found by: the controller, writing the proof (m2 and m3 were also caught by older tests). Why: show the new test pins something no other test does. Cost if wrong: none. Named in chat when made.
- **R5: the two pre-send timeout sites are pinned.** Decided: `test_a_timeout_before_sending_reports_its_own_deadline`, parametrized over a clock that runs out before the lookup and one that runs out after it, with `deadline_seconds=60.0` (also pinning `:g`), and mutants m5 and m6 in the proof; 4 new test cases in all. Found by: the spec review of 73ac980 (Important 1: a mutant leaving crawl.py:293 and 304 at "30 s" passed every test; Minor 1: `:g` was unpinned). Why: the spec claims all three sites report the deadline in force. Cost if wrong: none. Named in chat when made.
- **R6: the spec review's wording points.** Decided: the message is said to follow `DEADLINE_SECONDS` at call time; test_dataforseo.py:170 "feeds" the old text rather than pinning it; R1's cost is the headroom the budget check asks for, not a reservation, with $2 named as the default cap; the count names selected tests; the section-approval line is no longer a numbered decision. Found by: the spec review of 73ac980 (Minors 2-6). Why: no claim wider than its source. Cost if wrong: none. Named in chat when made.
- **R7: the plan review's wording points.** (Added with the plan.) Decided: the slice 41 notes say "addressed by slice 42" (commit SHAs come after merge); Task 1's confirming grep notes its expected exit 1; departure 1 says "three occurrences of the same text"; the test line reference is 157-159; the commit prefix of Task 2 is left (departure 4). Found by: the plan review of e5fcd99 (Minors 1-5; "Ready to execute? With fixes"). Why: no claim ahead of the code, and every expected output as the implementer sees it. Cost if wrong: none. Named in chat when made.
- **R8: no fix wave after the final review.** (Added after merge.) The ledger line, as recorded: "Ruling: R8 — Decided: no fix wave after the final review; the README-row minor is closed by the post-merge docs PR filling the plan's execution section; the four task minors stay deferred. Found by: the final review ("Ready to merge? Yes", 1 Minor). Why: none is a code defect. Cost if wrong: none. How named: named in chat when made."
- **R9: each slice 41 note names the commit that fixed it.** (Added after merge.) The ledger line, as recorded: "Ruling: R9 — Decided: each of the five slice 41 lines gets its own note naming the one commit that fixed it (b90397e for the two _TIMED_OUT lines; 6c03876 for the repr-shape, end-to-end-test and worker-comment lines); one scoped re-review. Found by: the review of 964255e. Why: a claim the controller wrote wider than its source; fixed, not offered as a choice. Cost if wrong: none. How named: named in chat when made."

## Deferred minors

Quoted verbatim from the ledger (deleted after this slice's docs PR merges):

- "Task 1: minor (deferred): test_http_fetch.py the two pre-send cases are told apart only by the clock sequence; no assertion on whether the lookup ran, so a future monotonic() read in the lookup path could make clock1 test the first site"
- "Task 1: minor (deferred): crawl.py:232 :g prints scientific notation for very large deadlines (e.g. 1e+06 s); current deadlines are 30 and 120"
- "Task 2: minor (deferred): tests/unit/test_dataforseo.py:166 the helper is named slow though it raises at once (spec-verbatim)"
- "Task 2: minor (deferred): the worker comment was edited before Step 2 instead of after Step 3 (disclosed; no effect)"
- "Final: minor (deferred): docs/README.md's new plan row mentions "the changes made during execution" while the plan's section is still "(Filled in after execution.)"; filled by the post-merge docs PR"
  - Note (2026-10-05, after PR #84): closed by this docs PR, which fills the plan's execution section.
