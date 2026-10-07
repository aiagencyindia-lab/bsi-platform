# Slice 49 design: api() refuses a path fetch would not send as written

## Context

Codebase facts: main `c45a729`, checked 2026-10-07.

The slice 48 final review deferred a minor: a server action puts `brand_id` from a hidden form field straight into the API path (findings-slice48 §3, R6). The same holds for every value the web app interpolates into an API path (about 40 call sites): server actions read `brand_id`, `task_id`, the report `type`, a report `run` and a recommendation id from form fields; Server Component pages use route params (`id`, `oid`). `apps/web/src/lib/api.ts` builds `${API_URL}/v1${path}` and calls `fetch`; `publicApi()` does the same with no key. `fetch` normalizes the URL first: a `.` or `..` segment (also spelled `%2e`, and with `\` read as `/`) is collapsed, so a value such as `..` makes the request go to a different `/v1` route.

`encodeURIComponent` alone would not stop this: it leaves `.` unescaped, so a value of exactly `..` still walks up a segment.

Who can change these values: only the signed-in operator, whose request carries their own key and the same HTTP method; Next checks the Origin of server actions. So the change keeps requests on the intended route; it is not a privilege fix.

The two Route Handlers already validate their parameter before `fetch` (`products/export.csv`: a UUID regex; `r/[token]/pdf`: a token regex), and the public report page passes its token through `encodeURIComponent`.

Classification: **bounded** (one shared function, no API change), said as the first line of the first brainstorming reply with the session model (Opus 5.5). The user's process asks for a spec and plan even for small changes, so the full process is followed.

Decisions approved in chat (2026-10-07), each after approaches with trade-offs and a recommendation written in a chat message:
1. One guard in `api()` (and `publicApi()`); over validating each id at every action site and page, or `encodeURIComponent` at each site.
2. On refusal, `notFound()` with a log line; over throwing an error.

Design Section 1 (the round-trip rule, the refusal, both functions, the `?` gap) and Section 2 (`sendAsWritten`, the 9 tests) were each shown in chat and approved.

## Design

`sendAsWritten(path)` parses `path` as a URL path against a dummy base and requires the parsed path plus query to equal `path` exactly. Otherwise it logs `console.error("API path refused", path)` and calls `notFound()`. `api()` calls it first, before reading the cookie; `publicApi()` calls it first. Refused: `.` and `..` segments in any spelling, `\`, a `#`, anything the URL parser would percent-encode (a space, a non-ASCII letter), and a trailing bare `?`. Passed unchanged: every path the app builds today (UUIDs, report type slugs, `URLSearchParams` query strings, none of them a bare `?`).

Not caught: a `?` inside a value moves the rest of the path into the query string; for example `addDomain` with `brand_id = "B?"` posts to `/v1/brands/B` instead of `/v1/brands/B/domains`, a shorter route of the same brand with the same key and method, which the API answers with its own status.

Unchanged: the call sites, the Route Handlers and the API.

As a diff against main `c45a729` (generated from the proof below):

```diff
diff --git a/apps/web/src/lib/api.test.ts b/apps/web/src/lib/api.test.ts
--- a/apps/web/src/lib/api.test.ts
+++ b/apps/web/src/lib/api.test.ts
@@ -9,7 +9,8 @@ vi.mock("next/navigation", () => ({
   redirect: vi.fn(),
 }));
 
-const { publicApi } = await import("./api");
+const { api, publicApi } = await import("./api");
+const { cookies } = await import("next/headers");
 
 const stub = (status: number) =>
   vi.stubGlobal(
@@ -17,7 +18,15 @@ const stub = (status: number) =>
     vi.fn(async () => new Response("{}", { status })),
   );
 
-afterEach(() => vi.unstubAllGlobals());
+afterEach(() => {
+  vi.unstubAllGlobals();
+  vi.restoreAllMocks();
+});
+
+const signedIn = () =>
+  vi.mocked(cookies).mockResolvedValue({
+    get: () => ({ value: "bsi_key_1" }),
+  } as never);
 
 test.each([404, 422])("publicApi maps %i to notFound", async (status) => {
   stub(status);
@@ -30,3 +39,42 @@ test("publicApi throws a plain error on 5xx and sends no auth", async () => {
   const init = vi.mocked(fetch).mock.calls[0][1];
   expect(init).toEqual({ cache: "no-store" });
 });
+
+test.each([
+  "/brands/../x",
+  "/brands/./x",
+  "/brands/%2e%2E/x",
+  "/brands/..\\x",
+  "/brands/x#y",
+  "/brands/x y",
+  "/brands/x?",
+])("api refuses %s without calling the API", async (path) => {
+  signedIn();
+  const log = vi.spyOn(console, "error").mockImplementation(() => {});
+  const fetchMock = vi.fn();
+  vi.stubGlobal("fetch", fetchMock);
+  await expect(api(path)).rejects.toThrow("NOT_FOUND");
+  expect(fetchMock).not.toHaveBeenCalled();
+  expect(log).toHaveBeenCalledWith("API path refused", path);
+});
+
+test("api sends a path with a query string as written", async () => {
+  signedIn();
+  vi.stubGlobal(
+    "fetch",
+    vi.fn(async () => new Response("{}", { status: 200 })),
+  );
+  const path = "/brands/1eb6c00a-4b18-4512-b515-dd1d8039511f/sov?days=14";
+  await api(path);
+  expect(vi.mocked(fetch).mock.calls[0][0]).toBe(
+    `http://localhost:8000/v1${path}`,
+  );
+});
+
+test("publicApi refuses a dot segment", async () => {
+  vi.spyOn(console, "error").mockImplementation(() => {});
+  const fetchMock = vi.fn();
+  vi.stubGlobal("fetch", fetchMock);
+  await expect(publicApi("/r/..")).rejects.toThrow("NOT_FOUND");
+  expect(fetchMock).not.toHaveBeenCalled();
+});
diff --git a/apps/web/src/lib/api.ts b/apps/web/src/lib/api.ts
--- a/apps/web/src/lib/api.ts
+++ b/apps/web/src/lib/api.ts
@@ -6,8 +6,19 @@ import { COOKIE } from "./cookie";
 export const API_URL = process.env.API_URL ?? "http://localhost:8000";
 export { COOKIE };
 
+// ponytail: refuses dot segments in any spelling, '\', '#' and anything the
+// URL parser would re-encode; a '?' inside a value still moves the rest of
+// the path into the query string (same key and method, shorter route).
+function sendAsWritten(path: string) {
+  const u = new URL(path, "http://api.invalid");
+  if (u.pathname + u.search === path) return;
+  console.error("API path refused", path);
+  notFound();
+}
+
 /** Server-side call to /v1. The key comes from the httpOnly cookie. */
 export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
+  sendAsWritten(path);
   const key = (await cookies()).get(COOKIE)?.value;
   if (!key) redirect("/login");
   const res = await fetch(`${API_URL}/v1${path}`, {
@@ -47,6 +58,7 @@ export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
 
 /** Server-side call to a public /v1 route: no cookie, no key. */
 export async function publicApi<T>(path: string): Promise<T> {
+  sendAsWritten(path);
   const res = await fetch(`${API_URL}/v1${path}`, { cache: "no-store" });
   // 422 = malformed token (e.g. a link truncated by a mail client): to the
   // reader that is just a link that doesn't exist.
```

## Testing

`apps/web/src/lib/api.test.ts` gains (in the diff above):

- `api refuses %s without calling the API`, for `/brands/../x`, `/brands/./x`, `/brands/%2e%2E/x`, `/brands/..\x`, `/brands/x#y`, `/brands/x y` and `/brands/x?`: with a signed-in cookie, `api(path)` rejects with the mocked `notFound`'s `NOT_FOUND`, `fetch` is not called, and `console.error` is called with `"API path refused"` and the path (R1).
- `api sends a path with a query string as written`: `/brands/1eb6c00a-4b18-4512-b515-dd1d8039511f/sov?days=14` reaches `fetch` as `http://localhost:8000/v1` plus that path.
- `publicApi refuses a dot segment`: `/r/..` rejects with `NOT_FOUND` and `fetch` is not called.

No test checks every real call site's path (R2). Expected gates: web 61 vitest (52 on main plus 9), lint, typecheck and build pass; backend unchanged at `1753 passed, 2 deselected`.

### Proof

Run 2026-10-07 in the scratchpad on a copy of main's `apps/web` (`git archive`), with the repo's `node_modules` linked.

- Red, main's code with the new tests: `Tests  8 failed | 4 passed (12)` in `api.test.ts`; the 8 are the 7 refusal cases and `publicApi refuses a dot segment`; the query-string test passes on main, as it should.
- Green, patched: `Tests  12 passed (12)`; typecheck, lint, test (`Tests  61 passed (61)`) and build (`Compiled successfully`) exit 0, with no `API path refused` line in the output. The gate's `gen:check` was not run: the copy has no backend (`scripts/export_openapi.py`). No API file changes.
- Prettier is not in the gate; both changed files pass `prettier --check`.

Each change below fails tests (counts from `api.test.ts`):

| Mutant | Change | Result | Failing assertion |
|---|---|---|---|
| M1 | no guard in `api()` | `7 failed | 5 passed (12)` | the 7 refusal cases: rejects with a TypeError (fetch called, its stub returns nothing), not `NOT_FOUND` |
| M2 | no guard in `publicApi()` | `1 failed | 11 passed (12)` | `publicApi refuses a dot segment` |
| M3 | the query string left out of the comparison | `1 failed | 11 passed (12)` | `api sends a path with a query string as written` (refused) |
| M4 | `api()`'s guard moved after `fetch` | `7 failed | 5 passed (12)` | the 7 refusal cases: `fetch` was called |
| M5 | no log line | `7 failed | 5 passed (12)` | the 7 refusal cases: `console.error` not called with the path |

## Rulings

Quoted from the ledger:

> Ruling: R1. Decided: the refusal tests sign in with a mocked cookie (a signedIn() helper) and silence console.error with vi.spyOn, and afterEach calls vi.restoreAllMocks(); none of this was in the Section 2 text. Found by: the controller, running the proof: without a cookie, mutant M4 (the guard moved after fetch) failed only because api() crashed reading an undefined cookie store, not on the "fetch not called" assertion. Why: each mutant then fails on the assertion that names its fault, and the gate output stays free of "API path refused" lines. Cost if wrong: an unexpected console.error in those tests would be hidden. How named: in chat, 2026-10-07, after the proof run.

> Ruling: R2. Decided: no test checks that every real call site's path passes the guard; the paths are built from UUIDs (route params and hidden form fields), report type slugs and URLSearchParams query strings, which the URL parser leaves unchanged, and the one query-string test pins that case. Found by: the controller, writing the design (named in Section 2). Why: the call sites are about 40 Server Component and server action paths with no page-test harness in the repo. Cost if wrong: a page whose path the URL parser re-encodes would show the not-found page, with "API path refused" and the path in the web server log. How named: in chat, 2026-10-07, in Section 2 and after the proof run.

## Deferred minors

None yet.

## Live check

None: the change refuses paths before any request, and the tests drive it with mocked `fetch`. Typing a dot segment into the browser's address bar would not exercise it, because the browser's URL parser collapses `.`, `..` and `%2e%2e` segments before the request is sent; reaching the guard needs a crafted form post.
