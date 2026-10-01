# Slice 32 findings: signing the alert webhook

## 1. What was built

The open item "No webhook signing; a consumer cannot authenticate the sender" (docs/findings-slice13.md) is closed: a brand can store a signing secret, and every alert webhook POST for that brand carries `X-BSI-Signature: t=<unix seconds>,v1=<hex>`, an HMAC-SHA256 with the secret over `t`, a dot, and the raw body. A brand without a secret is delivered exactly as before, with no extra header.

Spec: docs/superpowers/specs/2026-10-01-slice32-webhook-signing-design.md (rulings R1–R11). Plan: docs/superpowers/plans/2026-10-01-slice32-webhook-signing.md (Tasks 1–4). Merged via PR #61 (main `e929515`).

**Code**:
- packages/core/bsi_core/alerts.py: `sign(secret: str, body: bytes, now: int) -> str` returns `t=<now>,v1=<hex>`, where the digest is `hmac.new(secret.encode(), f"{now}.".encode() + body, hashlib.sha256)`. `now` is a parameter; the worker passes `int(time.time())`.
- packages/core/bsi_core/crawl.py: `http_fetch(..., headers: Mapping[str, str] | None = None)`. On every hop the caller's headers are sent, except that keys whose lower-cased name is in `_PINNED = frozenset({"host", "user-agent", "accept-encoding"})` are dropped, and the pinned `Host`, `User-Agent` and `Accept-Encoding` are merged last (R3). So a caller cannot override or duplicate the Host the SSRF guard checked, in any letter case. The loop's local dict is now `sent` (R3). Resolution, pinning, redirects, decoding, the cap and the timeouts are unchanged; the other callers (crawl, feeds, sitemaps, audits) pass no headers.
- migrations/versions/0022_brand_webhook_secret.py: adds nullable `brand.webhook_secret` (text). No new table, so no RLS or isolation rows.
- packages/core/bsi_core/models.py: `Brand.webhook_secret: Mapped[str | None]` and a property `has_webhook_secret` (`webhook_secret is not None`).
- apps/api/bsi_api/routers/brands.py: `BrandPatch.webhook_secret` (32–200 characters, no surrounding whitespace, or null to clear); `BrandOut.has_webhook_secret: bool`, and `BrandOut` never lists the secret; setting `webhook_url` to null also nulls the secret. `apps/web/openapi.json` and `apps/web/src/lib/schema.d.ts` are regenerated.
- apps/workers/bsi_workers/worker.py: `Poster.__call__` takes `headers`; `deliver_due_alerts` reads `brand.webhook_secret` in its existing tenant read and, after that session closes, passes `{"X-BSI-Signature": sign(secret, body, int(time.time()))}` when a secret is set, else `None`. No transaction is open during the POST; retries, backoff and the `FOR UPDATE` cleared-check are unchanged. Each retry signs again with a fresh `t`.
- apps/web/src/app/(app)/b/[id]/alerts/page.tsx and actions.ts, apps/web/src/lib/format.ts: the URL field is `required` to save (R1); a password input `webhook_secret` (`minLength` 32, `maxLength` 200, `autoComplete="new-password"`, R7, no `defaultValue`); a "Signing on" / "Unsigned" span; a "Remove secret" button when a secret is set; help text with the header format and the 5-minute rule. The action sends the secret as typed, omits it when the field is empty, and sends null on Remove secret, which wins over a filled field (R4). Notes: `cleared` is now "Webhook cleared; any signing secret was removed." and `secret_removed` is "Signing secret removed; deliveries are unsigned."

**Receiver contract** (spec §2; the page help text is shorter):
- Read the raw request body as bytes, before parsing or re-serialising the JSON: the signature is over the exact bytes sent.
- Split `X-BSI-Signature` into `t` and `v1`. Compute HMAC-SHA256 with the shared secret, encoded as UTF-8, over `t` (as sent), a dot, and the raw body; hex-encode it.
- Compare it to `v1` in constant time (for example Python's `hmac.compare_digest`).
- Reject the request when `|now − t| > 300` seconds.
- The secret is per brand. A brand without a secret sends no header, so a receiver that requires one rejects those deliveries.

**Tests**:
- tests/unit/test_alerts.py: `test_sign_is_an_hmac_over_t_dot_body` (fixed `now`, expected value computed with `hmac`/`hashlib`; one extra body byte changes the result).
- tests/unit/test_http_fetch.py: `test_extra_headers_are_sent_but_cannot_override_the_pinned_ones` (spoof keys `Host`, `user-agent`, `ACCEPT-ENCODING`; exactly one raw header per pinned name, names lower-cased, and `x-bsi-signature` sent).
- tests/integration/test_api_alerts.py: `test_secret_is_write_only_and_shown_as_a_flag`, `test_a_short_or_padded_secret_is_rejected` (31 characters; a leading space), `test_clearing_the_url_also_clears_the_secret`, `test_null_clears_only_the_secret`.
- tests/integration/test_worker.py: `_Hook` and the three local fake posters take `headers=None` (R2); `test_deliver_posts_the_payload_and_marks_delivered` now asserts no header without a secret; `test_deliver_signs_when_the_brand_has_a_secret` recomputes the HMAC over the raw bytes the fake received.
- apps/web/src/lib/format.test.ts: the `alertNote` test has the new `cleared` text and a `secret_removed` line.

Results, as the task reports record them:
- Task 1 red: `ImportError: cannot import name 'sign' from 'bsi_core.alerts'` (`1 error in 0.32s`); tests/unit/test_http_fetch.py alone `1 failed, 52 passed in 2.18s` with `TypeError: http_fetch() got an unexpected keyword argument 'headers'`. Green: `56 passed in 2.22s`. Gate (`gate-task1.txt`, `gate exit 0`): ruff format `171 files left unchanged`, `All checks passed!`, mypy `Success: no issues found in 29 source files`, `1560 passed, 2 deselected, 2 warnings in 227.07s (0:03:47)`.
- Task 2 red: `5 failed, 12 passed, 2 warnings` (three `KeyError: 'has_webhook_secret'`, two `assert 200 == 422`). Green: `17 passed, 2 warnings in 8.00s`. Gate (`gate-task2.txt`, `gate exit 0`): `2 files reformatted, 170 files left unchanged`, `All checks passed!`, mypy clean, `1565 passed, 2 deselected, 2 warnings in 239.83s (0:03:59)`.
- Task 3 red: `1 failed, 42 passed, 2 warnings`, `TypeError: 'NoneType' object is not subscriptable` at `headers["X-BSI-Signature"]`. Green: `43 passed, 2 warnings in 11.61s`. Gate (`gate-task3.txt`, `gate exit 0`): `1 file reformatted, 171 files left unchanged`, `All checks passed!`, mypy clean, `1566 passed, 2 deselected, 2 warnings in 209.68s (0:03:29)`.
- Task 4 red: `Tests  1 failed | 21 passed (22)`, "expected 'Webhook cleared.' to be 'Webhook cleared; any signing secret w…'". Green: `Tests  22 passed (22)`. Web gate (`gate-task4-web.txt`, `web gate exit 0`): `Tests  43 passed (43)`, `✓ Compiled successfully in 1396ms`.
- Each task's banned-word grep over its staged added lines had no match.
- The 2 warnings in every backend run are the two known third-party ones: fastapi/testclient.py `StarletteDeprecationWarning` and the starlette/testclient.py anyio `BlockingPortal` `DeprecationWarning`.
- After merge, on main `e929515` (the ledger's "After merge" lines): `gh pr checks 61` printed "gates	pass	4m4s"; the controller's backend gate printed "gate exit 0" with "1566 passed, 2 deselected, 2 warnings in 163.96s (0:02:43)" and "Total coverage: 100.00%"; the web gate printed "web gate exit 0" with "Tests  43 passed (43)".

**Commits** (`git log --oneline --reverse 5ec4c1d..e929515^2`, oldest first):

| Commit | Subject |
|---|---|
| cd76bde | docs(spec): slice 32 webhook signing design |
| 6a9bd3f | docs(spec): slice 32 review fixes R1-R5 |
| 7c9dd7f | docs(spec): slice 32 re-review fixes R6 |
| 9be422e | docs(plan): slice 32 webhook signing implementation plan |
| 9944f23 | docs: slice 32 plan review fixes R7-R8 |
| 454ccd5 | feat(alerts): sign() and an http_fetch headers keyword |
| d3f0ec8 | feat(brands): write-only webhook_secret, has_webhook_secret flag |
| 8fa2cd5 | feat(worker): sign alert deliveries with X-BSI-Signature |
| e01cf81 | feat(web): signing secret on the alerts page |

## 2. Live check on dev

Run on 2026-10-01 after merge (main `e929515`), with the user's approval in chat: "yes, docs first, then migrate dev and run the live check". Observed:
- Pre-check (read-only): no uvicorn, worker or pytest process; dev at migration 0021; 0 queued or running jobs; BSOAgentTestBrand (`34db213a-f484-4991-a969-c52cfa5e1c10`) had no webhook URL; `max(api_key.last_used_at)` = 2026-09-30 19:55:06.669119+00; no `brand.webhook_secret` column.
- Migration: `alembic upgrade head` on dev; afterwards `alembic_version` 0022, `brand.webhook_secret` text and nullable, 0 brands with a secret.
- The API was started against dev. `PATCH /v1/brands/{id}` with a generated 32-character test secret returned HTTP 200; the only body key containing "secret" was `has_webhook_secret`, which was `true`; the secret text appeared 0 times in the body; the stored value was 32 characters long.
- `GET /v1/brands/{id}` returned `has_webhook_secret: true` and no `webhook_secret` key. A PATCH with `"short"` returned HTTP 422.
- `PATCH {"webhook_secret": null}` returned HTTP 200 with `has_webhook_secret: false`; the stored secret and the webhook URL were NULL afterwards, so the brand row ended as it started.
- The API was stopped (13:46:05 UTC; the background task exited 144, as expected). Writes: `api_key.last_used_at` moved to 2026-10-01 13:46:01.188758+00, and the brand row (set, then cleared). 0 jobs queued or running. No spend.
- Not checked live: a signed delivery (spec §5); the integration test covers it with a fake poster.

## 3. Deferred and untested

From the task reviews (ledger lines tagged `minor (deferred)`):
- "Task 1: minor (deferred): the reported gate output carries 2 warnings (third-party; confirmed present on main) — "confirm the warnings were present on the base 9944f23, or filter them in the pytest config in a separate change"."
- "Task 1: minor (deferred): a caller `content-type` key in another letter case would be sent beside the `content_type` argument (crawl.py:308-309); spec §2 states and accepts this."
- "Task 1: minor (deferred): no test covers caller headers on a GET redirect's second hop (crawl.py:298-303); the spec does not require one."
- "Task 2: minor (deferred): `brands.py:181` — a combined body `{"webhook_url": null, "webhook_secret": X}` returns 200 with `has_webhook_secret: false` and no test covers it (follows spec §1)."
- "Task 2: minor (deferred): `test_api_alerts.py:118` — the parametrize covers the lower bound and a leading space only; no 201-character or trailing-whitespace case."
- "Task 2: minor (deferred): test output carries the 2 known third-party warnings (present before the change)."
- "Task 3: minor (deferred): test output carries the 2 known third-party warnings (StarletteDeprecationWarning from fastapi/testclient.py); track separately."
- "Task 3: minor (deferred): an empty-string secret would go unsigned (`if secret` at worker.py:308-312); unreachable through the API (`min_length=32`)."
- "Task 4: minor (deferred): page.tsx:47-55 — the secret input has no accessible name (placeholder only); the URL input at page.tsx:38-46 has the same pre-existing gap; suggested `aria-label`s."
- "Task 4: minor (deferred): actions.ts:16 — Clear (formNoValidate) with a short typed secret sends it beside `webhook_url: null`, so the API returns 422 instead of clearing; reviewer labelled it plan-mandated (spec §3 sends the field whenever non-empty)."
- "Task 4: minor (deferred): actions.ts:14 — Remove secret also sends the current URL field, so an edited or emptied URL is saved or cleared while the note mentions only the secret (plan behaviour, R4)."

From the final whole-branch review. The result, as recorded: "Final review aeef3df3e18981a83 over 5ec4c1d..e01cf81 — Ready to merge: Yes; 0 Critical, 0 Important, 3 Minor; every Task 1–4 deferred minor triaged "keep deferred" (including R11's Clear-with-short-secret item: "keep deferred. The plan requires this")."
- "Final: minor (deferred): crawl.py:298-302 — caller headers would follow a cross-host GET redirect (spec §2 says headers go on every hop; no GET caller passes headers today); a future credential header would leak to the redirect host; note the limit or drop headers on host change in a later slice."
- "Final: minor (deferred): page.tsx:56-58 — "Signing on" can show with no webhook URL when a secret was saved through the API alone (§1 "it waits"); cosmetic."
- "Final: minor (deferred): alerts.py:281 — the secret is encoded as UTF-8 and the receiver is not told; state "UTF-8" in docs/findings-slice32.md."

Parked: no finding was parked at a fix-loop cap. The one ledger line that uses the word is R11's ruling, which kept a task-review minor as a deferred minor (quoted above and in R11).

The ledger: "No fix wave: the final review has no Critical or Important findings."

Out of scope (spec):
- The last ordered item ("-es" folding): slice 33.
  - Note (2026-10-01): done in slice 33 (docs/findings-slice33.md).
- Server-generated or rotated secrets, a secret per webhook rather than per brand, a signature over anything but the raw body, `X-RateLimit`-style headers, a delivery log, re-delivery of alerts created before a webhook was set, and Standard Webhooks compatibility.

Carried forward from docs/findings-slice31.md §3, still open:
- The judge-agreement question, waiting on the user.
- The once-per-window sweep (slice 31 R10) has no unit test.
  - Note (2026-10-01): pinned in slice 35 by `test_the_sweep_runs_once_per_window` (docs/superpowers/specs/2026-10-01-slice35-sweep-test-design.md, PR #67): with the `_swept` guard removed it fails and the other three tests in test_ratelimit.py pass.

Untested: caller headers on a GET redirect's second hop (no caller sends headers on a GET); a secret saved through the API with no URL ("it waits", spec §1) delivering once a URL is set (by reading: `deliver_due_alerts` reads the secret at delivery time); delivery to a real receiver (spec §5: no live delivery check, since the SSRF guard refuses a localhost receiver and a public catch-all receiver would send dev alert data to a third party).

## Rulings

R1–R6 were made during the spec reviews and R7–R8 during the plan review (R1 and R7 asked in chat); R9–R11 during execution; R12 after merge, for these docs. Each is quoted from the spec (R1–R8) or the ledger (R9–R12).

- **R1: the URL input is `required`.** Decided: the alerts page's URL input gains `required`, so "Save webhook" is browser-blocked with an empty URL field; "Clear" and "Remove secret" keep `formNoValidate`; the API is unchanged, so a secret saved with no URL is reachable only through the API; the user chose this over omitting `webhook_url` from the body when the field is empty, or keeping today's behaviour and documenting it. Found by the spec review of cd76bde (the form always sends `webhook_url`, null when empty, so a secret typed with an empty URL would be nulled by `patch_brand` and the note would say "Webhook cleared."). Why: the dropped-secret case cannot happen from the page, with no change to the API or to "empty URL means clear". Cost if wrong: an operator cannot save a waiting secret from the page. Asked in chat.
- **R2: the three local `fetch` fakes and `_Hook` all gain `headers=None`.** Decided: in tests/integration/test_worker.py, `_Hook.__call__` and the local `fetch` in `test_no_transaction_is_open_during_the_webhook_post`, `test_one_failing_delivery_does_not_block_the_rest` and `test_a_delivery_that_fails_after_the_webhook_is_cleared_is_given_up` accept `headers=None`; the spec says six delivery tests, one of which unpacks `_Hook`'s tuple. Found by the spec review of cd76bde (the spec said five tests and "the existing tuple unpacking in the five delivery tests is widened"). Why: the worker always passes `headers=`, and `deliver_due_alerts` swallows the resulting `TypeError`, so those three tests would fail silently on the count. Cost if wrong: none. Named in chat when made.
- **R3: `http_fetch` renames its local to `sent` and drops the pinned names case-insensitively.** Decided: the parameter is `headers`; the loop's local dict is `sent`; caller keys whose lower-cased name is in `_PINNED` (`host`, `user-agent`, `accept-encoding`) are dropped before the pinned headers are merged; caller headers go on every hop; the unit test spoofs with mixed-case keys and asserts one raw header per pinned name. Found by the spec review of cd76bde (with one name a GET redirect would merge the first hop's dict; a case-sensitive merge lets `host` ride beside `Host`, and httpx sends both). Why: the approved property "a caller cannot override the pinned headers" must hold in any letter case, and the shared function must stay mypy-clean. Cost if wrong: a few more lines in a shared function, covered by the new test. Named in chat when made.
- **R4: the web action does not trim the secret; Remove secret wins; the `cleared` note mentions the secret.** Decided: `setWebhook` sends the secret as typed (the API's whitespace rule, 422, is the guard); `clear_secret` wins over a filled secret field; the `queued=` value is `secret_removed` whenever Remove secret was pressed; `ALERT_NOTES.cleared` becomes "Webhook cleared; any signing secret was removed." and format.test.ts follows. Found by the spec review of cd76bde (§3's trimming contradicted §1's byte-for-byte rule; precedence and the silent secret removal on Clear were unstated). Why: one rule for whitespace, stated precedence, and no silent removal. Cost if wrong: copy only. Named in chat when made.
- **R5: the review's remaining minors were applied.** Decided: worker.py's `Mapping` and `sign` imports named; the live check's brand id written in full; the `ALERT_NOTES` change worded as a new key in the literal and the redirect parameter named `queued=`; format.test.ts's `alertNote` test named; Context's description of the body assignment matches the code. Found by the spec review of cd76bde. Why: accuracy for the plan writer. Cost if wrong: none. Named in chat when made.
- **R6: the re-review's three minors were applied.** Decided: the claim that `mypy --strict` rejects the indexed assignment is dropped from §2 and R3 (the rename stands on the redirect-hop reason; the review ran mypy on that shape and it passes); §4 says raw header names are compared lower-cased, since httpx keeps the sent case; §2 says `Content-Type` is not in `_PINNED`. Found by the re-review of 6a9bd3f. Why: the spec must state no false fact. Cost if wrong: none. Named in chat when made.
- **R7: the secret input uses `autoComplete="new-password"`.** Decided: the alerts page's secret input is `type="password"` with `autoComplete="new-password"` instead of `"off"`; the user chose this over keeping `"off"`, or a plain text input. Found by the plan review of 9be422e (browsers, Chrome in particular, often ignore `autocomplete=off` on a password field and may autofill a saved login password, which "Save webhook" would then send as the secret). Why: `new-password` is the value browsers honour to suppress login autofill, and the field stays masked. Cost if wrong: one attribute value. Asked in chat.
- **R8: the plan review's minors 1–5 were applied to the plan.** Decided: Task 2 Step 2 states only the red result; the plan's self-review drops the non-departure (the spoof keys the spec itself names) and lists the six wording additions (comments, a docstring and a test constant); Tasks 2 and 3 say which lines `ruff format .` reflows and to re-stage; the Files lines read `crawl.py:225` and `worker.py:298-311`; Task 4 Step 2 shows vitest's single quotes. Found by the plan review of 9be422e. Why: accuracy for the implementer. Cost if wrong: none. Named in chat when made.
- **R9: commits from execution on carry the Opus 5.5 trailer.** (Title: writer's own wording.) The ledger line, as recorded: "Ruling: R9 — Decided: every commit from execution on carries "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; the earlier slice 32 commits (cd76bde, 6a9bd3f, 7c9dd7f, 9be422e, 9944f23) keep the Fable 5.1 trailer. Found by: the controller, on a new attribution reminder naming Opus 5.5 after the execution choice. Why: the plan's Global Constraint binds the trailer to the latest session reminder. Cost if wrong: mixed trailers within one branch. How named: named in chat when made."
- **R10: subagent dispatches omit the model parameter.** (Title: writer's own wording.) The ledger line, as recorded: "Ruling: R10 — Decided: subagent dispatches omit the Agent `model` parameter. Found by: the controller, the session being on Opus 5.5. Why: memory rule "omit the Agent model param on Opus". Cost if wrong: none (the inherited model is Opus 5.5). How named: named in chat when made."
- **R11: Task 4's Clear-with-a-short-secret minor is parked for the final review.** (Title: writer's own wording.) The ledger line, as recorded: "Ruling: R11 — Decided: Task 4's plan-mandated minor (Clear with a short typed secret → 422) is parked as a deferred minor for the final review to triage; if the final review wants it fixed, the change (skip `webhook_secret` when Clear is pressed) goes to the user as a question before the fix wave. Found by: Task 4 review a707e10230c366409 (Minor 2, labelled plan-mandated). Why: it changes approved spec §3 behaviour, and design changes from reviews are asked first. Cost if wrong: an operator who half-types a secret and presses Clear sees an error page until the field is emptied. How named: named in chat when made."
- **R12: one commit applies the docs review's points and records the live check.** (Title: writer's own wording.) The ledger line, as recorded: "Ruling: R12 — Decided: one commit applies the docs review's 1 Important and 4 Minor and records the live check in findings §2; one scoped re-review of that commit; its findings, if any, go in the PR description. Found by: the controller, after review a929107c60b8973ca and the live check. Why: §2 must carry the live check anyway, and the review's points are wording or sourcing; the post-merge docs get one review round as in earlier slices. Cost if wrong: re-review findings stay in the PR description instead of the docs. How named: named in chat when made."
