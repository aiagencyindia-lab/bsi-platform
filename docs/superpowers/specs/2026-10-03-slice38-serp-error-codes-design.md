# Slice 38 design: the DataForSEO adapter reads error codes from non-2xx answers

## Context

Codebase facts: main `54775b6`, checked 2026-10-03.

The slice 37 live check on dev (docs/findings-slice37.md §2, note of 2026-10-03) recorded: "DataForSEO returns some errors as HTTP statuses (403 observed on searches; 401 on the account call); the adapter maps every non-2xx answer to `http` before reading the body." Three causes (wrong credentials, an unverified account, a paused account) all reached the page as `http` or `provider_40201`. The user asked to "fix the adapter error codes".

Facts read before the approaches:
- packages/core/bsi_core/providers/dataforseo.py:156-157: `if not resp.ok: return SerpPage(error="http")` runs before the body is read. Only a 2xx body reaches `_parse` (lines 91-119), which maps the top-level `status_code`, then `tasks[0].status_code`, through `_code` and `ERRORS = {40100: "auth", 40200: "funds", 40210: "funds", 40202: "rate"}` (line 21); any other code is `provider_<code>`.
- The live check observed: an HTTP 401 whose JSON body carried top-level `40100` (the account call); an HTTP 403 whose JSON body carried top-level `40104` ("Please verify your account before using the API"); an HTTP 200 whose task carried `40201` ("… temporarily paused access …"). The search responses' bodies were JSON (315 and 266 bytes).
- `_parse` raises when the top-level `status_code` is not an integer (line 96), but the task's `status_code` is passed to `_code` unchecked (line 107), so a list or long string becomes `provider_<anything>`, which the worker stores in `serp_audit.error` (deferred minor "dataforseo.py:58 the provider_<code> error string is unbounded and accepts any type", findings-slice37 §3).
- `_parse`'s docstring says it "raises on an undocumented shape", but since commit 9555650 an item that fails to parse returns `json` with the task's cost (parked under R18, findings-slice37 §3).
- Only two tests depend on the `http` code: tests/unit/test_dataforseo.py `test_an_http_failure_is_http` (a timeout and a 500 with body "oops") and tests/integration/test_serp_audit.py `test_a_partial_failure_keeps_both_rows_and_is_done` (a 500 "oops"). The worker and the API pass the code through; the page labels it from `SERP_ERRORS` in apps/web/src/lib/format.ts and shows an unknown code as is.

Classification: **bounded** — a change to the existing adapter's error handling and two page labels; said in chat as the first line of the first brainstorming reply. The user's process rule asks for a spec even for small changes, so this file exists.

Decisions approved in chat (brainstorming on Opus 5.5, 2026-10-03), each after approaches with trade-offs, the facts above and a recommendation written in a chat message before the question:
1. A non-2xx answer: read the provider code from its body, falling back to `http` (over mapping the HTTP status alone, which leaves a 403 / `40104` as `http`; and over both, which adds a second table for HTML error pages never seen).
2. Scope: the error-code fix plus the two findings on the same lines, the stale `_parse` docstring (R18) and a non-integer task `status_code` (over the error-code fix only; and over all six open adapter findings).
3. Design Sections 1 and 2, the text of each in chat before its approval question.

## Design

### The adapter

packages/core/bsi_core/providers/dataforseo.py:

```python
ERRORS = {
    40100: "auth",
    40104: "unverified",
    40200: "funds",
    40201: "paused",
    40202: "rate",
    40210: "funds",
}
```

In `_parse`, the docstring and the task status:

```python
def _parse(doc: Any) -> SerpPage:
    """The page in a decoded response. Raises on an undocumented shape
    until the task's cost is read; after that, returns `json` with it."""
    ...
    task = tasks[0]
    cost = _micros(task.get("cost"))
    status = task["status_code"]
    if not isinstance(status, int):
        return SerpPage(cost_micros=cost, error="json")
    # The top-level status first, then the task's (spec, The adapter).
    error = _code(top) or _code(status)
    ...
```

A new function before `serp`, and its use:

```python
def _refused(resp: Response) -> SerpPage:
    """A non-2xx answer: the provider's error code from its body when it
    has one; otherwise `http` (a timeout, a bare or cut error page)."""
    try:
        page = _parse(json.loads(resp.body))
    except UNREADABLE:
        return SerpPage(error="http")
    if page.error in (None, "json"):
        return SerpPage(error="http")
    return SerpPage(cost_micros=page.cost_micros, error=page.error)
```

```python
    if not resp.ok:
        return _refused(resp)
```

- A non-2xx answer whose body carries a provider error code (top level or task level) gets that code (`auth`, `funds`, `rate`, `unverified`, `paused`, `provider_<n>`) and any cost the body reports.
- A non-2xx answer with no readable code gets `http` and cost 0: a timeout (status 0, empty body), a body that is not JSON, a cut body, a body without an integer code, or a body with a success code. Items are never taken from a non-2xx answer.
- Unchanged: the order of the checks (credentials, country, the call), the 2xx path, `truncated` for a cut 2xx body, and the never-raises contract. The worker and the API are unchanged.

### The page

apps/web/src/lib/format.ts `SERP_ERRORS` gains:
- `unverified: "the SERP provider account is not verified"`
- `paused: "the SERP provider paused the account; contact its support"`

`http` keeps "the SERP provider returned an error or could not be reached".

### Tests

tests/unit/test_dataforseo.py (no network; the file's fake `Fetch` and `body()`):

```python
ERROR_CODES = [
    (40100, "auth"),
    (40200, "funds"),
    (40210, "funds"),
    (40202, "rate"),
    (40104, "unverified"),
    (40201, "paused"),
    (50000, "provider_50000"),
]
```

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


@pytest.mark.parametrize(
    "response",
    [
        Response(403, "{}"),
        Response(401, "<html>Unauthorized</html>"),
        Response(403, body()),
        Response(401, body(status=40100)[:30], truncated=True),
    ],
)
def test_a_refused_answer_without_a_code_is_http(response):
    assert _serp(Fetch(response)) == SerpPage([], 0, "http")


def test_a_non_integer_task_status_is_json_and_keeps_the_cost():
    raw = body(task_status=[1, 2])
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 4_000, "json")
```

- `ERROR_CODES` runs in the existing top-level and task-level tests, so its two new rows add 4 cases.
- apps/web/src/lib/format.test.ts: one test that `serpError("unverified")` and `serpError("paused")` return the two labels.
- Counts (*inferred* from the lists): tests/unit/test_dataforseo.py 27 → 41; backend 1643 → 1657; web 47 → 48. The plan re-collects the baseline.

### Proof

Run on 2026-10-03 with pytest on a scratch copy of packages/core/bsi_core outside the repo, the changed test file in its own scratch folder, `PYTHONPATH=<copy>:.`; each run's `bsi_core.providers.dataforseo.__file__` printed the intended copy first.

| Code | Result over the 41 tests | Failing |
|---|---|---|
| main (`54775b6`) | `10 failed, 31 passed` | the 4 new `ERROR_CODES` cases, the 5 `REFUSED` cases, the non-integer case |
| patched (the design above) | `41 passed` | none |
| mutant 1: `_refused(resp)` reverted to `SerpPage(error="http")` | `5 failed, 36 passed` | the 5 `REFUSED` cases |
| mutant 2: `_refused` returns the parsed page as is | `1 failed, 40 passed` | `test_a_refused_answer_without_a_code_is_http[response2]` (a success body on a 403) |
| mutant 3: the task-status integer check removed | `1 failed, 40 passed` | the non-integer case |

- The other three cases of `test_a_refused_answer_without_a_code_is_http` (`{}`, an HTML body, a cut body) pass on main and on every mutant: they pin that an unreadable error body gives `http`, and no mutant tried breaks that.
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

## Out of scope

- Mapping HTTP statuses without a body code (a 401 or 402 HTML page stays `http`).
- The other four open adapter findings: a bool or negative cost, a bool or float rank, a top-level `40102` with no tasks, and tests where both levels carry errors.
- Any worker, API, migration or schema change.
- A live call (the account is paused).
