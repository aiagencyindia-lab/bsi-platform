# Slice 32 design: signing the alert webhook

## Context

Codebase facts: main `5ec4c1d`, checked 2026-10-01.

The third of the four smaller items the user ordered on 2026-10-01 (labels, rate limits, webhook signing, "-es" folding). docs/findings-slice13.md records the gap: "No webhook signing; a consumer cannot authenticate the sender." The slice 13 spec's cost line says "add an HMAC header later."

Facts read before the approaches (direct reads on Fable 5.1):
- Delivery is `deliver_due_alerts` in apps/workers/bsi_workers/worker.py: a `tenant_session` read of the alert and brand builds `body = json.dumps(payload(alert, brand.name), default=str).encode()`, the session closes, then `fetch(url, WEBHOOK_UA, method="POST", body=body, content_type="application/json")`. The `Poster` protocol fixes that call signature. Retries follow `BACKOFF_DELIVERY`; the webhook-cleared check uses `SELECT … FOR UPDATE` on `brand.webhook_url`.
- `http_fetch` in packages/core/bsi_core/crawl.py builds its headers dict inline (`Host`, `User-Agent`, `Accept-Encoding`, and `Content-Type` when given). There is no parameter for other headers. It is shared with crawling, feeds and sitemaps, so any change to it is covered by tests/unit/test_http_fetch.py.
- `Brand.webhook_url` (packages/core/bsi_core/models.py, migration 0016) is validated by `_webhook_url` in apps/api/bsi_api/routers/brands.py: HTTPS, public host, default port, no userinfo. So a header carrying a signature is never sent in clear.
- `BrandOut` (`from_attributes=True`) returns `webhook_url`; `_patch` applies every set field of `BrandPatch` with `setattr`; `patch_brand` nulls pending deliveries when `webhook_url` is set to null. Migrations end at 0021. `Organization.settings` (JSONB, default `{}`) is unused.
- The web form is apps/web/src/app/(app)/b/[id]/alerts/page.tsx with the server action `setWebhook` in actions.ts (`clear=1` or an empty URL sends `webhook_url: null`); notes are in `ALERT_NOTES` in apps/web/src/lib/format.ts; `Brand` is `S["BrandOut"]` from the generated schema.
- Tests: tests/unit/test_alerts.py (`payload`), tests/unit/test_http_fetch.py (the recording `MockTransport` and `test_post_sends_the_body_and_content_type_to_the_pinned_address`), tests/integration/test_worker.py (`_Hook` fake poster; five delivery tests from line 930), tests/integration/test_api_alerts.py (webhook URL validation, clearing). tests/integration/test_isolation.py already has `("PATCH", "/v1/brands/{b}", {"name": "x"})`.

Classification, said in chat as the first line of the first brainstorming reply: **architectural** — "webhook signing adds a new interface (a signature header that receivers verify), a stored secret (new column or JSONB key, possibly migration 0022), a change to the shared `crawl.http_fetch` (which crawling also uses), plus API, web and worker changes."

Decisions approved in chat (brainstorming on Fable 5.1, 2026-10-01, in plan mode; implementer and reviewer subagents on Opus 5.5). Each decision had three approaches with trade-offs and a recommendation in a chat message before its question:
- D1, where the secret lives: a per-brand column `brand.webhook_secret` (over a per-org key in `Organization.settings`, and a global env secret). The user chose the per-brand column.
- D2, how the operator sets it: the operator supplies it, write-only on `PATCH /v1/brands/{id}`, and `BrandOut` reports only `has_webhook_secret` (over a server-generated secret shown once by a new route, and auto-generation on the first URL set). The user chose operator-supplied.
- D3, the format: one header, `X-BSI-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256>` over `"{t}." + body` (over a plain body HMAC with no timestamp, and the Standard Webhooks three-header spec). The user chose the timestamped HMAC.
Each design section's text was in chat before its approval question; the user approved Sections 1–5, and with Section 5 the API-only live check. The user then approved the plan-mode plan.

## Design

### 1. Data and API

- Migration `migrations/versions/0022_brand_webhook_secret.py` (`revision = "0022"`, `down_revision = "0021"`): `op.add_column("brand", sa.Column("webhook_secret", sa.Text()))`; downgrade drops it. Nullable, no default, no index. No new table, so no RLS, `TENANT_TABLES`, `org_b` or isolation `CASES` work.
- `models.Brand.webhook_secret: Mapped[str | None]` under `webhook_url`, with the comment: shared with the receiver, read only by the worker when it signs a delivery; null = unsigned. A property `has_webhook_secret` on `Brand` returns `self.webhook_secret is not None`, so `BrandOut` (`from_attributes=True`) can read it without a validator.
- In apps/api/bsi_api/routers/brands.py: a type `WebhookSecret = Annotated[str, Field(min_length=32, max_length=200), AfterValidator(_webhook_secret)]` where `_webhook_secret` raises `ValueError("no surrounding whitespace")` when `value.strip() != value` (the receiver's copy must match byte for byte). `BrandPatch.webhook_secret: WebhookSecret | None = None`. `BrandOut.has_webhook_secret: bool`. `BrandOut` does not list `webhook_secret`, so no route returns it.
- `patch_brand`: `_patch` already applies `webhook_secret` (set or null) through `setattr`. In the existing `webhook_url is None` branch, also `brand.webhook_secret = None`: a secret without a URL is dead state. Setting a secret with no URL is allowed; it waits. The pending-delivery nulling is unchanged.
- `npm run gen` afterwards; `apps/web/openapi.json` and `apps/web/src/lib/schema.d.ts` are committed.

### 2. Signing and delivery

- In packages/core/bsi_core/alerts.py, after `payload`:

```python
def sign(secret: str, body: bytes, now: int) -> str:
    """The X-BSI-Signature value: `t=<now>,v1=<hex>` where the digest is
    HMAC-SHA256 with `secret` over `"{now}." + body`. The receiver
    recomputes it from the raw body and rejects a stale `t`."""
    mac = hmac.new(secret.encode(), f"{now}.".encode() + body, hashlib.sha256)
    return f"t={now},v1={mac.hexdigest()}"
```

  `hmac` and `hashlib` are stdlib; `now` is a parameter so the unit test is deterministic (the worker passes `int(time.time())`).
- `crawl.http_fetch` gains a keyword `headers: Mapping[str, str] | None = None` (import `Mapping` from `collections.abc`, where `Callable` already comes from) and sends `{**(headers or {}), "Host": host, "User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}` plus `Content-Type` when given: the pinned headers are merged last, so a caller cannot override the Host the SSRF guard checked or the User-Agent. Nothing else in `http_fetch` changes (resolution, pinning, redirects, decoding, cap, timeouts). The docstring gains one line: "`headers` are sent as given; Host, User-Agent and Accept-Encoding win."
- `worker.Poster.__call__` gains `headers: Mapping[str, str] | None = None`. In `deliver_due_alerts`, the existing tenant-session read also takes `brand.webhook_secret`; after the session closes, `headers = {"X-BSI-Signature": sign(secret, body, int(time.time()))} if secret else None` and the call becomes `fetch(url, WEBHOOK_UA, method="POST", body=body, content_type="application/json", headers=headers)`. The POST still runs with no transaction open; the attempt count, backoff and the `FOR UPDATE` cleared-check are unchanged. A brand with a URL and no secret is delivered exactly as today (no header), so existing receivers such as Slack incoming webhooks see no change.
- Receiver contract (in the page help text and findings): compute HMAC-SHA256 with the shared secret over `"{t}." + raw body`, compare to `v1` in constant time, and reject when `|now − t| > 300` seconds. The signature is over the exact bytes sent, so the receiver must verify before parsing or re-serialising the JSON.

### 3. Web

- apps/web/src/app/(app)/b/[id]/alerts/page.tsx: the webhook form gains a second input, `name="webhook_secret"`, `type="password"`, `minLength={32}`, `maxLength={200}`, `autoComplete="off"`, placeholder "Signing secret (optional, 32+ characters)", no `defaultValue` (the API never returns it). Beside it a muted span from `brand.has_webhook_secret`: "Signing on" or "Unsigned". When `has_webhook_secret` is true, a third button `name="clear_secret" value="1" formNoValidate` labelled "Remove secret". The help paragraph gains: "With a signing secret set, each POST carries `X-BSI-Signature: t=<unix seconds>,v1=<hex>`, an HMAC-SHA256 with the secret over `t`, a dot, and the raw body; reject a `t` more than 5 minutes old."
- actions.ts `setWebhook`: reads `webhook_secret` (trimmed) and `clear_secret`. Body: `webhook_url` as today; plus `webhook_secret: null` when `clear_secret === "1"`, `webhook_secret: value` when the field is non-empty, and no key when it is empty (the secret is left as it is). The redirect note is `secret_removed` when `clear_secret` was pressed, else `cleared`/`saved` as today. The URL "Clear" button is unchanged; the API nulls the secret with the URL.
- apps/web/src/lib/format.ts: `ALERT_NOTES.secret_removed = "Signing secret removed; deliveries are unsigned."`.
- `Brand` picks up `has_webhook_secret` from the regenerated schema. No new vitest: `setWebhook` is a thin fetch wrapper, as `scanNow` is, and neither has a test today; `npm run gate` keeps the 43 existing tests green.

### 4. Tests

- tests/unit/test_alerts.py: `test_sign_is_an_hmac_over_t_dot_body` — with `now = 1700000000`, `secret = "s" * 32` and `body = b'{"text":"hi"}'`, `sign()` equals `f"t=1700000000,v1={hmac.new(b"s" * 32, b"1700000000." + body, hashlib.sha256).hexdigest()}"`; appending a byte to the body changes the result.
- tests/unit/test_http_fetch.py, after `test_post_sends_the_body_and_content_type_to_the_pinned_address`: `test_extra_headers_are_sent_but_cannot_override_the_pinned_ones` — a POST through `server(ok)` with `headers={"X-BSI-Signature": "sig", "Host": "evil.example", "User-Agent": "spoof"}`; the recorded request has `x-bsi-signature` "sig", `host` "hook.example.com" and `user-agent` "UA".
- tests/integration/test_worker.py: `_Hook.__call__` gains `headers=None` and records `(url, ua, method, content_type, json.loads(body), body, headers)`; the existing tuple unpacking in the five delivery tests is widened. `test_deliver_posts_the_payload_and_marks_delivered` also asserts the recorded `headers is None`. New `test_deliver_signs_when_the_brand_has_a_secret`: `_hooked_brand` plus `webhook_secret = "s" * 32` set through the owner session; after `deliver_due_alerts(fetch=hook) == 1`, parse the header as `t=<int>,v1=<hex>`, assert `abs(time.time() - t) < 60`, and assert `v1` equals the HMAC recomputed from the secret and the recorded raw bytes.
- tests/integration/test_api_alerts.py: `test_secret_is_write_only_and_shown_as_a_flag` — PATCH `{"webhook_secret": "s" * 32}` → 200, the body has no `webhook_secret` key and `has_webhook_secret` is true, the owner session reads the secret back; `test_a_short_or_padded_secret_is_rejected`, parametrized over `"s" * 31` and `" " + "s" * 32` → 422; `test_clearing_the_url_also_clears_the_secret` — set both, PATCH `{"webhook_url": null}` → `has_webhook_secret` false and the column null; `test_null_clears_only_the_secret` — set both, PATCH `{"webhook_secret": null}` → `has_webhook_secret` false and `webhook_url` unchanged.
- No new RLS or isolation rows (no new table or route). Migration 0022 runs under `conftest`'s `alembic upgrade head` on `bsi_test`.
- Red and green, checked on 2026-10-01 on scratch copies outside the repo (a patched copy of `bsi_core` and a test file in a separate folder): on main's code the two unit tests fail at collection (`ImportError: cannot import name 'sign' from 'bsi_core.alerts'`); with the patched copy `2 passed`; `mypy --strict` with the repo config is clean on the two patched modules. The integration and API tests are written in execution and run against the shared test DB.
- Copy: new strings, test names, fixtures and comments are checked against `FORBIDDEN` in tests/unit/test_recommend_copy.py by a grep of the diff.

### 5. Docs, dev migration, live check

- Docs after merge: docs/findings-slice32.md; a dated note ("Note (2026-10-01): signed in slice 32, `X-BSI-Signature`") under the "No webhook signing" line in docs/findings-slice13.md, keeping the original; README rows for the spec, the plan and the findings.
- Dev migration: 0021 → 0022 is one nullable column; the controller asks before `alembic upgrade head` on dev.
- Live check (approved with Section 5): after merge and the dev migration, start uvicorn against dev, `PATCH /v1/brands/34db213a-…` with a 32-character test secret, check `has_webhook_secret: true` and no `webhook_secret` key in the body, then `PATCH {"webhook_secret": null}` and check the flag is false; stop uvicorn. Writes: `api_key.last_used_at` and the brand row (ends as it started). Spend: none. No live delivery check: the SSRF guard refuses a localhost receiver, and a public catch-all receiver would send dev alert data to a third party; delivery signing is covered by the integration test with the fake poster.
- Gates: both, run by the controller before the finishing menu.

## Rulings

None yet.

## Out of scope

- The last ordered item ("-es" folding): slice 33.
- Server-generated or rotated secrets, a secret per webhook rather than per brand, a signature over anything but the raw body, `X-RateLimit`-style headers, a delivery log, re-delivery of alerts created before a webhook was set, and Standard Webhooks compatibility.
