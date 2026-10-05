# Slice 42 design: slice 41's three deferred minors

## Context

Codebase facts: main `afc5126`, checked 2026-10-05.

Slice 41 left three deferred minors (its spec, "Deferred minors"); the user asked to "do this Three deferred minors":
- apps/workers/bsi_workers/worker.py:118-120: the comment above `SERP_JOB_MICROS = 40_000` says "Kept from 5 locales x 2 queries x $0.004". On 2026-10-05 a live call was observed to cost $0.002 (findings-slice37 §2) and an audit is now 1 locale (2 calls, 4,000 micros). `SERP_JOB_MICROS` is `JOB_ESTIMATES["audit_serp"]`, the budget estimate checked before a job runs; tests/integration/test_serp_audit.py:77 pins it at 40,000.
- packages/core/bsi_core/crawl.py:228: `_TIMED_OUT = f"timeout: over the {DEADLINE_SECONDS} s deadline"` is built once and returned at three places (lines 293, 304, 341), so a fetch that passed its own `deadline_seconds` (the SERP call's 120 s) reports "30 s". tests/unit/test_http_fetch.py:330 and tests/unit/test_dataforseo.py:170 pin "timeout: over the 30 s deadline". Nothing outside crawl.py imports `_TIMED_OUT`.
- No test drives a real `httpx.ReadTimeout` through `http_fetch` into `serp()`: `serp()` recognises a timeout by `resp.error.startswith("ReadTimeout")`, and `http_fetch` sets the error to `repr(e)` (crawl.py:363); the tests feed a hand-written string. Slice 41's final review checked the real path by hand (`SerpPage([], 2000, "timeout")`).

Classification: **bounded** — one comment, one helper replacing a module constant, and two tests, in existing code; said in chat as the first line of the first brainstorming reply. The user's process rule asks for a spec even for small changes, so this file exists.

Decisions approved in chat (brainstorming on Opus 5.5, 2026-10-05), each after approaches with trade-offs, the facts above and a recommendation written in a chat message before the question:
1. The worker comment is fixed and `SERP_JOB_MICROS` stays 40,000 (R1), over lowering it to 8,000, or to exactly 4,000.
2. The timeout message reports the deadline actually used (R2), over dropping the number, or leaving it.
3. Design Sections 1 and 2, the text of each in chat before its approval question.

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

`limit` is the deadline `http_fetch` already resolves (`deadline_seconds`, else `DEADLINE_SECONDS` read at call time). `:g` prints 30 as "30", so the default message is unchanged character for character; a SERP call cut off at its deadline now says "120 s". The SERP adapter matches only `ReadTimeout…` errors, so that message stays `http`.

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
@@ -332,2 +332,23 @@ def test_the_whole_fetch_has_a_deadline(monkeypatch):
 
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

2 new tests; backend 1704 → 1706 (computed). No web change; no schema, migration or API change.

### Proof

Run 2026-10-05 in the scratchpad (copies of `packages/core/bsi_core` and `apps/workers/bsi_workers` imported via `PYTHONPATH`, `bsi_core.crawl.__file__` checked to be the copy; the two test files are the repo's with the changes above):

| Code | Result | Failing tests |
|---|---|---|
| main (`afc5126`) | `1 failed, 142 passed` | `test_a_fetch_reports_its_own_deadline` |
| patched | `143 passed` | — |
| m1: the message uses `DEADLINE_SECONDS`, not the deadline used | `1 failed, 142 passed` | `test_a_fetch_reports_its_own_deadline` |
| m2: `serp()` does not recognise `ReadTimeout` | `2 failed, 141 passed` | `test_a_read_timeout_is_timeout_with_the_expected_cost`, `test_a_real_read_timeout_from_http_fetch_is_timeout` |
| m3: `http_fetch` reports `str(e)`, not `repr(e)` | `2 failed, 141 passed` | `test_a_transport_error_is_a_response_not_an_exception`, `test_a_real_read_timeout_from_http_fetch_is_timeout` |
| m4: `http_fetch` prefixes its error text (`f"error {e!r}"`) | `1 failed, 142 passed` | `test_a_real_read_timeout_from_http_fetch_is_timeout` |

`test_a_real_read_timeout_from_http_fetch_is_timeout` passes on main (it pins existing behaviour); m4 is the change only it catches (the transport-error test still finds "ConnectError" in a prefixed message). The worker change is a comment and has no mutant. `ruff check` and `ruff format --check` on the patched modules and both test files: pass; `mypy --strict` on the patched `bsi_core`: no issues.

### Docs

- Code PR: this spec, the plan, two docs/README.md rows, and a dated note in the slice 41 spec under each of the five quoted deferred minors this slice closes (the two `_TIMED_OUT` lines, the repr-shape line, the end-to-end test line, the worker comment line).
- Post-merge docs PR: the plan's "Changes made during execution", rulings from execution, deferred minors.

### Out of scope

- `SERP_JOB_MICROS`'s value (decision 1).
- No live check: nothing here changes a DataForSEO request.

## Rulings

- **R1: the worker comment is fixed; `SERP_JOB_MICROS` stays 40,000.** Decided: the comment states the observed $0.002, 2 calls (4,000 micros) and the 10x margin that fails closed; the user chose this over 8,000 or 4,000. Found by: the brainstorm. Why: the deferred minor is about the comment; the margin costs about $0.04 of a $2 daily budget per audit. Cost if wrong: a SERP audit reserves 10x its cost in the budget check. Asked in chat.
- **R2: the timeout message reports the deadline used.** Decided: `_timed_out(limit)` builds `f"timeout: over the {limit:g} s deadline"`; the user chose this over dropping the number, or leaving it. Found by: the brainstorm. Why: the SERP path said "30 s" for a 120 s deadline. Cost if wrong: none. Asked in chat.
- **R3: commits carry the Opus 5.5 trailer.** Decided: slice 42 commits end with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>", and subagents are dispatched with no `model` parameter (the session is on Opus 5.5). Found by: the controller at the start of the slice. Why: the memory rules. Cost if wrong: none. Named in chat when made.
- **R4: mutant m4 in the proof.** Decided: the proof adds m4 (a prefixed error text), the one change only the new end-to-end test catches; Section 2 named m1-m3 only. Found by: the controller, writing the proof (m2 and m3 were also caught by older tests). Why: show the new test pins something no other test does. Cost if wrong: none. Named in chat when made.
