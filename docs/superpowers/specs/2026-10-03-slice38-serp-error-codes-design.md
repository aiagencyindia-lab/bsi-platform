# Slice 38 design: the DataForSEO adapter reads error codes from non-2xx answers

## Context

Codebase facts: main `54775b6`, checked 2026-10-03.

The slice 37 live check on dev (docs/findings-slice37.md §2, note of 2026-10-03) recorded: "DataForSEO returns some errors as HTTP statuses (403 observed on searches; 401 on the account call); the adapter maps every non-2xx answer to `http` before reading the body." Three causes (wrong credentials, an unverified account, a paused account) all reached the page as `http` or `provider_40201`. The user asked to "fix the adapter error codes".

Facts read before the approaches:
- packages/core/bsi_core/providers/dataforseo.py:156-157: `if not resp.ok: return SerpPage(error="http")` runs before the body is read. Only a 2xx body reaches `_parse` (lines 91-119), which maps the top-level `status_code`, then `tasks[0].status_code`, through `_code` and `ERRORS = {40100: "auth", 40200: "funds", 40210: "funds", 40202: "rate"}` (line 21); any other code is `provider_<code>`.
- The live check observed: an HTTP 401 whose JSON body carried top-level `40100` (the account call); an HTTP 403 whose JSON body carried top-level `40104` ("Please verify your account before using the API"); an HTTP 200 whose task carried `40201` ("… temporarily paused access …"). The search responses' bodies were JSON (their status codes and messages decoded).
- `_parse` raises when the top-level `status_code` is not an integer (line 96), but the task's `status_code` is passed to `_code` unchecked (line 107), so a list or long string becomes `provider_<anything>`, which the worker stores in `serp_audit.error` (deferred minor "dataforseo.py:58 the provider_<code> error string is unbounded and accepts any type", findings-slice37 §3).
- `_parse`'s docstring says it "raises on an undocumented shape", but since commit 9555650 an item that fails to parse returns `json` with the task's cost (parked under R18, findings-slice37 §3).
- Only two tests depend on the `http` code: tests/unit/test_dataforseo.py `test_an_http_failure_is_http` (a timeout and a 500 with body "oops") and tests/integration/test_serp_audit.py `test_a_partial_failure_keeps_both_rows_and_is_done` (a 500 "oops"). The worker and the API pass the code through; the page labels it from `SERP_ERRORS` in apps/web/src/lib/format.ts and shows an unknown code as is.

Classification: **bounded** — a change to the existing adapter's error handling and two page labels; said in chat as the first line of the first brainstorming reply. The user's process rule asks for a spec even for small changes, so this file exists.

Decisions approved in chat (brainstorming on Opus 5.5, 2026-10-03), each after approaches with trade-offs, the facts above and a recommendation written in a chat message before the question:
1. A non-2xx answer: read the provider code from its body, falling back to `http` (over mapping the HTTP status alone, which leaves a 403 / `40104` as `http`; and over both, which adds a second table for HTML error pages never seen).
2. Scope: the error-code fix plus the two findings on the same lines, the stale `_parse` docstring (R18) and a non-integer task `status_code` (over the error-code fix only; and over all six open adapter findings).
3. Design Sections 1 and 2, the text of each in chat before its approval question.
4. After the spec review of a80f98a: a status counts only if it is a plain integer (not a bool) from 0 to 99999 (R6), over excluding bools only, or leaving the check as first designed.

## Design

### The adapter

packages/core/bsi_core/providers/dataforseo.py, as a diff against main `54775b6` (the exact change the plan applies):

```diff
@@ -18,7 +18,15 @@
 # per country as locales arrive; an unknown country is error "location".
 LOCATIONS = {"IN": "India"}
 OK, NO_RESULTS = 20000, 40102
-ERRORS = {40100: "auth", 40200: "funds", 40210: "funds", 40202: "rate"}
+ERRORS = {
+    40100: "auth",
+    40104: "unverified",
+    40200: "funds",
+    40201: "paused",
+    40202: "rate",
+    40210: "funds",
+}
+MAX_STATUS = 99_999  # documented codes have five digits
 # What an undocumented body can raise while it is decoded or read.
 UNREADABLE = (
     ValueError,
@@ -71,6 +79,14 @@
     return f"provider_{status}"
 
 
+def _status(value: object) -> int | None:
+    """A provider status code, or None: only a plain integer (not a
+    bool) from 0 to MAX_STATUS counts, so a stored error stays short."""
+    if isinstance(value, bool) or not isinstance(value, int):
+        return None
+    return value if 0 <= value <= MAX_STATUS else None
+
+
 def _micros(cost: object) -> int:
     return round(cost * 1_000_000) if isinstance(cost, int | float) else 0
 
@@ -89,12 +105,13 @@
 
 
 def _parse(doc: Any) -> SerpPage:
-    """The page in a decoded response; raises on an undocumented shape."""
+    """The page in a decoded response. Raises on an undocumented shape
+    until the task's cost is read; after that, returns `json` with it."""
     if not isinstance(doc, dict):
         raise ValueError("not an object")
-    top = doc["status_code"]
-    if not isinstance(top, int):
-        raise ValueError("status_code is not a number")
+    top = _status(doc["status_code"])
+    if top is None:
+        raise ValueError("status_code is not a status")
     tasks = doc.get("tasks") or []
     if not tasks:
         error = _code(top)
@@ -104,7 +121,12 @@
     task = tasks[0]
     cost = _micros(task.get("cost"))
     # The top-level status first, then the task's (spec, The adapter).
-    error = _code(top) or _code(task["status_code"])
+    error = _code(top)
+    if error is None:
+        status = _status(task.get("status_code"))
+        if status is None:
+            return SerpPage(cost_micros=cost, error="json")
+        error = _code(status)
     if error is not None:
         return SerpPage(cost_micros=cost, error=error)
     try:
@@ -119,6 +141,19 @@
     return SerpPage(items, cost)
 
 
+def _refused(resp: Response) -> SerpPage:
+    """A non-2xx answer: the provider's error code from its body when it
+    has one; otherwise `http`. `truncated` is not consulted: a cut body
+    fails to decode, which is also `http`."""
+    try:
+        page = _parse(json.loads(resp.body))
+    except UNREADABLE:
+        return SerpPage(error="http")
+    if page.error in (None, "json"):
+        return SerpPage(error="http")
+    return SerpPage(cost_micros=page.cost_micros, error=page.error)
+
+
 def serp(
     query: str,
     country: str,
@@ -154,7 +189,7 @@
         headers={"Authorization": f"Basic {token}"},
     )
     if not resp.ok:
-        return SerpPage(error="http")
+        return _refused(resp)
     if resp.truncated:
         return SerpPage(error="truncated")
     try:
```

- `_status(value)`: only a plain integer (not a bool) from 0 to `MAX_STATUS = 99_999` is a provider status (R6). A top-level status that is not one raises in `_parse`, so `serp()` returns `json` with cost 0, as a non-integer one does today. A task status that is not one returns `json` with the task's cost.
- The top-level code is mapped first; the task's status is read only when the top level is a success (R3). So a top-level error code wins even when the task's status is missing or malformed, as on main.
- `_refused(resp)` for a non-2xx answer: a body whose top-level or task-level code is an error, with a readable cost, gives that code (`auth`, `funds`, `rate`, `unverified`, `paused`, `provider_<n>`) and that cost. Every other non-2xx answer gives `http` and cost 0: a timeout (status 0, empty body), a body that is not JSON, a cut body (`truncated` is not consulted; the cut body fails to decode), a body without a valid status, a body with a success code, an unreadable cost (`_micros` raises), or a task status that is not valid (`_parse` gives `json`, which `_refused` turns into `http`). Items are never taken from a non-2xx answer.
- Unchanged: the order of the checks (credentials, country, the call), the 2xx path for valid statuses, `truncated` for a cut 2xx body, and the never-raises contract. The worker and the API are unchanged.

### The page

apps/web/src/lib/format.ts `SERP_ERRORS` gains:
- `unverified: "the SERP provider account is not verified"`
- `paused: "the SERP provider paused the account; contact its support"`

`http` keeps "the SERP provider returned an error or could not be reached".

### Tests

tests/unit/test_dataforseo.py (no network; the file's fake `Fetch` and `body()`). `ERROR_CODES` gains two rows:

```python
    (40202, "rate"),
    (40104, "unverified"),
    (40201, "paused"),
    (50000, "provider_50000"),
]
```

and these tests are appended after `test_deeply_nested_json_is_json`, the file's last test:

```python
REFUSED = [
    (401, 40100, "auth"),
    (402, 40210, "funds"),
    (403, 40104, "unverified"),
    (429, 40202, "rate"),
    (403, 50301, "provider_50301"),
]


@pytest.mark.parametrize(("http", "status", "code"), REFUSED)
def test_a_refused_answer_is_its_providers_code(http, status, code):
    raw = json.dumps({"status_code": status, "cost": 0, "tasks": None})
    assert _serp(Fetch(Response(http, raw))) == SerpPage([], 0, code)


def test_a_refused_answer_keeps_a_task_code_and_its_cost():
    raw = body(task_status=40210)
    assert _serp(Fetch(Response(402, raw))) == SerpPage([], 4_000, "funds")


@pytest.mark.parametrize(
    "response",
    [
        Response(403, "{}"),
        Response(401, "<html>Unauthorized</html>"),
        Response(403, body()),
        Response(401, body(status=40100)[:30], truncated=True),
        Response(403, body(task_status=[1, 2])),
    ],
)
def test_a_refused_answer_without_a_code_is_http(response):
    assert _serp(Fetch(response)) == SerpPage([], 0, "http")


@pytest.mark.parametrize("status", [[1, 2], True, 100_000, -1])
def test_a_bad_task_status_is_json_and_keeps_the_cost(status):
    raw = body(task_status=status)
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 4_000, "json")


@pytest.mark.parametrize("status", [True, 100_000])
def test_a_bad_top_level_status_is_json(status):
    raw = body(status=status)
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "json")


def test_a_top_level_error_wins_over_a_bad_task_status():
    raw = body(status=40100, task_status=[1, 2])
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 4_000, "auth")


@pytest.mark.parametrize(
    ("status", "code"), [(0, "provider_0"), (99_999, "provider_99999")]
)
def test_the_status_range_ends_are_codes(status, code):
    page = _serp(Fetch(Response(200, body(task_status=status))))
    assert page == SerpPage([], 4_000, code)


def test_a_task_without_a_status_is_json_and_keeps_the_cost():
    doc = json.loads(body())
    del doc["tasks"][0]["status_code"]
    page = _serp(Fetch(Response(200, json.dumps(doc))))
    assert page == SerpPage([], 4_000, "json")
```

- `ERROR_CODES` runs in the existing top-level and task-level tests, so its two new rows add 4 cases; the appended tests add 21 (5 + 1 + 5 + 4 + 2 + 1 + 2 + 1).
- apps/web/src/lib/format.test.ts: one test that `serpError("unverified")` and `serpError("paused")` return the two labels.
- Counts: tests/unit/test_dataforseo.py 27 → 52 (the scratch run below ran 52); backend 1643 → 1668 and web 47 → 48 (*inferred* from the lists). The plan re-collects the baseline.

### Proof

Run on 2026-10-03 with pytest on scratch copies of packages/core/bsi_core outside the repo, the changed test file in its own scratch folder, `PYTHONPATH=<copy>:.`; before each run `bsi_core.providers.dataforseo.__file__` was checked to be the intended copy.

| Code | Result over the 52 tests | Failing |
|---|---|---|
| main (`54775b6`) | `17 failed, 35 passed` | the 4 new `ERROR_CODES` cases; the 5 `REFUSED` cases; `test_a_refused_answer_keeps_a_task_code_and_its_cost`; the 4 bad task statuses; the 2 bad top-level statuses; `test_a_task_without_a_status_is_json_and_keeps_the_cost` |
| patched (the design above) | `52 passed` | none |
| m1: `_refused(resp)` reverted to `SerpPage(error="http")` | `6 failed, 46 passed` | the 5 `REFUSED` cases; the task code and cost case |
| m2: `_refused` returns the parsed page as is | `2 failed, 50 passed` | no-code cases `response2` (a success body on a 403) and `response4` (a bad task status on a 403) |
| m3: the task-status check removed (`_code(task.get("status_code"))`) | `6 failed, 46 passed` | no-code `response4`; the 4 bad task statuses; the task without a status |
| m4: `_refused` drops the cost | `1 failed, 51 passed` | the task code and cost case |
| m5: `_refused` lets `json` through (`if page.error is None`) | `1 failed, 51 passed` | no-code `response4` |
| m6: the task status read before the top-level code | `1 failed, 51 passed` | `test_a_top_level_error_wins_over_a_bad_task_status` |
| m7: `_status` accepts a bool | `2 failed, 50 passed` | the bad task status `True`; the bad top-level status `True` |
| m8: `_status` without the 0–99999 bound | `3 failed, 49 passed` | the bad task statuses `100000` and `-1`; the bad top-level status `100000` |
| m9: `_status` upper bound exclusive (`< MAX_STATUS`) | `1 failed, 51 passed` | the range end `99999` |
| m10: `_status` lower bound exclusive (`0 < value`) | `1 failed, 51 passed` | the range end `0` |
| m11: the task status read with `task["status_code"]` | `1 failed, 51 passed` | the task without a status |

- Three no-code cases (`{}`, an HTML body, a cut body) pass on main and on every mutant: they pin that an unreadable error body gives `http`. `test_a_top_level_error_wins_over_a_bad_task_status` passes on main: it pins the existing order against m6.
- `ruff check`, `ruff format --check` and `mypy --strict` were clean on the scratch adapter and test file.

### No live check

DataForSEO paused the account on 2026-10-03 (findings-slice37 §2). No call is made in this slice; the next successful slice 37 run will exercise this path on real answers.

### Copy

New text is checked against `FORBIDDEN` in tests/unit/test_recommend_copy.py by a grep of the diff.

## Process and docs

- Branch `slice38-serp-error-codes`; spec reviewer; plan by writing-plans; subagent-driven execution with a task review and a final review; at most one fix wave; both gates; the finishing menu; merge on the user's go-ahead.
- After merge: dated notes in docs/findings-slice37.md under the "Disproved" line of §2, the non-integer-code deferred minor and the parked R18 line of §3, pointing here; README rows. No findings file of its own.

## Rulings

- **R1: commits carry the Opus 5.5 trailer.** Decided: slice 38 commits end with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>", the trailer the latest attribution reminder names; a later reminder naming another needs a new ruling. Found by the controller at the start of the slice. Why: the process binds the trailer to the latest session reminder. Cost if wrong: a trailer naming a model that did not write the commit. Named in chat when made.
- **R2: two extra mutants in the proof.** Decided: besides reverting the `_refused` call, the proof runs mutant 2 (the parsed page accepted as is) and mutant 3 (no task-status integer check); the spec records that three cases of the no-code test fail on no mutant tried. Found by the controller, during the prototype. Why: show each new rule is pinned by a test. Cost if wrong: none. Named in chat when made.
- **R3: the top-level code is checked before the task's status.** Decided: `_parse` maps the top-level status first and reads the task's status (with `.get`) only when the top level is a success; one test (`test_a_top_level_error_wins_over_a_bad_task_status`) pins it. Found by the spec review of a80f98a (Important 1: the first design read the task's status first, so a top-level `40100` with a missing or malformed task status became `json`, and on a 401 `http`). Why: a regression against the approved rule "the top-level status first"; fixed, not offered as a choice. Cost if wrong: none. Named in chat when made.
- **R4: two more tests and four more mutants.** Decided: `test_a_refused_answer_keeps_a_task_code_and_its_cost` and the no-code case `Response(403, body(task_status=[1, 2]))`; mutants m4 (cost dropped) and m5 (`json` let through), plus m6 (R3) and m7–m8 (R6), in the proof table. Found by the spec review of a80f98a (Important 2: no test pinned a task-level code or a cost on a non-2xx answer). Why: each stated behaviour has a failing mutant. Cost if wrong: none. Named in chat when made.
- **R5: the spec review's wording points.** Decided: the docstring matches the code (the task status is read with `.get`, so a missing key no longer raises after the cost is read); the unsourced byte sizes are dropped; the design says `truncated` is not consulted on a non-2xx answer. Found by the spec review of a80f98a (Minors 3, 5, 6). Why: accuracy. Cost if wrong: none. Named in chat when made.
- **R6: a status is a plain integer from 0 to 99999.** Decided: `_status` rejects bools and integers outside 0–99999 at both levels, so `provider_<n>` is at most five digits; the user chose this over excluding bools only, or leaving the check as first designed. Found by the spec review of a80f98a (Minor 4: `provider_True` and a 200-digit code were still possible). Why: closes the unbounded-error finding fully. Cost if wrong: a future six-digit provider code would show as `json`; none is documented. Asked in chat.
- **R7: the re-review's four minors were applied.** Decided: the appended test block starts at its anchor (it had begun with a stray tail of the file's last line); `test_the_status_range_ends_are_codes` (0 and 99999) and `test_a_task_without_a_status_is_json_and_keeps_the_cost` were added, with mutants m9–m11 in the proof; the `_refused` bullet names an unreadable cost as `http`. Found by the re-review of e2e9759 (4 Minor). Why: a valid test block, and each stated boundary pinned by a failing mutant. Cost if wrong: none. Named in chat when made.
- **R8: the plan review's five points were applied.** Decided: R7 says "the `_refused` bullet" (one bullet changed); in the plan, the `git status` checks expect the pre-existing untracked `.DS_Store` and `packages/.DS_Store`, Task 2's red step greps the assertion lines (a `tail -6` showed only the summary), Global Constraints define `<workspace>`, and the departures list names the header's executing-plans option. Found by the review of 358781a and 858336e (5 Minor; no Critical or Important). Why: nothing for an implementer to guess, and no claim wider than the commit. Cost if wrong: none. Named in chat when made.
- **R9: no fix wave after the final review.** (Title: writer's own wording; added after merge.) The ledger line, as recorded: "Ruling: R9 — Decided: no fix wave; the post-merge docs add dated notes to findings-slice37.md lines 11 and 96, add "a large cost, now also on non-2xx answers" to the open cost finding, and record the unreadable-tasks case; the both-levels test stays out of scope. Found by: the final review (3 Minor, "Ready to merge? Yes"). Why: none is a code defect; the docs notes keep findings-slice37 accurate. Cost if wrong: a large provider cost stays unbounded until a later slice. How named: named in chat when made."
- **R10: the post-merge docs review's points were applied.** (Title and text: writer's summary of the ledger's R10, added after merge; the ledger line reads "Decided: one fix commit applies both Importants and Minors 1-3; Minor 4's two figures stand (observed by the controller)".) Decided: the findings-slice37 notes name the unreadable-task-list case as `http` and condition the "now `auth`" note on a readable task list; the overflow note says a very large cost overflows both `serp_audit.cost_micros` and `job.cost_micros`, so the failure could not be recorded (it had said the run fails as `error`; R11 corrects what happens to the job); the plan's triage wording is exact; a dated note marks findings-slice37's "a refused call records cost 0" line; the docstring quote is marked as reflowed; the plan's post-merge bullet names the `job.cost_micros` overflow; the README spec row's range becomes R1–R10; the two plan figures the reviewer could not source (the controller gate on `99c8f4f`, the CI timing) stand, since the controller observed both. Found by the review of 677dca2 (2 Important, 4 Minor). Why: no claim wider than its source. Cost if wrong: none. Named in chat when made.
- **R11: a third docs round, by the user's choice.** (Added after merge. Text: the writer's summary, not the ledger's wording; the ledger line was not kept when the slice 38 ledger was deleted. Marked 2026-10-03, after slice 39, PR #76.) Decided: the findings-slice37 overflow note names the real path (a later `claim_job()` fails the job as `stale` after 10 minutes, and the run's spend is never added to `job.cost_micros`, which both budget guards read; `reset_stale_running()` updates only observations); the refused-call cost note requires a readable task list; R10 is marked as the writer's summary and quotes its ledger line, and lists the plan sentence and README range it changed; then one scoped re-review; the user chose this over stopping with the findings in the PR description. Found by the re-review of e4d94cc (2 Important, 2 Minor). Why: no wrong statement about how money is recorded merges as fact. Cost if wrong: one more commit. Asked in chat.
- **R12: stop after the third docs round, by the user's choice.** (Added 2026-10-03, after slice 39. Text: the writer's summary; the slice 38 ledger was deleted, and PR #75's description is the only source. Its copy of the ledger's "After merge" section reads: "re-review: 2 Minor left -> the user chose to stop (R12)".) Decided: no fourth docs round; the re-review's two remaining Minors (R11's text unmarked as the writer's summary; findings-slice37's overflow note should cite R11) were recorded in PR #75's description instead. Found by: the re-review of 4df5f0d (2 Minor). Why and Cost if wrong: not recorded in the surviving source. How named: asked in chat (PR #75: "the user chose to stop here"). Later: slice 39's post-merge docs (PR #77) marked R11 and added the citation (slice 39 R13).

## Out of scope

- Mapping HTTP statuses without a body code (a 401 or 402 HTML page stays `http`).
- Reading `truncated` on a non-2xx answer.
- The other four open adapter findings: a bool or negative cost, a bool or float rank, a top-level `40102` with no tasks, and tests where both levels carry errors.
  - Note (2026-10-03, after slice 39, PR #76): a bool or negative cost is closed in slice 39 (R3); the other three stay open.
- Any worker, API, migration or schema change.
- A live call (the account is paused).
