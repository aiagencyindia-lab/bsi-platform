"""audit_entity from canned responses. Nothing here touches the network."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from bsi_core import crawl
from bsi_core.crawl import BROWSER_UA, Response
from bsi_core.entity import (
    EXPECTED,
    FAMILIES,
    SEVERITY,
    SIGNAL,
    audit_entity,
)

HOME_CODES = {
    "org_name_mismatch",
    "org_url_mismatch",
    "org_logo_missing",
    "org_sameas_missing",
    "website_schema_missing",
    "title_brand_missing",
    "about_missing",
}
ORG = {
    "@type": "Organization",
    "name": "Acme, Inc.",
    "url": "https://www.acme.com/",
    "logo": {"@type": "ImageObject", "url": "https://acme.com/logo.png"},
    "sameAs": [
        "https://x.com/AcmeHQ",
        "https://www.linkedin.com/company/acme/",
    ],
}
SITE = {"@type": "WebSite", "url": "https://acme.com/"}


def home(
    org=ORG,
    extra=(SITE,),
    title="Acme | Rockets",
    links=('<a href="/about-us">About</a>',),
):
    graph = [n for n in (org, *extra) if n is not None]
    ld = json.dumps({"@context": "https://schema.org", "@graph": graph})
    return (
        f"<html><head><title>{title}</title>"
        f'<script type="application/ld+json">{ld}</script></head>'
        f"<body>{''.join(links)}</body></html>"
    )


def org_home(drop=(), **kv):
    org = {k: v for k, v in {**ORG, **kv}.items() if k not in drop}
    return Response(200, home(org=org))


def fetcher(home_resp=None, search=None, entities=None):
    """A fetch that answers the homepage and the two Wikidata calls."""
    calls = []

    def fetch(url, ua):
        calls.append((url, ua))
        if url == "https://acme.com/":
            return home_resp or Response(200, home())
        action = parse_qs(urlsplit(url).query).get("action", [""])[0]
        if action == "wbsearchentities":
            return search or Response(200, json.dumps({"search": []}))
        if action == "wbgetentities":
            return entities or Response(200, json.dumps({"entities": {}}))
        raise AssertionError(f"unexpected fetch {url}")

    fetch.calls = calls
    return fetch


def run(fetch, name="Acme", aliases=("Acme Inc",), pause=0.0):
    return audit_entity(
        "acme.com", name, list(aliases), ["acme.com"], fetch, pause=pause
    )


def verdicts(audit):
    return {c.code: c.ok for c in audit.checks}


def home_verdicts(audit):
    return {k: v for k, v in verdicts(audit).items() if k in HOME_CODES}


def test_a_consistent_homepage_passes_every_home_check():
    f = fetcher()
    a = run(f)
    assert home_verdicts(a) == dict.fromkeys(HOME_CODES, True)
    assert f.calls[0] == ("https://acme.com/", BROWSER_UA)
    about = next(c for c in a.checks if c.code == "about_missing")
    assert about.observed == "https://acme.com/about-us"


@pytest.mark.parametrize(
    ("code", "resp"),
    [
        ("org_name_mismatch", org_home(name="Acme Rockets Ltd")),
        ("org_url_mismatch", org_home(url="https://acme-shop.net/")),
        ("org_logo_missing", org_home(drop=("logo",))),
        ("org_sameas_missing", org_home(sameAs=[])),
        ("website_schema_missing", Response(200, home(extra=()))),
        ("title_brand_missing", Response(200, home(title="Rockets"))),
        (
            "about_missing",
            Response(
                200, home(links=('<a href="https://other.com/about">x</a>',))
            ),
        ),
    ],
)
def test_each_home_check_fails_alone(code, resp):
    got = home_verdicts(run(fetcher(home_resp=resp)))
    assert {k for k, ok in got.items() if not ok} == {code}


def test_observed_values_name_what_was_found():
    a = run(fetcher(home_resp=org_home(name="Acme Rockets Ltd", drop=("url",))))
    obs = {c.code: c.observed for c in a.checks}
    assert obs["org_name_mismatch"] == "Acme Rockets Ltd"
    assert obs["org_url_mismatch"] == "absent"


def test_names_normalise_case_punctuation_and_unicode():
    org = {**ORG, "name": "CAFÉ NOIR!"}
    f = fetcher(home_resp=Response(200, home(org=org, title="café-noir shop")))
    got = verdicts(run(f, name="Café Noir", aliases=()))
    assert got["org_name_mismatch"] and got["title_brand_missing"]


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://www.acme.com/", True),
        ("http://acme.com", True),
        ("https://shop.acme.com/x", True),
        ("https://acme.com.evil.net/", False),
        ("", False),
    ],
)
def test_org_url_must_be_a_declared_domain(url, ok):
    got = verdicts(run(fetcher(home_resp=org_home(url=url))))
    assert got["org_url_mismatch"] is ok


@pytest.mark.parametrize(
    ("logo", "ok"),
    [
        ("https://acme.com/l.png", True),
        ({"@id": "https://acme.com/#logo"}, True),
        ([{"url": "https://acme.com/l.png"}], True),
        ("", False),
        ([], False),
        ({"@type": "ImageObject"}, False),
    ],
)
def test_logo_accepts_every_schema_org_shape(logo, ok):
    got = verdicts(run(fetcher(home_resp=org_home(logo=logo))))
    assert got["org_logo_missing"] is ok


def test_sameas_may_be_a_single_string():
    got = verdicts(run(fetcher(home_resp=org_home(sameAs="https://x.com/a"))))
    assert got["org_sameas_missing"]


@pytest.mark.parametrize("kind", ["Corporation", ["Organization", "Brand"]])
def test_organization_subtypes_count(kind):
    got = home_verdicts(run(fetcher(home_resp=org_home(**{"@type": kind}))))
    assert got == dict.fromkeys(HOME_CODES, True)


def test_no_organization_skips_the_org_rows_only():
    got = verdicts(run(fetcher(home_resp=Response(200, home(org=None)))))
    assert not [c for c in got if c.startswith("org_")]
    assert {"website_schema_missing", "title_brand_missing"} <= set(got)
    assert "about_missing" in got


def test_a_malformed_block_does_not_hide_a_good_one():
    body = home().replace(
        "<script", '<script type="application/ld+json">{bad</script><script', 1
    )
    got = home_verdicts(run(fetcher(home_resp=Response(200, body))))
    assert got == dict.fromkeys(HOME_CODES, True)


def test_an_unreachable_homepage_emits_no_home_rows():
    a = run(fetcher(home_resp=Response(500, "")))
    assert not home_verdicts(a)


@pytest.mark.parametrize(
    ("href", "ok"),
    [
        ("/about", True),
        ("about-us", True),
        ("https://www.acme.com/Company/team", True),
        ("https://other.com/about", False),
        ("mailto:hello@acme.com", False),
        ("http://[::1", False),
    ],
)
def test_about_link_must_stay_on_the_brand_host(href, ok):
    resp = Response(200, home(links=(f'<a href="{href}">x</a>',)))
    assert verdicts(run(fetcher(home_resp=resp)))["about_missing"] is ok


def test_constants_are_consistent():
    assert set(EXPECTED) == set(SEVERITY) == FAMILIES
    assert set(SEVERITY.values()) <= {"high", "medium", "low"}
    assert all(v.endswith(SIGNAL) for v in EXPECTED.values())
    assert SIGNAL == "This is an optimisation signal, not a promised outcome."
    # The rule routes by family: entity and crawl must never share one.
    assert not FAMILIES & set(crawl.SEVERITY)
    assert len(FAMILIES) == 11
