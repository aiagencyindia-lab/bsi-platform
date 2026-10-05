"""DataForSEO: one live Google first page per call (slice 37, PRD F09).

serp() never raises: a failure is a SerpPage with a short error code.
Only a POST is made, so the Basic header never follows a redirect."""

import base64
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..crawl import Response, http_fetch

URL = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"
SERP_UA = "bsi-platform-serp/1.0"
SERP_CAP_BYTES = 4 * 1024 * 1024
SERP_TIMEOUT_SECONDS = 120  # DataForSEO's advice for live SERP calls
TIMEOUT_MICROS = 4_000  # one call's expected price, about $0.004
# ponytail: a static table of the provider's location names, one line
# per country as locales arrive; an unknown country is error "location".
LOCATIONS = {"IN": "India"}
OK, NO_RESULTS = 20000, 40102
ERRORS = {
    40100: "auth",
    40104: "unverified",
    40200: "funds",
    40201: "paused",
    40202: "rate",
    40210: "funds",
}
MAX_STATUS = 99_999  # documented codes have five digits
# What an undocumented body can raise while it is decoded or read.
UNREADABLE = (
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    IndexError,
    OverflowError,
    RecursionError,
)


class SerpFetch(Protocol):
    def __call__(
        self,
        url: str,
        user_agent: str,
        *,
        method: str,
        body: bytes,
        content_type: str,
        cap: int,
        headers: Mapping[str, str] | None = None,
        deadline_seconds: float | None = None,
        phase_seconds: float | None = None,
    ) -> Response: ...


@dataclass
class SerpItem:
    position: int  # rank_absolute; 0 when the provider gives none
    item_type: str  # the provider's `type`
    url: str
    domain: str
    title: str
    sitelinks: bool  # an organic item with a non-empty `links`


@dataclass
class SerpPage:
    items: list[SerpItem] = field(default_factory=list)
    cost_micros: int = 0
    error: str | None = None


def _code(status: object) -> str | None:
    """None for a success status, else the short error code."""
    if status in (OK, NO_RESULTS):
        return None
    if isinstance(status, int) and status in ERRORS:
        return ERRORS[status]
    return f"provider_{status}"


def _status(value: object) -> int | None:
    """A provider status code, or None: only a plain integer (not a
    bool) from 0 to MAX_STATUS counts, so a stored error stays short."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= MAX_STATUS else None


MAX_COST_USD = 1  # per call; the expected price is about $0.004


def _micros(cost: object) -> int:
    """The cost in micros. A missing or non-number cost is 0. A bool, a
    negative number, NaN, or one above MAX_COST_USD raises ValueError."""
    if isinstance(cost, bool):
        raise ValueError("cost is a bool")
    if not isinstance(cost, int | float):
        return 0
    if not 0 <= cost <= MAX_COST_USD:
        raise ValueError("cost out of range")
    return round(cost * 1_000_000)


def _error_micros(cost: object) -> int:
    """The cost of an answer that carries an error code: a bad cost is 0,
    so the code is kept."""
    try:
        return _micros(cost)
    except ValueError:
        return 0


def _item(raw: Mapping[str, Any]) -> SerpItem:
    rank = raw.get("rank_absolute")
    kind = str(raw.get("type") or "")
    return SerpItem(
        position=rank if isinstance(rank, int) else 0,
        item_type=kind,
        url=str(raw.get("url") or ""),
        domain=str(raw.get("domain") or ""),
        title=str(raw.get("title") or ""),
        sitelinks=kind == "organic" and bool(raw.get("links")),
    )


def _parse(doc: Any) -> SerpPage:
    """The page in a decoded response. Raises on an undocumented shape,
    or on a success whose cost is bad. An error answer keeps its code; a
    bad cost there is 0. An unreadable item returns `json` with the cost."""
    if not isinstance(doc, dict):
        raise ValueError("not an object")
    top = _status(doc["status_code"])
    if top is None:
        raise ValueError("status_code is not a status")
    tasks = doc.get("tasks") or []
    if not tasks:
        error = _code(top)
        if error is None:
            raise ValueError("no task")
        return SerpPage(cost_micros=_error_micros(doc.get("cost")), error=error)
    task = tasks[0]
    # The top-level status first, then the task's (spec, The adapter).
    error = _code(top)
    if error is None:
        status = _status(task.get("status_code"))
        error = "json" if status is None else _code(status)
    if error is not None:
        return SerpPage(
            cost_micros=_error_micros(task.get("cost")), error=error
        )
    cost = _micros(task.get("cost"))  # a bad cost on a success raises: json
    try:
        items = [
            _item(raw)
            for result in task.get("result") or []
            for raw in result.get("items") or []
        ]
    except UNREADABLE:
        # The task's cost is known by now; keep it with the error.
        return SerpPage(cost_micros=cost, error="json")
    return SerpPage(items, cost)


def _refused(resp: Response) -> SerpPage:
    """A non-2xx answer: the provider's error code from its body when it
    has one; otherwise `http`. `truncated` is not consulted: a cut body
    fails to decode, which is also `http`."""
    try:
        page = _parse(json.loads(resp.body))
    except UNREADABLE:
        return SerpPage(error="http")
    if page.error in (None, "json"):
        return SerpPage(error="http")
    return SerpPage(cost_micros=page.cost_micros, error=page.error)


def serp(
    query: str,
    country: str,
    language: str,
    *,
    login: str,
    password: str,
    fetch: SerpFetch = http_fetch,
) -> SerpPage:
    """Google's first page for `query` in one locale: desktop, live mode,
    with an asynchronously loaded AI Overview included."""
    if not login or not password:
        return SerpPage(error="serp_not_configured")
    location = LOCATIONS.get(country.upper())
    if location is None:
        return SerpPage(error="location")
    task = {
        "keyword": query,
        "location_name": location,
        "language_code": language,
        "device": "desktop",
        "depth": 10,
        "load_async_ai_overview": True,
    }
    token = base64.b64encode(f"{login}:{password}".encode()).decode()
    resp = fetch(
        URL,
        SERP_UA,
        method="POST",
        body=json.dumps([task]).encode(),
        content_type="application/json",
        cap=SERP_CAP_BYTES,
        headers={"Authorization": f"Basic {token}"},
        deadline_seconds=SERP_TIMEOUT_SECONDS,
        phase_seconds=SERP_TIMEOUT_SECONDS,
    )
    if not resp.ok:
        if resp.status == 0 and (resp.error or "").startswith("ReadTimeout"):
            # Sent but not answered in time: the provider may bill it.
            return SerpPage(cost_micros=TIMEOUT_MICROS, error="timeout")
        return _refused(resp)
    if resp.truncated:
        return SerpPage(error="truncated")
    try:
        return _parse(json.loads(resp.body))
    except UNREADABLE:
        return SerpPage(error="json")
