"""audit_entity from canned responses. Nothing here touches the network."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from bsi_core import crawl, entity
from bsi_core.crawl import BROWSER_UA, Response
from bsi_core.entity import (
    EXPECTED,
    FAMILIES,
    SEVERITY,
    SIGNAL,
    WIKIDATA_UA,
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
    """A fetch that answers the homepage, the Wikidata search and the
    SPARQL query."""
    calls = []

    def fetch(url, ua):
        calls.append((url, ua))
        if url == "https://acme.com/":
            return home_resp or Response(200, home())
        if urlsplit(url).hostname == "query.wikidata.org":
            return entities or sparql({})
        action = parse_qs(urlsplit(url).query).get("action", [""])[0]
        if action == "wbsearchentities":
            return search or Response(200, json.dumps({"search": []}))
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
        ("/en-US/about/", True),
        ("/en_gb/company", True),
        ("/shop/about", False),
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


MATCH_PROPS = {
    "P856": ["http://www.acme.com"],
    "P154": ["Acme logo.svg"],
    "P2002": ["AcmeHQ"],
    "P4264": ["acme"],
}


def item(label="Acme Inc", drop=(), mul="", **props):
    p = {k: v for k, v in {**MATCH_PROPS, **props}.items() if k not in drop}
    return {"label": label, "mul": mul, **p}


def binding(qid, it):
    """One SPARQL result row, shaped as query.wikidata.org answers."""
    b = {
        "item": {
            "type": "uri",
            "value": f"http://www.wikidata.org/entity/{qid}",
        },
        "P154": {"type": "literal", "value": str(len(it.get("P154", [])))},
    }
    if it["label"]:
        b["label"] = {"xml:lang": "en", "type": "literal", "value": it["label"]}
    if it["mul"]:
        b["mul"] = {"xml:lang": "mul", "type": "literal", "value": it["mul"]}
    # query.wikidata.org leaves out an aggregate with no values at all.
    for p in ("P856", *entity.SOCIAL_PROPS):
        if it.get(p):
            b[p] = {"type": "literal", "value": "\t".join(it[p])}
    return b


def sparql(items):
    rows = [binding(q, it) for q, it in items.items()]
    return Response(200, json.dumps({"results": {"bindings": rows}}))


IMPOSTOR = item(label="Acme", P856=["https://acme.org/"])
SEARCH = Response(
    200,
    json.dumps(
        {
            "search": [
                {"id": "Q1", "label": "Acme"},
                {"id": "Q2", "label": "Acme Inc"},
            ]
        }
    ),
)


def ents(match=None, **more):
    return sparql({"Q1": IMPOSTOR, "Q2": match or item(), **more})


def wiki(**kw):
    """A fetcher with a domain-verified Wikidata match by default."""
    kw.setdefault("search", SEARCH)
    kw.setdefault("entities", ents())
    return fetcher(**kw)


WIKI_CODES = {
    "wikidata_missing",
    "wikidata_name_mismatch",
    "wikidata_logo_missing",
    "social_links_conflict",
}


def test_a_consistent_brand_passes_every_check():
    f = wiki()
    a = run(f)
    assert verdicts(a) == dict.fromkeys(SEVERITY, True)
    assert a.fetches == 3
    assert [ua for _, ua in f.calls] == [BROWSER_UA, WIKIDATA_UA, WIKIDATA_UA]
    search = parse_qs(urlsplit(f.calls[1][0]).query)
    assert search["action"] == ["wbsearchentities"]
    assert search["search"] == ["Acme"]
    got = urlsplit(f.calls[2][0])
    assert (got.scheme, got.hostname, got.path) == (
        "https",
        "query.wikidata.org",
        "/sparql",
    )
    q = parse_qs(got.query)
    assert q["format"] == ["json"]
    assert "VALUES ?item { wd:Q1 wd:Q2 }" in q["query"][0]
    obs = {c.code: (c.observed, c.url) for c in a.checks}
    # The impostor comes first in search order; its P856 is acme.org.
    assert obs["wikidata_missing"] == (
        "Q2: Acme Inc",
        "https://www.wikidata.org/wiki/Q2",
    )
    assert obs["social_links_conflict"][0] == "2 profiles agree"


@pytest.mark.parametrize(
    ("code", "kw"),
    [
        (
            "wikidata_name_mismatch",
            {"entities": ents(item(label="Acme Rockets"))},
        ),
        ("wikidata_logo_missing", {"entities": ents(item(drop=("P154",)))}),
        ("social_links_conflict", {"entities": ents(item(P2002=["acme_x"]))}),
    ],
)
def test_each_wikidata_check_fails_alone(code, kw):
    got = verdicts(run(wiki(**kw)))
    assert {k for k, ok in got.items() if not ok} == {code}


def test_no_domain_verified_candidate_is_wikidata_missing_only():
    a = run(wiki(entities=ents(item(P856=["https://acme.org"]))))
    got = {k: v for k, v in verdicts(a).items() if k in WIKI_CODES}
    assert got == {"wikidata_missing": False}
    miss = next(c for c in a.checks if c.code == "wikidata_missing")
    assert miss.observed == "candidates: Q1 Acme, Q2 Acme Inc"
    assert miss.url == "https://www.wikidata.org/w/index.php?search=Acme"


def test_empty_search_is_missing_without_a_second_call():
    f = wiki(search=Response(200, json.dumps({"search": []})))
    a = run(f)
    got = {c.code: (c.ok, c.observed) for c in a.checks if c.code in WIKI_CODES}
    assert got == {"wikidata_missing": (False, "no search results")}
    assert a.fetches == 2


@pytest.mark.parametrize(
    ("kw", "fetches"),
    [
        ({"search": Response(500, "")}, 2),
        ({"search": Response(0, "", "ConnectError('x')")}, 2),
        ({"search": Response(200, "<html>")}, 2),
        ({"search": Response(200, json.dumps({"error": {"code": "x"}}))}, 2),
        ({"search": Response(200, json.dumps({"search": [{"x": 1}]}))}, 2),
        ({"entities": Response(503, "")}, 3),
        ({"entities": Response(200, "not json")}, 3),
        ({"entities": Response(200, json.dumps({"results": {}}))}, 3),
        (
            {
                "entities": Response(
                    200, json.dumps({"results": {"bindings": [{"item": 1}]}})
                )
            },
            3,
        ),
    ],
)
def test_an_unreadable_wikidata_answer_skips_its_checks(kw, fetches, caplog):
    a = run(wiki(**kw))
    assert not WIKI_CODES & set(verdicts(a))
    assert a.fetches == fetches
    assert HOME_CODES <= set(verdicts(a))  # the home rows still stand
    # Skipped, but not silently.
    assert "acme.com" in caplog.text


def test_search_ids_that_are_not_item_ids_stay_out_of_the_query():
    hits = [
        {"id": "Q1 } ; DROP", "label": "x"},
        {"id": "P31", "label": "y"},
        {"id": "Q2", "label": "Acme Inc"},
    ]
    f = wiki(search=Response(200, json.dumps({"search": hits})))
    a = run(f)
    query = parse_qs(urlsplit(f.calls[2][0]).query)["query"][0]
    assert "VALUES ?item { wd:Q2 }" in query
    assert "DROP" not in query and "P31" not in query
    miss = next(c for c in a.checks if c.code == "wikidata_missing")
    assert (miss.ok, miss.observed) == (True, "Q2: Acme Inc")


def test_only_invalid_ids_read_as_no_search_results():
    hits = [{"id": "P31", "label": "y"}, {"id": "Q1\n", "label": "z"}]
    f = wiki(search=Response(200, json.dumps({"search": hits})))
    a = run(f)
    got = {c.code: (c.ok, c.observed) for c in a.checks if c.code in WIKI_CODES}
    assert got == {"wikidata_missing": (False, "no search results")}
    assert a.fetches == 2


@pytest.mark.parametrize(
    ("q1_site", "q2_site"),
    [
        # A product page on the brand's domain comes first in search
        # order; the item whose site is the domain root is the brand.
        ("https://acme.com/rockets", "https://acme.com/"),
        # No root candidate: the first domain-verified one still wins
        # over a namesake elsewhere.
        ("https://acme.org/", "https://acme.com/about"),
        # The exact host beats a subdomain, even the subdomain's root.
        ("https://gov.acme.com/", "https://acme.com/about"),
        ("https://acme.com/about", "https://acme.com/"),
        ("https://gov.acme.com/about", "https://gov.acme.com/"),
    ],
)
def test_the_exact_host_root_item_wins_the_match(q1_site, q2_site):
    product = item(label="Acme Rockets", P856=[q1_site])
    entities = sparql({"Q1": product, "Q2": item(P856=[q2_site])})
    a = run(wiki(entities=entities))
    miss = next(c for c in a.checks if c.code == "wikidata_missing")
    assert (miss.ok, miss.observed) == (True, "Q2: Acme Inc")


def test_equal_sites_keep_search_order():
    hits = [{"id": "Q2", "label": "Acme Inc"}, {"id": "Q1", "label": "Acme"}]
    f = wiki(
        search=Response(200, json.dumps({"search": hits})),
        entities=sparql({"Q1": item(label="Acme"), "Q2": item()}),
    )
    miss = next(c for c in run(f).checks if c.code == "wikidata_missing")
    assert miss.observed == "Q2: Acme Inc"


@pytest.mark.parametrize(
    ("label", "mul", "ok", "observed"),
    [
        # An item with only a "default for all languages" label.
        ("", "Acme Inc", True, "Q2: Acme Inc"),
        # English wins when both exist.
        ("Acme Rockets", "Acme Inc", False, "Q2: Acme Rockets"),
        ("", "", False, "Q2: no English label"),
    ],
)
def test_the_mul_label_stands_in_for_english(label, mul, ok, observed):
    f = wiki(entities=ents(item(label=label, mul=mul)))
    a = run(f)
    c = next(c for c in a.checks if c.code == "wikidata_name_mismatch")
    assert (c.ok, c.observed) == (ok, observed)
    query = parse_qs(urlsplit(f.calls[2][0]).query)["query"][0]
    assert 'LANG(?mul_) = "mul"' in query


def test_wikidata_runs_when_the_homepage_is_down():
    a = run(wiki(home_resp=Response(500, "")))
    assert set(verdicts(a)) == WIKI_CODES
    assert a.fetches == 3


@pytest.mark.parametrize(
    ("same_as", "props", "observed"),
    [
        (
            [*ORG["sameAs"], "https://instagram.com/acme"],
            {},
            "on Wikidata only: none; on site only: instagram.com/acme",
        ),
        (
            ORG["sameAs"],
            {"P2013": ["Acme"]},
            "on Wikidata only: facebook.com/acme; on site only: none",
        ),
    ],
)
def test_social_conflict_in_each_direction(same_as, props, observed):
    a = run(
        wiki(home_resp=org_home(sameAs=same_as), entities=ents(item(**props)))
    )
    c = next(c for c in a.checks if c.code == "social_links_conflict")
    assert (c.ok, c.observed) == (False, observed)


@pytest.mark.parametrize(
    ("same_as", "drop"),
    [
        (["https://en.wikipedia.org/wiki/Acme"], ()),
        (ORG["sameAs"], ("P2002", "P4264")),
    ],
)
def test_no_conflict_when_one_side_has_no_socials(same_as, drop):
    f = wiki(home_resp=org_home(sameAs=same_as), entities=ents(item(drop=drop)))
    c = next(c for c in run(f).checks if c.code == "social_links_conflict")
    assert c.ok
    assert c.observed.startswith("nothing to compare")


def test_youtube_is_left_out_of_the_social_comparison():
    # sameAs holds youtube.com/@handle, P2397 a channel id: never equal.
    same_as = [*ORG["sameAs"], "https://www.youtube.com/@acme"]
    f = wiki(
        home_resp=org_home(sameAs=same_as),
        entities=ents(item(P2397=["UCabc"])),
    )
    c = next(c for c in run(f).checks if c.code == "social_links_conflict")
    assert (c.ok, c.observed) == (True, "2 profiles agree")
    assert "P2397" not in parse_qs(urlsplit(f.calls[2][0]).query)["query"][0]


def test_pause_is_taken_before_every_fetch(monkeypatch):
    sleeps = []
    monkeypatch.setattr(entity.time, "sleep", sleeps.append)
    run(wiki(), pause=0.5)
    assert sleeps == [0.5, 0.5, 0.5]


def test_a_nested_organization_stub_does_not_shadow_the_brand_node():
    stub = {
        "@type": "WebSite",
        "publisher": {"@type": "Organization", "@id": "https://acme.com/#org"},
    }
    resp = Response(200, home(org=stub, extra=(ORG,)))
    got = home_verdicts(run(fetcher(home_resp=resp)))
    assert got == dict.fromkeys(HOME_CODES, True)
