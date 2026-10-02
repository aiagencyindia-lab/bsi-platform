import base64
import json

import pytest
from bsi_core.crawl import Response
from bsi_core.providers.dataforseo import (
    SERP_CAP_BYTES,
    SERP_UA,
    URL,
    SerpItem,
    SerpPage,
    serp,
)

ITEMS = [
    {"type": "knowledge_graph", "rank_absolute": 1, "title": "Walkaroo"},
    {
        "type": "organic",
        "rank_absolute": 2,
        "domain": "walkaroo.in",
        "url": "https://walkaroo.in/",
        "title": "Walkaroo footwear",
        "links": [{"type": "link_element", "url": "https://walkaroo.in/men"}],
    },
    {
        "type": "organic",
        "rank_absolute": 3,
        "domain": "www.amazon.in",
        "url": "https://www.amazon.in/walkaroo",
        "title": "Walkaroo on Amazon",
        "links": None,
    },
    {"type": "people_also_ask", "rank_absolute": 4},
]


def body(items=None, cost=0.004, status=20000, task_status=20000) -> str:
    """A response in the documented shape: one task, one result."""
    task = {
        "status_code": task_status,
        "cost": cost,
        "result": [{"items": ITEMS if items is None else items}],
    }
    return json.dumps({"status_code": status, "cost": cost, "tasks": [task]})


class Fetch:
    """A fake http_fetch: records each call, repeats its last response."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, user_agent, **kw):
        self.calls.append((url, user_agent, kw))
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


def _serp(fetch, country="IN", login="me", password="pw"):
    return serp(
        "walkaroo", country, "en", login=login, password=password, fetch=fetch
    )


def test_a_page_is_parsed_into_items():
    page = _serp(Fetch(Response(200, body())))
    assert (page.error, page.cost_micros) == (None, 4_000)
    assert page.items == [
        SerpItem(1, "knowledge_graph", "", "", "Walkaroo", False),
        SerpItem(
            2,
            "organic",
            "https://walkaroo.in/",
            "walkaroo.in",
            "Walkaroo footwear",
            True,
        ),
        SerpItem(
            3,
            "organic",
            "https://www.amazon.in/walkaroo",
            "www.amazon.in",
            "Walkaroo on Amazon",
            False,
        ),
        SerpItem(4, "people_also_ask", "", "", "", False),
    ]


def test_the_request_is_one_live_desktop_task_with_basic_auth():
    fetch = Fetch(Response(200, body()))
    _serp(fetch, country="in")
    [(url, user_agent, kw)] = fetch.calls
    assert (url, user_agent) == (URL, SERP_UA)
    assert kw["method"] == "POST"
    assert kw["content_type"] == "application/json"
    assert kw["cap"] == SERP_CAP_BYTES
    assert json.loads(kw["body"]) == [
        {
            "keyword": "walkaroo",
            "location_name": "India",
            "language_code": "en",
            "device": "desktop",
            "depth": 10,
            "load_async_ai_overview": True,
        }
    ]
    token = base64.b64encode(b"me:pw").decode()
    assert kw["headers"] == {"Authorization": f"Basic {token}"}


def test_no_search_results_is_a_success_with_no_items():
    task = {"status_code": 40102, "cost": 0.002, "result": None}
    raw = json.dumps({"status_code": 20000, "cost": 0.002, "tasks": [task]})
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 2_000, None)


ERROR_CODES = [
    (40100, "auth"),
    (40200, "funds"),
    (40210, "funds"),
    (40202, "rate"),
    (50000, "provider_50000"),
]


@pytest.mark.parametrize(("status", "code"), ERROR_CODES)
def test_a_top_level_error_status_is_its_code(status, code):
    raw = json.dumps({"status_code": status, "cost": 0, "tasks": None})
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, code)


@pytest.mark.parametrize(("status", "code"), ERROR_CODES)
def test_a_task_level_error_is_its_code_and_keeps_the_cost(status, code):
    page = _serp(Fetch(Response(200, body(task_status=status))))
    assert page == SerpPage([], 4_000, code)


@pytest.mark.parametrize(
    "response", [Response(0, error="timeout"), Response(500, "oops")]
)
def test_an_http_failure_is_http(response):
    assert _serp(Fetch(response)) == SerpPage([], 0, "http")


def test_a_cut_body_is_truncated():
    cut = Response(200, body()[:50], truncated=True)
    assert _serp(Fetch(cut)) == SerpPage([], 0, "truncated")


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        '{"tasks": []}',
        '{"status_code": 20000}',
        '{"status_code": "x"}',
    ],
)
def test_an_unreadable_body_is_json(raw):
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "json")


@pytest.mark.parametrize(("login", "password"), [("", "pw"), ("me", "")])
def test_missing_credentials_make_no_call(login, password):
    fetch = Fetch(Response(200, body()))
    # The credential check comes before the country check.
    page = _serp(fetch, country="US", login=login, password=password)
    assert page == SerpPage([], 0, "serp_not_configured")
    assert fetch.calls == []


def test_an_unknown_country_makes_no_call():
    fetch = Fetch(Response(200, body()))
    assert _serp(fetch, country="US") == SerpPage([], 0, "location")
    assert fetch.calls == []


def test_an_infinite_cost_is_json():
    raw = body(cost=1e400)  # json.dumps writes Infinity; loads reads inf
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "json")


def test_an_unreadable_item_is_json_and_keeps_the_cost():
    raw = body(items=[1])
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 4_000, "json")


def test_deeply_nested_json_is_json():
    raw = "[" * 200_000 + "]" * 200_000
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "json")
