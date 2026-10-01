# Slice 32 Webhook Signing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A brand with a signing secret gets every alert webhook POST signed with `X-BSI-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256>` over `"{t}." + body`; the operator sets the secret write-only through the API or the alerts page, and the API reports only `has_webhook_secret`.

**Architecture:** `alerts.sign()` (stdlib hmac) builds the header value; `crawl.http_fetch` gains a `headers` keyword whose pinned names (Host, User-Agent, Accept-Encoding) cannot be overridden; `deliver_due_alerts` reads `brand.webhook_secret` in its existing tenant-session read and signs after the session closes. A nullable `brand.webhook_secret` column (migration 0022) is set through `BrandPatch` and cleared with the URL; the alerts page gets a password input, a status span and a "Remove secret" button.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Alembic, pydantic 2, FastAPI, httpx, pytest (shared `bsi_test` DB); Next.js 15 Server Actions, TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-10-01-slice32-webhook-signing-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`. In zsh a variable holding several paths is not split into words; pass paths literally.
- **Branch:** `slice32-webhook-signing`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB, the network or the worker loop. Never call a model.
- **Unchanged:** `http_fetch`'s resolution, pinning, redirect, decoding, cap and timeout logic; `deliver_due_alerts`'s retry, backoff and `FOR UPDATE` logic; `_webhook_url`; the existing tests' expectations (only additions and the exact edits this plan names).
- **Shared test DB:** run `pgrep -fl pytest` first, and never run two suites at once. Run the full backend suite only once per task, in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal: read the file and repeat the edit.)
- **Writing files:** never use a shell heredoc or zsh `echo` to write files; use the Edit or Write tools.
- **Lint and types:** ruff line length is 80 (the Backend gate runs `ruff format .` first); RUF001 rejects a literal curly apostrophe. The gate's mypy covers only `packages/core/bsi_core`; apps/api and apps/workers are not type-checked by the gate.
- **Banned words:** copy (code, comments, docstrings, test names, fixtures, response bodies, docs) never contains `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat` or `certain` (`FORBIDDEN` in tests/unit/test_recommend_copy.py).
- **Banned-word grep:** `grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1|top spot|dominat|certain'`, run on added lines only (`git diff --cached -U0 | grep '^+' | <the grep>` after staging; a new file is grepped directly). Expected: no match.
- **Backend gate:** `{ uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-taskN.txt 2>&1; echo "gate exit $?"` (the echo prints to the terminal, not to a file).
- **Web gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate > <workspace>/gate-taskN-web.txt 2>&1; echo "web gate exit $?"`.
- **Commit trailer:** the `Co-Authored-By` line from the latest session reminder.
- **Baseline counts** (collected 2026-10-01 on `7c9dd7f`): backend `1558 passed, 2 deselected`; tests/unit/test_http_fetch.py 52, tests/unit/test_alerts.py 2, tests/integration/test_worker.py 42, tests/integration/test_api_alerts.py 12; web 43 vitest.

## File map

| File | Responsibility |
|---|---|
| `packages/core/bsi_core/alerts.py` | `sign(secret, body, now)` |
| `packages/core/bsi_core/crawl.py` | `_PINNED`; `http_fetch(..., headers=)`; local dict renamed `sent` |
| `tests/unit/test_alerts.py` | the HMAC vector |
| `tests/unit/test_http_fetch.py` | extra headers sent, pinned ones not overridable |
| `migrations/versions/0022_brand_webhook_secret.py` (new) | the column |
| `packages/core/bsi_core/models.py` | `Brand.webhook_secret`, `Brand.has_webhook_secret` |
| `apps/api/bsi_api/routers/brands.py` | `_webhook_secret`, `WebhookSecret`, `BrandPatch.webhook_secret`, `BrandOut.has_webhook_secret`, the clear in `patch_brand` |
| `tests/integration/test_api_alerts.py` | write-only secret, 422s, clearing |
| `apps/web/openapi.json`, `apps/web/src/lib/schema.d.ts` | regenerated |
| `apps/workers/bsi_workers/worker.py` | `Poster.headers`; signing in `deliver_due_alerts` |
| `tests/integration/test_worker.py` | `_Hook` and the three local fakes take `headers`; the signed delivery |
| `apps/web/src/app/(app)/b/[id]/alerts/page.tsx` | `required` URL, secret input, status span, Remove secret |
| `apps/web/src/app/(app)/b/[id]/alerts/actions.ts` | `webhook_secret` in the PATCH body; `secret_removed` note |
| `apps/web/src/lib/format.ts`, `apps/web/src/lib/format.test.ts` | the two notes |

---

### Task 1: `sign()` and `http_fetch` headers

**Files:**
- Modify: `packages/core/bsi_core/alerts.py` (imports at lines 8–9; append after `payload`)
- Modify: `packages/core/bsi_core/crawl.py:16` (import), `:226` (new constant before `_REDIRECTS_REFUSED`), `:233-258` (signature and docstring), `:294-306` (the headers dict and the `client.stream` call)
- Test: `tests/unit/test_alerts.py`, `tests/unit/test_http_fetch.py` (after line 432, the end of `test_post_sends_the_body_and_content_type_to_the_pinned_address`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `bsi_core.alerts.sign(secret: str, body: bytes, now: int) -> str`; `bsi_core.crawl.http_fetch(..., headers: Mapping[str, str] | None = None)`; `bsi_core.crawl._PINNED`.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_alerts.py`, replace the import block

```python
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from bsi_core.alerts import drop_copy, payload, shift_copy, source_copy
```

with

```python
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from bsi_core.alerts import drop_copy, payload, shift_copy, sign, source_copy
```

and append at the end of the file:

```python


def test_sign_is_an_hmac_over_t_dot_body():
    body = b'{"text":"hi"}'
    want = hmac.new(
        b"s" * 32, b"1700000000." + body, hashlib.sha256
    ).hexdigest()
    assert sign("s" * 32, body, 1700000000) == f"t=1700000000,v1={want}"
    assert sign("s" * 32, body + b" ", 1700000000) != sign(
        "s" * 32, body, 1700000000
    )
```

In `tests/unit/test_http_fetch.py`, after `test_post_sends_the_body_and_content_type_to_the_pinned_address` (its last line is `    assert req.url.host == PUBLIC`), insert:

```python


def test_extra_headers_are_sent_but_cannot_override_the_pinned_ones():
    t = server(ok)
    r = http_fetch(
        "https://hook.example.com/in",
        "UA",
        resolve=dns({"hook.example.com": [PUBLIC]}),
        transport=t,
        method="POST",
        body=b"{}",
        content_type="application/json",
        headers={
            "X-BSI-Signature": "sig",
            "Host": "evil.example",
            "user-agent": "spoof",
            "ACCEPT-ENCODING": "br",
        },
    )
    assert r.ok
    (req,) = t.seen
    assert req.headers["x-bsi-signature"] == "sig"
    # httpx keeps the sent letter case in .raw; compare names lower-cased.
    raw = [(k.lower(), v) for k, v in req.headers.raw]
    for name, value in (
        (b"host", b"hook.example.com"),
        (b"user-agent", b"UA"),
        (b"accept-encoding", b"gzip, deflate"),
    ):
        assert [v for k, v in raw if k == name] == [value]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q -p no:cacheprovider tests/unit/test_alerts.py tests/unit/test_http_fetch.py 2>&1 | tail -5`
Expected: collection error for test_alerts.py: `ImportError: cannot import name 'sign' from 'bsi_core.alerts'`; test_http_fetch.py is not reached because the error interrupts the run. Then run test_http_fetch.py alone: `uv run pytest -q -p no:cacheprovider tests/unit/test_http_fetch.py 2>&1 | tail -3`. Expected: `1 failed, 52 passed`, the failure `TypeError: http_fetch() got an unexpected keyword argument 'headers'`.

- [ ] **Step 3: Add `sign()`**

In `packages/core/bsi_core/alerts.py`, replace

```python
import json
import uuid
from dataclasses import dataclass
```

with

```python
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
```

and append at the end of the file:

```python


def sign(secret: str, body: bytes, now: int) -> str:
    """The X-BSI-Signature value: `t=<now>,v1=<hex>` where the digest is
    HMAC-SHA256 with `secret` over `"{now}." + body`. The receiver
    recomputes it from the raw body and rejects a stale `t`."""
    mac = hmac.new(secret.encode(), f"{now}.".encode() + body, hashlib.sha256)
    return f"t={now},v1={mac.hexdigest()}"
```

- [ ] **Step 4: Add `headers` to `http_fetch`**

In `packages/core/bsi_core/crawl.py`, replace

```python
from collections.abc import Callable, Iterator
```

with

```python
from collections.abc import Callable, Iterator, Mapping
```

Replace

```python
_REDIRECTS_REFUSED = "too many redirects"
```

with

```python
# Caller headers never replace these (dropped by lower-cased name).
_PINNED = frozenset({"host", "user-agent", "accept-encoding"})
_REDIRECTS_REFUSED = "too many redirects"
```

Replace

```python
    cap: int = BODY_CAP_BYTES,
    raw: bool = False,
) -> Response:
```

with

```python
    cap: int = BODY_CAP_BYTES,
    raw: bool = False,
    headers: Mapping[str, str] | None = None,
) -> Response:
```

Replace

```python
    `cap` bounds the decoded bytes kept (every guard is unchanged);
    `truncated` says the cap cut the body. `raw=True` decodes the bytes as
    Latin-1, which is lossless: `body.encode('latin-1')` gives the exact
    bytes back.
    """
```

with

```python
    `cap` bounds the decoded bytes kept (every guard is unchanged);
    `truncated` says the cap cut the body. `raw=True` decodes the bytes as
    Latin-1, which is lossless: `body.encode('latin-1')` gives the exact
    bytes back. `headers` go on every hop; Host, User-Agent and
    Accept-Encoding are always the pinned ones.
    """
```

Replace

```python
                headers = {
                    "Host": host,
                    "User-Agent": user_agent,
                    "Accept-Encoding": "gzip, deflate",
                }
                if content_type:
                    headers["Content-Type"] = content_type
                with client.stream(
                    method,
                    target,
                    content=body,
                    headers=headers,
                    extensions=ext,
```

with

```python
                sent = {
                    k: v
                    for k, v in (headers or {}).items()
                    if k.lower() not in _PINNED
                } | {
                    "Host": host,
                    "User-Agent": user_agent,
                    "Accept-Encoding": "gzip, deflate",
                }
                if content_type:
                    sent["Content-Type"] = content_type
                with client.stream(
                    method,
                    target,
                    content=body,
                    headers=sent,
                    extensions=ext,
```

- [ ] **Step 5: Run the two files to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q -p no:cacheprovider tests/unit/test_alerts.py tests/unit/test_http_fetch.py 2>&1 | tail -3`
Expected: `56 passed` (3 + 53).

- [ ] **Step 6: Banned-word grep, then the backend gate**

Stage the four files (`git add packages/core/bsi_core/alerts.py packages/core/bsi_core/crawl.py tests/unit/test_alerts.py tests/unit/test_http_fetch.py`) and run the banned-word grep from Global Constraints on `git diff --cached -U0`. Expected: no match. Then run the Backend gate from Global Constraints with `gate-task1.txt`. Expected: `gate exit 0`; the file ends with `1560 passed, 2 deselected` (1558 + 2) and the metrics coverage line at 100%. (`ruff format .` may reflow the new code; if it changed a file, re-stage it.)

- [ ] **Step 7: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/alerts.py packages/core/bsi_core/crawl.py tests/unit/test_alerts.py tests/unit/test_http_fetch.py && git commit -m "feat(alerts): sign() and an http_fetch headers keyword

sign() builds the X-BSI-Signature value (t=<unix>,v1=<hex HMAC-SHA256
over t.body>). http_fetch takes caller headers; Host, User-Agent and
Accept-Encoding are dropped from them by lower-cased name and merged
last, so the SSRF guard's pinned Host cannot be overridden.

<trailer>"
```

---

### Task 2: the column and the API

**Files:**
- Create: `migrations/versions/0022_brand_webhook_secret.py`
- Modify: `packages/core/bsi_core/models.py:134-135` (`Brand.webhook_url`)
- Modify: `apps/api/bsi_api/routers/brands.py:48-52` (types), `:68-75` (`BrandPatch`), `:78-86` (`BrandOut`), `:163-174` (`patch_brand`)
- Modify: `apps/web/openapi.json`, `apps/web/src/lib/schema.d.ts` (regenerated)
- Test: `tests/integration/test_api_alerts.py` (append)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: column `brand.webhook_secret text NULL`; `m.Brand.webhook_secret: str | None`; `m.Brand.has_webhook_secret -> bool` (property); `BrandPatch.webhook_secret`; `BrandOut.has_webhook_secret: bool`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_api_alerts.py`:

```python


SECRET = "s" * 32


def test_secret_is_write_only_and_shown_as_a_flag(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    r = client.patch(
        f"/v1/brands/{bid}", headers=org.headers, json={"webhook_secret": SECRET}
    )
    assert r.status_code == 200, r.text
    assert "webhook_secret" not in r.json()
    assert r.json()["has_webhook_secret"] is True
    with owner() as s:
        assert s.get(m.Brand, bid).webhook_secret == SECRET


@pytest.mark.parametrize("secret", ["s" * 31, " " + SECRET])
def test_a_short_or_padded_secret_is_rejected(
    client, make_org, make_brand, secret
):
    org = make_org()
    bid = make_brand(org)
    r = client.patch(
        f"/v1/brands/{bid}", headers=org.headers, json={"webhook_secret": secret}
    )
    assert r.status_code == 422, r.text


def test_clearing_the_url_also_clears_the_secret(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    client.patch(
        f"/v1/brands/{bid}",
        headers=org.headers,
        json={"webhook_url": "https://hooks.example.com/in", "webhook_secret": SECRET},
    )
    r = client.patch(
        f"/v1/brands/{bid}", headers=org.headers, json={"webhook_url": None}
    )
    assert r.status_code == 200 and r.json()["has_webhook_secret"] is False
    with owner() as s:
        assert s.get(m.Brand, bid).webhook_secret is None


def test_null_clears_only_the_secret(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    client.patch(
        f"/v1/brands/{bid}",
        headers=org.headers,
        json={"webhook_url": "https://hooks.example.com/in", "webhook_secret": SECRET},
    )
    r = client.patch(
        f"/v1/brands/{bid}", headers=org.headers, json={"webhook_secret": None}
    )
    assert r.status_code == 200
    assert r.json()["has_webhook_secret"] is False
    assert r.json()["webhook_url"] == "https://hooks.example.com/in"
    with owner() as s:
        assert s.get(m.Brand, bid).webhook_secret is None
```

- [ ] **Step 2: Run the file to verify the new tests fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q -p no:cacheprovider tests/integration/test_api_alerts.py 2>&1 | tail -3`
Expected: `5 failed, 12 passed`. `test_secret_is_write_only_and_shown_as_a_flag` fails on `"webhook_secret" not in r.json()`? No: pydantic ignores unknown fields, so the PATCH returns 200 and the first failing assertion is `r.json()["has_webhook_secret"]` → `KeyError`. The two 422 cases fail with `assert 200 == 422`. The two clearing tests fail with `KeyError: 'has_webhook_secret'`.

- [ ] **Step 3: Write the migration**

Create `migrations/versions/0022_brand_webhook_secret.py`:

```python
"""brand.webhook_secret (slice 32)"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("brand", sa.Column("webhook_secret", sa.Text()))


def downgrade() -> None:
    op.drop_column("brand", "webhook_secret")
```

- [ ] **Step 4: Add the column and property to the model**

In `packages/core/bsi_core/models.py`, replace

```python
    # One HTTPS URL each new alert is POSTed to; null = no delivery.
    webhook_url: Mapped[str | None]
```

with

```python
    # One HTTPS URL each new alert is POSTed to; null = no delivery.
    webhook_url: Mapped[str | None]
    # Shared with the receiver; read only by the worker when it signs a
    # delivery. Null = unsigned. Never returned by the API.
    webhook_secret: Mapped[str | None]

    @property
    def has_webhook_secret(self) -> bool:
        return self.webhook_secret is not None
```

- [ ] **Step 5: The API**

In `apps/api/bsi_api/routers/brands.py`, replace

```python
WebhookUrl = Annotated[
    str, Field(max_length=2000), AfterValidator(_webhook_url)
]
```

with

```python
def _webhook_secret(value: str) -> str:
    """The receiver's copy must match byte for byte."""
    if value.strip() != value:
        raise ValueError("no surrounding whitespace")
    return value


WebhookUrl = Annotated[
    str, Field(max_length=2000), AfterValidator(_webhook_url)
]
WebhookSecret = Annotated[
    str, Field(min_length=32, max_length=200), AfterValidator(_webhook_secret)
]
```

Replace

```python
    webhook_url: WebhookUrl | None = None
    report_logo_url: LogoUrl | None = None
```

with

```python
    webhook_url: WebhookUrl | None = None
    webhook_secret: WebhookSecret | None = None
    report_logo_url: LogoUrl | None = None
```

Replace

```python
    status: str
    webhook_url: str | None
    report_logo_url: str | None
```

with

```python
    status: str
    webhook_url: str | None
    has_webhook_secret: bool
    report_logo_url: str | None
```

Replace

```python
    if "webhook_url" in body.model_fields_set and body.webhook_url is None:
        # Pending alerts must not go to whatever URL is set next.
        c.s.execute(
```

with

```python
    if "webhook_url" in body.model_fields_set and body.webhook_url is None:
        brand.webhook_secret = None  # a secret without a URL is dead state
        # Pending alerts must not go to whatever URL is set next.
        c.s.execute(
```

- [ ] **Step 6: Run the file to verify it passes**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q -p no:cacheprovider tests/integration/test_api_alerts.py 2>&1 | tail -3`
Expected: `17 passed` (conftest's `alembic upgrade head` applies 0022 to `bsi_test` first).

- [ ] **Step 7: Regenerate the OpenAPI types**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gen 2>&1 | tail -3 && cd /Users/vineet/Downloads/ADK/bsi-platform && git diff --stat -- apps/web/openapi.json apps/web/src/lib/schema.d.ts`
Expected: both files changed; `grep -n "has_webhook_secret\|webhook_secret" apps/web/src/lib/schema.d.ts` shows `has_webhook_secret: boolean;` under `BrandOut` and `webhook_secret?: string | null;` under `BrandPatch`.

- [ ] **Step 8: Banned-word grep, then the backend gate**

Stage the six files (`git add migrations/versions/0022_brand_webhook_secret.py packages/core/bsi_core/models.py apps/api/bsi_api/routers/brands.py tests/integration/test_api_alerts.py apps/web/openapi.json apps/web/src/lib/schema.d.ts`) and run the banned-word grep on `git diff --cached -U0`. Expected: no match. Then the Backend gate with `gate-task2.txt`. Expected: `gate exit 0`; `1565 passed, 2 deselected` (1560 + 5).

- [ ] **Step 9: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add migrations/versions/0022_brand_webhook_secret.py packages/core/bsi_core/models.py apps/api/bsi_api/routers/brands.py tests/integration/test_api_alerts.py apps/web/openapi.json apps/web/src/lib/schema.d.ts && git commit -m "feat(brands): write-only webhook_secret, has_webhook_secret flag

Migration 0022 adds brand.webhook_secret. PATCH /v1/brands/{id} takes
webhook_secret (32-200 chars, no surrounding whitespace); BrandOut reports
has_webhook_secret only; clearing the URL clears the secret too.

<trailer>"
```

---

### Task 3: signing in the worker

**Files:**
- Modify: `apps/workers/bsi_workers/worker.py:8` (import), `:15` (import), `:103-112` (`Poster`), `:294-309` (`deliver_due_alerts`'s read and POST)
- Test: `tests/integration/test_worker.py` (`_Hook` at 905–914; the unpacking at 937–946; the three local fakes at 997, 1027, 1044; append a test)

**Interfaces:**
- Consumes: `bsi_core.alerts.sign` (Task 1); `http_fetch(headers=)` (Task 1); `m.Brand.webhook_secret` (Task 2).
- Produces: `Poster.__call__(..., headers: Mapping[str, str] | None = None)`; the worker passes `headers=` on every delivery.

- [ ] **Step 1: Widen the fakes and write the failing test**

In `tests/integration/test_worker.py`, replace the import line

```python
import json
from datetime import UTC, datetime, timedelta
```

with

```python
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
```

Replace

```python
    def __call__(self, url, ua, *, method, body, content_type):
        self.calls.append((url, ua, method, content_type, json.loads(body)))
        return Response(self.status, "", self.error)
```

with

```python
    def __call__(self, url, ua, *, method, body, content_type, headers=None):
        self.calls.append(
            (url, ua, method, content_type, json.loads(body), body, headers)
        )
        return Response(self.status, "", self.error)
```

Replace

```python
    (url, ua, method, ctype, body) = hook.calls[0]
    assert (url, ua, method, ctype) == (
        "https://hooks.example.com/in",
        WEBHOOK_UA,
        "POST",
        "application/json",
    )
```

with

```python
    (url, ua, method, ctype, body, _raw, headers) = hook.calls[0]
    assert (url, ua, method, ctype, headers) == (
        "https://hooks.example.com/in",
        WEBHOOK_UA,
        "POST",
        "application/json",
        None,  # no secret, no signature
    )
```

Replace each of the three local fakes' first line (R2; three occurrences, one in each of `test_no_transaction_is_open_during_the_webhook_post`, `test_one_failing_delivery_does_not_block_the_rest`, `test_a_delivery_that_fails_after_the_webhook_is_cleared_is_given_up`):

```python
    def fetch(url, ua, *, method, body, content_type):
```

with

```python
    def fetch(url, ua, *, method, body, content_type, headers=None):
```

Append at the end of the file:

```python


def test_deliver_signs_when_the_brand_has_a_secret(
    owner, make_org, make_brand
):
    org, bid = _hooked_brand(owner, make_org, make_brand)
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand).where(m.Brand.id == bid).values(webhook_secret="s" * 32)
        )
    _due_alert(owner, org, bid)
    hook = _Hook()
    assert deliver_due_alerts(fetch=hook) == 1
    (_url, _ua, _method, _ctype, _body, raw, headers) = hook.calls[0]
    t, v1 = headers["X-BSI-Signature"].split(",")
    assert t.startswith("t=") and v1.startswith("v1=")
    assert abs(time.time() - int(t[2:])) < 60
    want = hmac.new(
        b"s" * 32, t[2:].encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    assert v1[3:] == want
```

- [ ] **Step 2: Run the file to verify only the new test fails**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q -p no:cacheprovider tests/integration/test_worker.py 2>&1 | tail -3`
Expected: `1 failed, 42 passed`; the failure is `TypeError: 'NoneType' object is not subscriptable` at `headers["X-BSI-Signature"]` (the worker does not pass headers yet, so `_Hook` records its default `None`).

- [ ] **Step 3: Sign in the worker**

In `apps/workers/bsi_workers/worker.py`, replace

```python
from collections.abc import Callable
```

with

```python
from collections.abc import Callable, Mapping
```

Replace

```python
from bsi_core.alerts import payload
```

with

```python
from bsi_core.alerts import payload, sign
```

Replace

```python
        method: str,
        body: bytes,
        content_type: str,
    ) -> Response: ...
```

with

```python
        method: str,
        body: bytes,
        content_type: str,
        headers: Mapping[str, str] | None = None,
    ) -> Response: ...
```

Replace

```python
                url, body = (
                    brand.webhook_url,
                    json.dumps(
                        payload(alert, brand.name), default=str
                    ).encode(),
                )
            assert url is not None  # due_alert_deliveries() filtered on it
            resp = fetch(
                url,
                WEBHOOK_UA,
                method="POST",
                body=body,
                content_type="application/json",
            )
```

with

```python
                url, secret, body = (
                    brand.webhook_url,
                    brand.webhook_secret,
                    json.dumps(
                        payload(alert, brand.name), default=str
                    ).encode(),
                )
            assert url is not None  # due_alert_deliveries() filtered on it
            # Signed after the session closed: no transaction spans the POST.
            headers = (
                {"X-BSI-Signature": sign(secret, body, int(time.time()))}
                if secret
                else None
            )
            resp = fetch(
                url,
                WEBHOOK_UA,
                method="POST",
                body=body,
                content_type="application/json",
                headers=headers,
            )
```

- [ ] **Step 4: Run the file to verify it passes**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q -p no:cacheprovider tests/integration/test_worker.py 2>&1 | tail -3`
Expected: `43 passed`.

- [ ] **Step 5: Banned-word grep, then the backend gate**

Stage the two files (`git add apps/workers/bsi_workers/worker.py tests/integration/test_worker.py`) and run the banned-word grep on `git diff --cached -U0`. Expected: no match. Then the Backend gate with `gate-task3.txt`. Expected: `gate exit 0`; `1566 passed, 2 deselected` (1565 + 1).

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/workers/bsi_workers/worker.py tests/integration/test_worker.py && git commit -m "feat(worker): sign alert deliveries with X-BSI-Signature

deliver_due_alerts reads brand.webhook_secret in its existing tenant
read and, after the session closes, sends t=<unix>,v1=<hmac> when a
secret is set. No secret: the POST is exactly as before.

<trailer>"
```

---

### Task 4: the alerts page

**Files:**
- Modify: `apps/web/src/app/(app)/b/[id]/alerts/page.tsx:36-60`
- Modify: `apps/web/src/app/(app)/b/[id]/alerts/actions.ts:6-16`
- Modify: `apps/web/src/lib/format.ts:159-164` (`ALERT_NOTES`)
- Test: `apps/web/src/lib/format.test.ts:162-169`

**Interfaces:**
- Consumes: `Brand.has_webhook_secret` from the regenerated `schema.d.ts` (Task 2); `PATCH /brands/{id}` with `webhook_secret` (Task 2).
- Produces: nothing for later tasks.

- [ ] **Step 1: Write the failing test**

In `apps/web/src/lib/format.test.ts`, replace

```ts
  expect(alertNote("cleared")).toBe("Webhook cleared.");
  expect(alertNote("new")).toBe("Scan done; new alerts are listed below.");
```

with

```ts
  expect(alertNote("cleared")).toBe("Webhook cleared; any signing secret was removed.");
  expect(alertNote("secret_removed")).toBe("Signing secret removed; deliveries are unsigned.");
  expect(alertNote("new")).toBe("Scan done; new alerts are listed below.");
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/format.test.ts 2>&1 | tail -6`
Expected: 1 failed (`alertNote says what the alerts forms did`: expected "Webhook cleared." to be "Webhook cleared; any signing secret was removed.").

- [ ] **Step 3: The notes**

In `apps/web/src/lib/format.ts`, replace

```ts
  saved: "Webhook saved; new alerts are posted to it.",
  cleared: "Webhook cleared.",
```

with

```ts
  saved: "Webhook saved; new alerts are posted to it.",
  cleared: "Webhook cleared; any signing secret was removed.",
  secret_removed: "Signing secret removed; deliveries are unsigned.",
```

- [ ] **Step 4: The action**

In `apps/web/src/app/(app)/b/[id]/alerts/actions.ts`, replace

```ts
export async function setWebhook(form: FormData) {
  const id = String(form.get("brand_id"));
  const value = String(form.get("webhook_url") ?? "").trim();
  const clear = form.get("clear") === "1" || value === "";
  await api(`/brands/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ webhook_url: clear ? null : value }),
  });
  redirect(`/b/${id}/alerts?queued=${clear ? "cleared" : "saved"}`);
}
```

with

```ts
export async function setWebhook(form: FormData) {
  const id = String(form.get("brand_id"));
  const value = String(form.get("webhook_url") ?? "").trim();
  const clear = form.get("clear") === "1" || value === "";
  // Not trimmed: the API rejects surrounding whitespace, and a trimmed
  // paste would be a different secret from the receiver's copy.
  const secret = String(form.get("webhook_secret") ?? "");
  const clearSecret = form.get("clear_secret") === "1";
  const body: Record<string, string | null> = { webhook_url: clear ? null : value };
  if (clearSecret) body.webhook_secret = null;
  else if (secret !== "") body.webhook_secret = secret;
  await api(`/brands/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const note = clearSecret ? "secret_removed" : clear ? "cleared" : "saved";
  redirect(`/b/${id}/alerts?queued=${note}`);
}
```

- [ ] **Step 5: The page**

In `apps/web/src/app/(app)/b/[id]/alerts/page.tsx`, replace

```tsx
        <input
          type="url"
          name="webhook_url"
          pattern="https://.*"
          placeholder="https://hooks.slack.com/services/…"
          defaultValue={brand.webhook_url ?? ""}
          style={{ minWidth: 360 }}
        />
        <button className="primary">Save webhook</button>
        <button name="clear" value="1" formNoValidate>
          Clear
        </button>
      </form>
```

with

```tsx
        <input
          type="url"
          name="webhook_url"
          required
          pattern="https://.*"
          placeholder="https://hooks.slack.com/services/…"
          defaultValue={brand.webhook_url ?? ""}
          style={{ minWidth: 360 }}
        />
        <input
          type="password"
          name="webhook_secret"
          minLength={32}
          maxLength={200}
          autoComplete="off"
          placeholder="Signing secret (optional, 32+ characters)"
          style={{ minWidth: 280 }}
        />
        <span className="muted">
          {brand.has_webhook_secret ? "Signing on" : "Unsigned"}
        </span>
        <button className="primary">Save webhook</button>
        <button name="clear" value="1" formNoValidate>
          Clear
        </button>
        {brand.has_webhook_secret && (
          <button name="clear_secret" value="1" formNoValidate>
            Remove secret
          </button>
        )}
      </form>
```

Replace

```tsx
        alert comes from a single answer. Each new alert is posted to the
        webhook as JSON with a <code>text</code> field.
      </p>
```

with

```tsx
        alert comes from a single answer. Each new alert is posted to the
        webhook as JSON with a <code>text</code> field. With a signing
        secret set, each POST carries{" "}
        <code>X-BSI-Signature: t=&lt;unix seconds&gt;,v1=&lt;hex&gt;</code>,
        an HMAC-SHA256 with the secret over <code>t</code>, a dot, and the
        raw body; reject a <code>t</code> more than 5 minutes old.
      </p>
```

- [ ] **Step 6: Run the test to verify it passes, then the web gate**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/format.test.ts 2>&1 | tail -4`
Expected: all tests in the file pass. Then stage the four files (`cd /Users/vineet/Downloads/ADK/bsi-platform && git add "apps/web/src/app/(app)/b/[id]/alerts/page.tsx" "apps/web/src/app/(app)/b/[id]/alerts/actions.ts" apps/web/src/lib/format.ts apps/web/src/lib/format.test.ts`), run the banned-word grep on `git diff --cached -U0` (expected: no match), then the Web gate with `gate-task4-web.txt`. Expected: `web gate exit 0`; the file shows 43 tests passed (the count is unchanged: one test gained a line) and `Compiled successfully`.

- [ ] **Step 7: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add "apps/web/src/app/(app)/b/[id]/alerts/page.tsx" "apps/web/src/app/(app)/b/[id]/alerts/actions.ts" apps/web/src/lib/format.ts apps/web/src/lib/format.test.ts && git commit -m "feat(web): signing secret on the alerts page

A password input, a Signing on/Unsigned span and a Remove secret button
beside the webhook URL, which is now required to save. The action sends
webhook_secret as typed, omits it when empty, and nulls it on Remove.

<trailer>"
```

---

## Self-review (plan vs spec)

- Spec coverage: §1 → Task 2; §2 → Tasks 1 and 3; §3 → Task 4; §4 → the tests in Tasks 1–4; §5 (docs, dev migration, live check) is post-merge work done by the controller, not a task.
- Departures from the spec, all wording or layout only:
  1. §4 names the unit test's spoof keys `"Host"`, `"user-agent"`, `"ACCEPT-ENCODING"`; the plan uses exactly those.
  2. §3 says the status span is "beside" the secret input; the plan places it after the input and before the buttons.
  3. The plan adds `style={{ minWidth: 280 }}` to the secret input (the URL input has `minWidth: 360`); the spec does not mention a width.
  4. The migration file's docstring is `"""brand.webhook_secret (slice 32)"""`, matching 0021's style; the spec gives no docstring.
  5. Task 2 Step 2's expected failure for the first test is a `KeyError`, not the write-only assertion: pydantic ignores the unknown field, so the PATCH succeeds. The spec does not state the red result for the API tests.
  6. Each task runs the full backend gate once (Tasks 1–3) or the web gate once (Task 4), as the Global Constraints say; the spec's "both gates, run by the controller" is in addition.
- Placeholder scan: none (`<trailer>` is the Global Constraints' commit-trailer rule, and `<workspace>` is the SDD workspace path the task brief supplies).
- Type consistency: `sign(secret: str, body: bytes, now: int) -> str` (Task 1) is called as `sign(secret, body, int(time.time()))` (Task 3); `headers: Mapping[str, str] | None` matches in `http_fetch`, `Poster` and the fakes; `has_webhook_secret` is the same name in the model, `BrandOut`, the schema and the page.
