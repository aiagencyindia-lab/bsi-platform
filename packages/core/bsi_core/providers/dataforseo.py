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
# ponytail: a static table of the provider's location names, one line
# per country as locales arrive; an unknown country is error "location".
LOCATIONS = {"IN": "India"}
OK, NO_RESULTS = 20000, 40102
ERRORS = {40100: "auth", 40200: "funds", 40210: "funds", 40202: "rate"}


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


def _micros(cost: object) -> int:
    return round(cost * 1_000_000) if isinstance(cost, int | float) else 0


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
    """The page in a decoded response; raises on an undocumented shape."""
    if not isinstance(doc, dict):
        raise ValueError("not an object")
    top = doc["status_code"]
    if not isinstance(top, int):
        raise ValueError("status_code is not a number")
    tasks = doc.get("tasks") or []
    if not tasks:
        error = _code(top)
        if error is None:
            raise ValueError("no task")
        return SerpPage(cost_micros=_micros(doc.get("cost")), error=error)
    task = tasks[0]
    cost = _micros(task.get("cost"))
    # The top-level status first, then the task's (spec, The adapter).
    error = _code(top) or _code(task["status_code"])
    if error is not None:
        return SerpPage(cost_micros=cost, error=error)
    items = [
        _item(raw)
        for result in task.get("result") or []
        for raw in result.get("items") or []
    ]
    return SerpPage(items, cost)


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
    )
    if not resp.ok:
        return SerpPage(error="http")
    if resp.truncated:
        return SerpPage(error="truncated")
    try:
        return _parse(json.loads(resp.body))
    except (ValueError, TypeError, KeyError, AttributeError, IndexError):
        return SerpPage(error="json")
