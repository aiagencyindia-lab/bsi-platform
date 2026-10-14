# Slice 71 follow-up: reset the redirect mock after each api test (design)

Date: 2026-10-14 (IST). Base: main 40aa797 (slice 71's PR 151 merged). Session model Opus 5.5.

## 1. Goal

Slice 71 moved the web tests from vitest 3.2.7 to 5.0.4. On vitest 5, `vi.restoreAllMocks()` in an `afterEach` no longer drops a `mockImplementationOnce` that a test queued but never used, so it fires in the next test that calls the mock. On vitest 3.2.7 it was dropped. `apps/web/src/lib/api.test.ts` relies on `restoreAllMocks` for its module-level `redirect` mock. This change resets that mock in the `afterEach`. Today no test in the suite leaves an unused once-impl, so nothing fails now; the reset keeps a future one from leaking.

## 2. Facts the design rests on

- The between-tests probe (`07-between-tests-*.txt`). Test a calls a plain `vi.fn` and a module-mock `redirect`, and queues a throwing once-impl on each. With `restoreAllMocks` in `afterEach`, test b then reports:
  - vitest 3.2.7: `plain.calls=0 redirect.calls=0 plain.once=no-throw redirect.once=no-throw`
  - vitest 5.0.4: `plain.calls=0 redirect.calls=0 plain.once=PLAIN_ONCE redirect.once=REDIRECT_ONCE`
  So between tests vitest 5.0.4 still clears call history, and only the unused once-impl survives. The clearing comes from vitest 5's default `clearMocks: true` (vitest 3.2.7 defaults to `false`), which runs `vi.clearAllMocks()` before each test; `clearAllMocks` keeps queued implementations. `restoreAllMocks` itself resets neither a `vi.fn`'s history nor its once-impls on 5.0.4.
- `api.test.ts` (as at main 40aa797):
  - lines 5–10 mock `next/navigation` with `redirect: vi.fn()`;
  - lines 22–28 run `vi.unstubAllGlobals()` and `vi.restoreAllMocks()`, then reset `cookies` only;
  - lines 119–121 queue a throwing once-impl on `redirect`, which line 124 uses within the same test.
- `src/app/(app)/b/[id]/serp/actions.test.ts`, the only other `restoreAllMocks` user, calls `redirect.mockClear()` in its own `afterEach`. `mockClear()` keeps a queued implementation, so that file's exposure is the same kind of leak. It is out of scope here, because no test in it queues a once-impl on `redirect`.
- Slice 63's R4 (findings-slice63.md line 129) closed the redirect-reset minor on two premises: that `restoreAllMocks` resets call history, and that it drops a queued once-impl. On vitest 5.0.4 neither holds for `restoreAllMocks`; call history is still cleared between tests, but by the default `clearMocks: true`, and a queued once-impl survives. R4's "Cost if wrong" names this fix: one `vi.mocked(redirect).mockReset()` in the afterEach.

## 3. User decisions

1. Start the follow-up fix inside slice 71, through the full process ("yes, start the follow-up fix").
2. Approach: one line in `api.test.ts`'s `afterEach` (options shown: one line in afterEach, recommended; `mockReset: true` in `vitest.config.ts`; `resetAllMocks` in `api.test.ts`).
3. Add a guard test (options shown: add guard test, recommended; no guard test); design sections 1–4 approved, one "yes" each.
4. The proof showed the guard as designed (`expect(redirect).not.toHaveBeenCalled()` after the `/login` test) passes without the fix on vitest 5.0.4, because history is still cleared. Re-asked: line only (options shown: line only, recommended; line plus a two-test guard pair; no code change).
5. Revised sections 1–4 approved, one "yes" each.

## 4. The change

Only `apps/web/src/lib/api.test.ts` changes. There is no production code, config or dependency change, and the web suite stays at 93 tests in 9 files. The diff, generated from the proof copy (`14-diff.txt`):

```diff
diff --git a/apps/web/src/lib/api.test.ts b/apps/web/src/lib/api.test.ts
index 197c27f..911358f 100644
--- a/apps/web/src/lib/api.test.ts
+++ b/apps/web/src/lib/api.test.ts
@@ -25,6 +25,9 @@ afterEach(() => {
   // restoreAllMocks keeps a vi.fn's mockResolvedValue; drop the cookie so
   // a test that forgets signedIn() cannot inherit the previous one's.
   vi.mocked(cookies).mockReset();
+  // On vitest 5, restoreAllMocks keeps a once-impl a test queued but never
+  // used; reset redirect so it cannot fire in the next test.
+  vi.mocked(redirect).mockReset();
 });
 
 // Only the cookie api() reads carries the key, so a wrong name sends none.
```

`redirect` is a bare `vi.fn()`, so `mockReset()` returns it to no calls, no queued implementations and an `undefined` return, which is what every test in the file expects; it would also clear call history if `clearMocks` were ever turned off. The `/login` test queues and uses its own once-impl within the test, so the reset does not affect it.

## 5. Proof

All runs are on scratch copies, outputs in `out71f/`. Each vitest exit code is recorded from vitest itself, with the raw output saved to a `.raw` file first. For the red and green runs and m3, a scratch-only test is inserted right before the `/login` test:

```ts
test("m2 scratch: queue a throwing once-impl and never use it", () => {
  vi.mocked(redirect).mockImplementationOnce(() => {
    throw new Error("LEAKED");
  });
});
```

| Run | Tree | Change | Result |
|---|---|---|---|
| Red (`10`) | 40aa797, vitest 5.0.4 | scratch test, no fix | vitest exit 1: the `/login` test fails with `expected [Function] to throw error including 'REDIRECT' but got 'LEAKED'`, `Tests  1 failed \| 28 passed (29)` |
| Green (`11`) | 40aa797, vitest 5.0.4 | scratch test plus the fix | exit 0, `Tests  29 passed (29)` |
| m3 (`13`) | 7368942, vitest 3.2.7 | scratch test, no fix | exit 0, `Tests  29 passed (29)`: the leak is new with vitest 5 |
| Real change (`12`) | 40aa797, vitest 5.0.4 | the fix only | exit 0, `Tests  28 passed (28)` (api.test.ts) |
| Web gate (`16`) | 40aa797 plus the fix | after the `15-precheck.txt` pre-check | `gate exit 0`: `RUN  v5.0.4`, `Test Files  9 passed (9)`, `Tests  93 passed (93)`, `▲ Next.js 15.5.27`, `gen:check` clean |

The Section 2 text shown in chat during design gave (30) counts for the red and green runs. Those were copied from superseded runs that still included the dropped guard test (`out71f/superseded/`, not relied on; their `vitest exit` lines recorded `sed`'s exit). The real counts are the ones above.

Planned at execution: both local gates, each after a saved pytest pre-check (§6).

## 6. Verification and merge

1. Pytest pre-check as its own command, output saved. Backend gate expected: `185 files already formatted`, `All checks passed!`, `Success: no issues found in 31 source files`, coverage 100%, `1811 passed, 2 deselected`, no warnings summary.
2. Pre-check again, saved. Web gate expected: `RUN  v5.0.4`, `Test Files  9 passed (9)`, `Tests  93 passed (93)` after stripping ANSI codes, `▲ Next.js 15.5.27`, `gen:check` clean.
3. Open the PR. On "check ci": one `gh pr checks --watch`; `gates` must pass; merge with `--merge --delete-branch`; then `git ls-remote --heads origin slice71-restore-fix`.
4. No live checks against the app, no database migration, no worker, no model or DataForSEO spend. The only GitHub writes are this PR and its merge.

## 7. Out of scope

- `actions.test.ts`'s `redirect.mockClear()`, which also keeps a queued implementation; no test there queues one on `redirect`.
- A global `mockReset` or `restoreMocks` setting in `vitest.config.ts`.
- A guard test, dropped at decision 4.
- Everything slice 71's spec lists as out of scope.
