# Slice 40 design: an error answer keeps its provider code when its cost is bad

## Context

Codebase facts: main `ae34ae6`, checked 2026-10-03.

Slice 39 made `_micros` raise `ValueError` for a bad cost (a bool, a negative number, a cost above `MAX_COST_USD`, infinity or NaN). Its spec accepted one consequence (Behaviour bullet 4; deferred minor "a task with a provider error code and a bad cost loses the code (e.g. paused with cost 5 becomes json); named and accepted in the spec (Behaviour bullet 4)"). The user asked to "fix the provider error code lost on a bad cost".

Facts read before the approaches:
- packages/core/bsi_core/providers/dataforseo.py `_parse` (lines 118-152 on main): on the no-task path the cost is read inside the return, `SerpPage(cost_micros=_micros(doc.get("cost")), error=error)` (line 131); on the task path `cost = _micros(task.get("cost"))` (line 133) runs before the top-level and task status codes are read. A bad cost therefore makes `_parse` raise before the code is used.
- `serp()` turns that raise into `json` with cost 0 on a 2xx answer; `_refused` turns it into `http` with cost 0 on a non-2xx answer. So a `paused`, `auth`, `funds`, `unverified`, `rate` or `provider_<n>` answer with a bad cost reaches the page as a generic error.
- Two tests pin the current behaviour: `test_a_refused_answer_with_a_cost_out_of_range_is_http` (402, task `40210`, cost 5 → `http`) and `test_a_top_level_error_with_a_cost_out_of_range_is_json` (top-level `40100`, no tasks, cost 5 → `json`). `test_a_bad_cost_is_json` (`BAD_COSTS` on a success) pins the success case.
- `_micros` is called only in `_parse`. The worker, API and web app read `SerpPage.error` and `cost_micros` as given; every code above except `provider_<n>` has a page label in apps/web/src/lib/format.ts `SERP_ERRORS`, and `serpError` shows `provider_<n>` as is.

Classification: **bounded** — two functions' ordering in the existing adapter and their unit tests; said in chat as the first line of the first brainstorming reply. The user's process rule asks for a spec even for small changes, so this file exists.

Decisions approved in chat (brainstorming on Opus 5.5, 2026-10-03), each after approaches with trade-offs, the facts above and a recommendation written in a chat message before the question:
1. An answer with a provider error code and a bad cost keeps the code and records cost 0 (R1), over recording the cap ($1), or adding a marker code or field.
2. Design Sections 1 and 2, the text of each in chat before its approval question.
3. After the spec review of 0f834a6: the `_parse` docstring also says "An unreadable item returns `json` with the cost." (R7), over keeping the approved text.

## Design

### The adapter

packages/core/bsi_core/providers/dataforseo.py, as a diff against main `ae34ae6` (the exact change the plan applies; formatted by `ruff format`):

```diff
@@ -103,4 +103,13 @@ def _micros(cost: object) -> int:
 
 
+def _error_micros(cost: object) -> int:
+    """The cost of an answer that carries an error code: a bad cost is 0,
+    so the code is kept."""
+    try:
+        return _micros(cost)
+    except ValueError:
+        return 0
+
+
 def _item(raw: Mapping[str, Any]) -> SerpItem:
     rank = raw.get("rank_absolute")
@@ -117,6 +126,7 @@ def _item(raw: Mapping[str, Any]) -> SerpItem:
 
 def _parse(doc: Any) -> SerpPage:
-    """The page in a decoded response. Raises on an undocumented shape
-    until the task's cost is read; after that, returns `json` with it."""
+    """The page in a decoded response. Raises on an undocumented shape,
+    or on a success whose cost is bad. An error answer keeps its code; a
+    bad cost there is 0. An unreadable item returns `json` with the cost."""
     if not isinstance(doc, dict):
         raise ValueError("not an object")
@@ -129,16 +139,16 @@ def _parse(doc: Any) -> SerpPage:
         if error is None:
             raise ValueError("no task")
-        return SerpPage(cost_micros=_micros(doc.get("cost")), error=error)
+        return SerpPage(cost_micros=_error_micros(doc.get("cost")), error=error)
     task = tasks[0]
-    cost = _micros(task.get("cost"))
     # The top-level status first, then the task's (spec, The adapter).
     error = _code(top)
     if error is None:
         status = _status(task.get("status_code"))
-        if status is None:
-            return SerpPage(cost_micros=cost, error="json")
-        error = _code(status)
+        error = "json" if status is None else _code(status)
     if error is not None:
-        return SerpPage(cost_micros=cost, error=error)
+        return SerpPage(
+            cost_micros=_error_micros(task.get("cost")), error=error
+        )
+    cost = _micros(task.get("cost"))  # a bad cost on a success raises: json
     try:
         items = [
```

Behaviour:
- An answer with a provider error code and a bad cost keeps the code and records cost 0: a top-level code with no tasks, a top-level code with tasks, a task-level code, and a non-2xx answer through `_refused` (which is unchanged and passes any code other than `json` through). For example a 402 with task `40210` and cost 5 is `funds`, cost 0 (it was `http`).
- A success with a bad cost is still `json` with cost 0 and no items (slice 39 R1 unchanged).
- A task status that is not a status is still `json`; a readable cost is kept with it, as before, and a bad cost there is 0, as before. On a non-2xx answer `_refused` still turns it into `http` with cost 0.
- A readable cost is recorded exactly as before on every path; on a task error it is the task's cost, not the top-level one. No worker, schema, API or web change; no migration.

### Tests

In tests/unit/test_dataforseo.py, two tests change name and expected result:

```python
def test_a_refused_answer_with_a_bad_cost_keeps_its_code():
    raw = body(cost=5, task_status=40210)
    assert _serp(Fetch(Response(402, raw))) == SerpPage([], 0, "funds")


def test_a_top_level_error_with_a_bad_cost_keeps_its_code():
    raw = json.dumps({"status_code": 40100, "cost": 5, "tasks": None})
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "auth")
```

(they were `test_a_refused_answer_with_a_cost_out_of_range_is_http`, expecting `http`, and `test_a_top_level_error_with_a_cost_out_of_range_is_json`, expecting `json`), and seven tests follow the second one:

```python
@pytest.mark.parametrize("cost", BAD_COSTS)
def test_a_task_error_with_a_bad_cost_keeps_its_code(cost):
    raw = body(cost=cost, task_status=40201)
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "paused")


def test_a_top_level_error_with_tasks_and_a_bad_cost_keeps_its_code():
    raw = body(cost=5, status=40100)
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "auth")


def test_a_bad_task_status_with_a_bad_cost_is_json():
    raw = body(cost=5, task_status=[1, 2])
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "json")


def test_a_top_level_error_keeps_a_readable_cost():
    raw = json.dumps({"status_code": 40100, "cost": 0.004, "tasks": None})
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 4_000, "auth")


def test_a_task_error_keeps_the_tasks_cost():
    doc = json.loads(body(task_status=40201))
    doc["cost"] = 0
    page = _serp(Fetch(Response(200, json.dumps(doc))))
    assert page == SerpPage([], 4_000, "paused")


def test_a_task_error_with_an_infinite_cost_keeps_its_code():
    raw = body(cost=1e400, task_status=40201)
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "paused")


def test_a_refused_top_level_error_with_a_bad_cost_keeps_its_code():
    raw = json.dumps({"status_code": 40100, "cost": 5, "tasks": None})
    assert _serp(Fetch(Response(401, raw))) == SerpPage([], 0, "auth")
```

12 new cases; the file goes from 65 to 77. `test_a_bad_cost_is_json`, `test_an_infinite_cost_is_json` and every readable-cost test are unchanged.

### Proof

Run 2026-10-03 in the scratchpad (copies of `packages/core/bsi_core` imported via `PYTHONPATH`, each run's `bsi_core.providers.dataforseo.__file__` checked to be the copy; the test file is the repo's with the changes above):

| Code | Result | Failing tests |
|---|---|---|
| main (`ae34ae6`) | `11 failed, 66 passed` | the two renamed tests; the 6 `test_a_task_error_with_a_bad_cost_keeps_its_code` cases; `test_a_top_level_error_with_tasks_and_a_bad_cost_keeps_its_code`; `test_a_task_error_with_an_infinite_cost_keeps_its_code`; `test_a_refused_top_level_error_with_a_bad_cost_keeps_its_code` |
| patched | `77 passed` | — |
| m1: the task error path uses `_micros` | `9 failed, 68 passed` | the refused-answer test; the 6 task-error cases; the top-level-with-tasks test; the infinite-cost test |
| m2: the no-task path uses `_micros` | `2 failed, 75 passed` | `test_a_top_level_error_with_a_bad_cost_keeps_its_code`; `test_a_refused_top_level_error_with_a_bad_cost_keeps_its_code` |
| m3: `_error_micros` returns 1,000,000 instead of 0 | `12 failed, 65 passed` | the 11 tests that fail on main, plus `test_a_bad_task_status_with_a_bad_cost_is_json` |
| m4: the success path uses `_error_micros` | `7 failed, 70 passed` | the 6 `test_a_bad_cost_is_json` cases; `test_an_infinite_cost_is_json` |
| m5: `_micros(task.get("cost"))` read before the code | `9 failed, 68 passed` | as m1 |
| m6: the no-task error path records 0 | `1 failed, 76 passed` | `test_a_top_level_error_keeps_a_readable_cost` |
| m7: the task error path reads the top-level cost | `1 failed, 76 passed` | `test_a_task_error_keeps_the_tasks_cost` |
| m8: `_error_micros` lets an infinite cost raise | `1 failed, 76 passed` | `test_a_task_error_with_an_infinite_cost_keeps_its_code` |

`test_a_bad_task_status_with_a_bad_cost_is_json`, `test_a_top_level_error_keeps_a_readable_cost` and `test_a_task_error_keeps_the_tasks_cost` pass on main (they pin existing behaviour against m3, m6 and m7). On the bad-status path the code is `json` whichever helper is used, so only m3 changes its outcome. `ruff check` and `ruff format --check` on the patched module and the test file: pass; `mypy --strict` on the patched module: no issues. The web code is unchanged.

### Docs

- Code PR: this spec, the plan, two docs/README.md rows (spec, plan), and a dated note in the slice 39 spec under its Behaviour bullet 4 and under the deferred minor that quotes it, saying both are closed by slice 40.
- Post-merge docs PR: the plan's "Changes made during execution", rulings from execution, deferred minors.

### Out of scope

- No live check: nothing here can be seen without a paid DataForSEO call, and the account is paused.
- A bad cost the provider really charged on an error answer records 0 (decision 1); the three error answers printed at the slice 37 live check reported cost 0 (findings-slice37 line 66).
- The other open adapter findings: a bool or float rank, a top-level `40102` with no tasks, tests where both levels carry errors.

## Rulings

- **R1: an error answer keeps its code with cost 0 when its cost is bad.** Decided: `_error_micros` returns 0 for a bad cost on any answer that carries an error code; the user chose this over recording the cap, or a marker code or field. Found by: the brainstorm. Why: the operator sees the real reason; slice 39's cost rule still keeps a bad cost out of the budget columns. Cost if wrong: a cost the provider really charged on an error answer is not counted. Asked in chat (named "R16" in chat by mistake; see R3).
- **R2: the no-task return stays on one line.** Decided: the spec uses `ruff format`'s output; Section 1 had said that line ran over 80 characters and would be wrapped, but it is exactly 80 and the formatter keeps it on one line. Found by: the controller's scratch run (`ruff format --check` asked to join the wrapped line). Why: the plan's code must be what the formatter leaves. Cost if wrong: none; no behaviour change. Named in chat when made.
- **R3: the first ruling is R1, not R16.** Decided: the user's choice in the brainstorm is this slice's R1; in chat it was called "R16", continuing slice 39's numbering by mistake. Found by: the controller, writing this spec. Why: each slice numbers its own rulings. Cost if wrong: none. Named in chat when made.
- **R4: commits carry the Opus 5.5 trailer.** Decided: slice 40 commits end with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" (the latest attribution reminder), and subagents are dispatched with no `model` parameter (the session is on Opus 5.5). Found by: the controller at the start of the slice. Why: the memory rules bind the trailer to the latest reminder and omit the param on Opus. Cost if wrong: none. Named in chat when made.
- **R5: four more tests pin stated behaviour.** Decided: `test_a_top_level_error_keeps_a_readable_cost`, `test_a_task_error_keeps_the_tasks_cost`, `test_a_task_error_with_an_infinite_cost_keeps_its_code` and `test_a_refused_top_level_error_with_a_bad_cost_keeps_its_code`, with mutants m6–m8 in the proof; the file goes to 77. Found by: the spec review of 0f834a6 (Important 1: a no-task error recording 0 passed all 73 tests; Minors 1, 2 and 6: the task path reading the top-level cost, infinity on the error path, and a non-2xx top-level code with a bad cost were unpinned). Why: each stated behaviour has a failing mutant. Cost if wrong: none. Named in chat when made.
- **R6: the spec review's accuracy points.** Decided: `provider_<n>` has no page label and is shown as is; the out-of-scope note cites the costs printed at the slice 37 live check instead of "documented as free"; the README file is named. Found by: the spec review of 0f834a6 (Minors 3, 4, 6). Why: no claim wider than its source. Cost if wrong: none. Named in chat when made.
- **R7: the docstring names the unreadable-item case.** Decided: "An unreadable item returns `json` with the cost." is appended to the `_parse` docstring; the user chose this over keeping the approved Section 1 text. Found by: the spec review of 0f834a6 (Minor 5). Why: the docstring covers every outcome of `_parse`, as the old one did. Cost if wrong: none. Asked in chat.
- **R8: the re-review's one wording point was applied, with no further re-review.** Decided: the out-of-scope note says "the three error answers printed at the slice 37 live check", since attempts 1-2's responses were not printed. Found by: the re-review of 1ff86aa (optional; "Ready for the user's review? Yes"). Why: no claim wider than its source. Cost if wrong: none; wording only. Named in chat when made.
