"""audit_domain from canned responses. Nothing here touches the network."""

import random
import re

import pytest
from bsi_core.crawl import (
    BODY_CAP_BYTES,
    BOTS,
    BROWSER_UA,
    Response,
    audit_domain,
    expected,
    family,
    robots_allows,
    severity,
)

HOME = """<html><head><title>Nike</title>
<meta name="description" content="Shoes">
<link rel="canonical" href="https://nike.com/">
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[{"@type":["Organization","Brand"],"name":"Nike"}]}
</script></head><body><h1>Nike</h1></body></html>"""

ROBOTS_OPEN = "User-agent: *\nDisallow:\nSitemap: https://nike.com/sm.xml\n"
ROBOTS_BLOCK = (
    "User-agent: *\nDisallow: /private\n\n"
    "User-agent: GPTBot\nUser-agent: ClaudeBot\nDisallow: /\n"
)
SITEMAP = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://nike.com/</loc></url></urlset>'
INDEX = '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://nike.com/a.xml</loc></sitemap></sitemapindex>'


def site(pages, *, blocked_uas=()):
    """A fetch over a dict of path -> Response; records every call."""
    calls = []

    def fetch(url, ua):
        calls.append((url, ua))
        path = url.split("nike.com", 1)[1] or "/"
        if path == "/" and ua in blocked_uas:
            return Response(403, "blocked")
        return pages.get(path, Response(404, ""))

    fetch.calls = calls
    return fetch


GOOD = {
    "/": Response(200, HOME),
    "/robots.txt": Response(200, ROBOTS_OPEN),
    "/sm.xml": Response(200, SITEMAP),
    "/llms.txt": Response(200, "# Nike"),
}


def codes(audit, ok):
    return sorted(c.code for c in audit.checks if c.ok is ok)


def test_a_healthy_site_passes_every_check():
    audit = audit_domain("nike.com", site(GOOD))
    assert codes(audit, False) == []
    assert set(codes(audit, True)) >= {
        "home_unreachable",
        "title_missing",
        "description_missing",
        "h1_missing",
        "canonical_missing",
        "org_schema_missing",
        "sitemap_missing",
        "sitemap_invalid",
        "llms_missing",
        *[f"bot_blocked:{b}" for b in BOTS],
        *[f"bot_ua_blocked:{b}" for b in BOTS],
    }
    # 1 home + 1 robots + 8 bot UAs + 1 sitemap + 1 llms.txt
    assert audit.fetches == 12


def test_fetch_count_and_order_are_deterministic():
    fetch = site(GOOD)
    audit_domain("nike.com", fetch)
    urls = [u for u, _ in fetch.calls]
    assert urls[0] == "https://nike.com/"
    assert fetch.calls[0][1] == BROWSER_UA
    assert urls[1] == "https://nike.com/robots.txt"
    assert urls[2:10] == ["https://nike.com/"] * 8
    assert [ua for _, ua in fetch.calls[2:10]] == list(BOTS)
    assert urls[10] == "https://nike.com/sm.xml"  # from the robots Sitemap line
    assert urls[11] == "https://nike.com/llms.txt"


def test_robots_groups_block_named_bots_only():
    pages = {**GOOD, "/robots.txt": Response(200, ROBOTS_BLOCK)}
    audit = audit_domain("nike.com", site(pages))
    assert codes(audit, False) == [
        "bot_blocked:ClaudeBot",
        "bot_blocked:GPTBot",
        "sitemap_missing",  # no Sitemap line and /sitemap.xml is 404
    ]
    blocked = next(c for c in audit.checks if c.code == "bot_blocked:GPTBot")
    assert "Disallow: /" in blocked.observed
    assert blocked.severity == "high"
    assert blocked.url == "https://nike.com/robots.txt"


def test_missing_robots_allows_every_bot():
    pages = {k: v for k, v in GOOD.items() if k != "/robots.txt"}
    pages["/sitemap.xml"] = Response(200, INDEX)
    audit = audit_domain("nike.com", site(pages))
    assert codes(audit, False) == []


def test_cdn_blocking_only_counts_when_the_browser_got_through():
    audit = audit_domain(
        "nike.com", site(GOOD, blocked_uas=("PerplexityBot", "Bingbot"))
    )
    assert codes(audit, False) == [
        "bot_ua_blocked:Bingbot",
        "bot_ua_blocked:PerplexityBot",
    ]
    down = {**GOOD, "/": Response(503, "")}
    audit = audit_domain("nike.com", site(down, blocked_uas=BOTS))
    # Home is down for everyone: that is home_unreachable, not eight
    # CDN blocks; the on-page and bot-UA checks are skipped entirely.
    assert codes(audit, False) == ["home_unreachable"]
    assert "title_missing" not in codes(audit, True)
    assert not [c for c in audit.checks if c.code.startswith("bot_ua")]
    # home + robots + sitemap + llms.txt: no bot-UA fetches
    assert audit.fetches == 4


def test_the_bot_list_is_pinned():
    assert BOTS == (
        "GPTBot",
        "OAI-SearchBot",
        "ClaudeBot",
        "Claude-SearchBot",
        "PerplexityBot",
        "Google-Extended",
        "Googlebot",
        "Bingbot",
    )


def test_the_browser_ua_is_a_real_browser():
    # A bot-like UA gets 403 from bot-managed sites and blinds the audit.
    assert BROWSER_UA.startswith("Mozilla/5.0 (")
    assert "Chrome/" in BROWSER_UA and "compatible" not in BROWSER_UA


def test_on_page_checks_fail_individually():
    bare = "<html><head></head><body><p>hi</p></body></html>"
    audit = audit_domain("nike.com", site({**GOOD, "/": Response(200, bare)}))
    assert codes(audit, False) == [
        "canonical_missing",
        "description_missing",
        "h1_missing",
        "org_schema_missing",
        "title_missing",
    ]


def test_org_schema_is_found_in_a_plain_object_and_a_list():
    plain = HOME.replace(
        '{"@context":"https://schema.org","@graph":[{"@type":["Organization","Brand"],"name":"Nike"}]}',
        '{"@type":"Organization","name":"Nike"}',
    )
    listed = HOME.replace(
        '{"@context":"https://schema.org","@graph":[{"@type":["Organization","Brand"],"name":"Nike"}]}',
        '[{"@type":"WebSite"},{"@type":"Organization"}]',
    )
    for body in (plain, listed):
        audit = audit_domain(
            "nike.com", site({**GOOD, "/": Response(200, body)})
        )
        assert "org_schema_missing" not in codes(audit, False)
    broken = HOME.replace('"name":"Nike"', '"name":')  # invalid JSON
    audit = audit_domain("nike.com", site({**GOOD, "/": Response(200, broken)}))
    assert "org_schema_missing" in codes(audit, False)


def test_sitemap_index_is_valid_and_junk_is_not():
    pages = {**GOOD, "/sm.xml": Response(200, INDEX)}
    assert codes(audit_domain("nike.com", site(pages)), False) == []
    pages = {**GOOD, "/sm.xml": Response(200, "<html>not a sitemap</html>")}
    audit = audit_domain("nike.com", site(pages))
    assert codes(audit, False) == ["sitemap_invalid"]
    pages = {**GOOD, "/sm.xml": Response(200, "<<<")}
    assert codes(audit_domain("nike.com", site(pages)), False) == [
        "sitemap_invalid"
    ]


def test_a_sitemap_cut_off_at_the_body_cap_is_still_valid():
    # http_fetch keeps the first BODY_CAP_BYTES bytes, so a large sitemap
    # arrives truncated mid-element. Only the root element decides.
    url = "<url><loc>https://nike.com/p</loc></url>"
    body = SITEMAP.replace("</urlset>", url * 20_000)[:BODY_CAP_BYTES]
    assert len(body) == BODY_CAP_BYTES  # really truncated
    pages = {**GOOD, "/sm.xml": Response(200, body)}
    audit = audit_domain("nike.com", site(pages))
    assert codes(audit, False) == []
    check = next(c for c in audit.checks if c.code == "sitemap_invalid")
    assert check.observed == "root <urlset>"


def test_a_fetch_error_is_a_failed_check_not_an_exception():
    def fetch(url, ua):
        return Response(0, "", "ConnectError('boom')")

    audit = audit_domain("nike.com", fetch)
    # An unreachable robots.txt is disallow-all under RFC 9309 §2.3.1.4.
    assert codes(audit, False) == sorted(
        [
            "home_unreachable",
            "llms_missing",
            "sitemap_missing",
            *[f"bot_blocked:{b}" for b in BOTS],
        ]
    )
    home = audit.checks[0]
    assert "ConnectError" in home.observed


def test_observed_is_capped_and_body_over_the_cap_still_parses():
    long_title = "<title>" + "x" * 5000 + "</title>"
    body = HOME.replace("<title>Nike</title>", long_title)
    audit = audit_domain("nike.com", site({**GOOD, "/": Response(200, body)}))
    assert all(len(c.observed) <= 300 for c in audit.checks)
    assert "title_missing" not in codes(audit, False)


def test_llms_txt_is_low_severity_and_says_unofficial():
    pages = {k: v for k, v in GOOD.items() if k != "/llms.txt"}
    audit = audit_domain("nike.com", site(pages))
    llms = next(c for c in audit.checks if c.code == "llms_missing")
    assert (llms.ok, llms.severity) == (False, "low")
    assert "unofficial" in llms.expected


def test_deeply_nested_json_ld_does_not_crash_the_audit():
    nested = "[" * 3000 + "]" * 3000
    body = HOME.replace(
        '{"@context":"https://schema.org","@graph":[{"@type":["Organization","Brand"],"name":"Nike"}]}',
        nested,
    )
    audit = audit_domain("nike.com", site({**GOOD, "/": Response(200, body)}))
    assert codes(audit, False) == ["org_schema_missing"]
    assert audit.fetches == 12


def test_bot_blocked_observed_prefers_the_named_group_over_a_long_star():
    star_rules = "\n".join(f"Disallow: /p{i}" for i in range(40))
    robots = f"User-agent: *\n{star_rules}\nUser-agent: GPTBot\nDisallow: /\n"
    pages = {**GOOD, "/robots.txt": Response(200, robots)}
    audit = audit_domain("nike.com", site(pages))
    blocked = next(c for c in audit.checks if c.code == "bot_blocked:GPTBot")
    assert "User-agent: GPTBot" in blocked.observed
    assert "/p1" not in blocked.observed


def test_bot_blocked_observed_does_not_leak_across_groups_without_blanks():
    robots = (
        "User-agent: GPTBot\nDisallow: /\n"
        "User-agent: Bingbot\nDisallow: /private\n"
    )
    pages = {**GOOD, "/robots.txt": Response(200, robots)}
    audit = audit_domain("nike.com", site(pages))
    bing = next(c for c in audit.checks if c.code == "bot_blocked:Bingbot")
    assert "User-agent: Bingbot" in bing.observed
    assert "GPTBot" not in bing.observed


@pytest.mark.parametrize(
    ("code", "sev"),
    [
        ("home_unreachable", "high"),
        ("bot_blocked:GPTBot", "high"),
        ("bot_ua_blocked:Bingbot", "high"),
        ("sitemap_missing", "medium"),
        ("sitemap_invalid", "medium"),
        ("org_schema_missing", "medium"),
        ("title_missing", "low"),
        ("llms_missing", "low"),
    ],
)
def test_severity_and_expected_are_defined_for_every_code(code, sev):
    assert severity(code) == sev
    assert expected(code)
    assert family("bot_blocked:GPTBot") == "bot_blocked"


def test_pause_is_applied_between_fetches(monkeypatch):
    slept = []
    monkeypatch.setattr("bsi_core.crawl.time.sleep", slept.append)
    audit_domain("nike.com", site(GOOD), pause=0.5)
    assert slept == [0.5] * 11  # between 12 fetches
    slept.clear()
    audit_domain("nike.com", site({**GOOD, "/": Response(503, "")}), pause=0.5)
    assert slept == [0.5] * 3  # home down: between 4 fetches


def test_a_non_http_sitemap_scheme_is_ignored():
    robots = "User-agent: *\nDisallow:\nSitemap: javascript:alert(1)\n"
    pages = {**GOOD, "/robots.txt": Response(200, robots)}
    fetch = site(pages)
    audit = audit_domain("nike.com", fetch)
    urls = [u for u, _ in fetch.calls]
    assert "https://nike.com/sitemap.xml" in urls
    assert not any(c.url.startswith("javascript:") for c in audit.checks)


def test_an_off_host_sitemap_is_ignored():
    robots = "User-agent: *\nDisallow:\nSitemap: https://evil.example/sm.xml\n"
    pages = {**GOOD, "/robots.txt": Response(200, robots)}
    fetch = site(pages)
    audit_domain("nike.com", fetch)
    urls = [u for u, _ in fetch.calls]
    assert "https://nike.com/sitemap.xml" in urls
    assert not any("evil.example" in u for u in urls)


def test_a_subdomain_sitemap_is_trusted():
    robots = "User-agent: *\nDisallow:\nSitemap: https://cdn.nike.com/sm.xml\n"
    pages = {**GOOD, "/robots.txt": Response(200, robots)}
    fetch = site(pages)
    audit_domain("nike.com", fetch)
    urls = [u for u, _ in fetch.calls]
    assert "https://cdn.nike.com/sm.xml" in urls


def test_an_empty_sitemap_body_has_no_root():
    pages = {**GOOD, "/sm.xml": Response(200, "")}
    audit = audit_domain("nike.com", site(pages))
    check = next(c for c in audit.checks if c.code == "sitemap_invalid")
    assert (check.ok, check.observed) == (False, "root <none>")


def test_bom_declaration_and_doctype_before_the_root_are_fine():
    body = (
        '﻿<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE urlset>\n'
        + (SITEMAP.split("?>", 1)[1])
    )
    pages = {**GOOD, "/sm.xml": Response(200, body)}
    assert codes(audit_domain("nike.com", site(pages)), False) == []


def test_a_billion_laughs_sitemap_does_not_hang_or_raise():
    # expat's amplification limit (expat >= 2.4) stops the expansion.
    ents = ['<!ENTITY lol0 "lol">'] + [
        f'<!ENTITY lol{i} "{f"&lol{i - 1};" * 10}">' for i in range(1, 10)
    ]
    body = f"<!DOCTYPE lolz [{''.join(ents)}]><lolz>&lol9;</lolz>"
    pages = {**GOOD, "/sm.xml": Response(200, body)}
    audit = audit_domain("nike.com", site(pages))
    assert any(c.code == "sitemap_invalid" for c in audit.checks)


def _bot_check(robots, bot):
    pages = {**GOOD, "/robots.txt": Response(200, robots)}
    audit = audit_domain("nike.com", site(pages))
    return next(c for c in audit.checks if c.code == f"bot_blocked:{bot}")


def test_comment_sitemap_host_and_blank_lines_do_not_split_a_group():
    # RFC 9309: only a user-agent line after a rule starts a new group, so
    # all of these are one `*` group whose Disallow applies to GPTBot.
    for between in (
        "# note",
        "Sitemap: https://nike.com/sm.xml",
        "Host: x",
        "",
    ):
        robots = f"User-agent: *\n{between}\nUser-agent: Google-Extended\n"
        check = _bot_check(robots + "Disallow: /\n", "GPTBot")
        assert not check.ok
        assert "Disallow: /" in check.observed, between


# RFC 9309 robots.txt semantics.


def _verdict(robots, bot="GPTBot"):
    return _bot_check(robots, bot).ok


def test_allow_only_the_homepage_allows_the_homepage():
    robots = "User-agent: *\nDisallow: /\nAllow: /$\n"
    audit = audit_domain(
        "nike.com", site({**GOOD, "/robots.txt": Response(200, robots)})
    )
    assert not [c for c in codes(audit, False) if c.startswith("bot_blocked")]


def test_an_allow_and_a_disallow_of_equal_length_allow():
    assert _verdict("User-agent: *\nDisallow: /\nAllow: /\n")
    assert _verdict("User-agent: *\nAllow: /\nDisallow: /\n")


@pytest.mark.parametrize(
    ("rule", "allowed"),
    [
        ("Disallow: /", False),
        ("Disallow: /*", False),
        ("Disallow: *", False),
        ("Disallow: /*.pdf", True),
        ("Disallow: /$", False),
        ("Disallow: /x$", True),
        ("Disallow:", True),  # an empty value matches nothing
        ("Disallow: /* # block all", False),
        ("disallow : /", False),  # keys are case-insensitive
        ("Allow: /", True),
    ],
)
def test_rule_patterns(rule, allowed):
    assert _verdict(f"User-agent: *\n{rule}\n") is allowed


def test_the_longest_matching_rule_wins():
    assert not _verdict("User-agent: *\nAllow: /\nDisallow: /*\n")
    assert _verdict("User-agent: *\nDisallow: /*\nAllow: /$\n")


def test_a_name_that_only_contains_the_bot_does_not_apply():
    # `Claude` is not ClaudeBot's product token: the `*` group applies.
    robots = "User-agent: *\nAllow: /\n\nUser-agent: Claude\nDisallow: /\n"
    for bot in ("ClaudeBot", "Claude-SearchBot"):
        check = _bot_check(robots, bot)
        assert check.ok
        assert check.observed == "User-agent: *\nAllow: /"


def test_the_product_token_stops_at_a_version():
    robots = (
        "User-agent: *\nAllow: /\n\nUser-agent: claudebot/1.0\nDisallow: /\n"
    )
    check = _bot_check(robots, "ClaudeBot")
    assert not check.ok
    assert check.observed == "User-agent: claudebot/1.0\nDisallow: /"


def test_every_group_naming_the_bot_is_merged():
    robots = (
        "User-agent: GPTBot\nAllow: /\n\n"
        "User-agent: Bingbot\nDisallow: /\n\n"
        "User-agent: gptbot\nDisallow: /*\n"
    )
    check = _bot_check(robots, "GPTBot")
    assert not check.ok  # /* is longer than /
    assert check.observed == (
        "User-agent: GPTBot\nAllow: /\nUser-agent: gptbot\nDisallow: /*"
    )


def test_a_named_group_beats_a_stricter_star():
    robots = "User-agent: *\nDisallow: /\n\nUser-agent: GPTBot\nAllow: /x\n"
    check = _bot_check(robots, "GPTBot")
    assert check.ok
    assert check.observed == "User-agent: GPTBot\nAllow: /x"
    assert not _bot_check(robots, "Bingbot").ok


def test_a_group_naming_star_and_the_bot_is_a_named_match():
    robots = (
        "User-agent: *\nUser-agent: GPTBot\nDisallow: /\n\n"
        "User-agent: GPT\nAllow: /\n"
    )
    check = _bot_check(robots, "GPTBot")
    assert not check.ok
    assert check.observed == "User-agent: *\nUser-agent: GPTBot\nDisallow: /"


def test_rules_before_the_first_user_agent_belong_to_nobody():
    check = _bot_check("Disallow: /\nUser-agent: Bingbot\nAllow: /\n", "GPTBot")
    assert (check.ok, check.observed) == (True, "no matching group")


def test_a_blank_line_after_a_user_agent_does_not_end_the_group():
    check = _bot_check("User-agent: GPTBot\n\nDisallow: /\n", "GPTBot")
    assert (check.ok, check.observed) == (
        False,
        "User-agent: GPTBot\nDisallow: /",
    )


def test_an_unreachable_robots_txt_disallows_everything():
    pages = {**GOOD, "/robots.txt": Response(503, "")}
    audit = audit_domain("nike.com", site(pages))
    for bot in BOTS:
        check = next(c for c in audit.checks if c.code == f"bot_blocked:{bot}")
        assert not check.ok
        assert "HTTP 503" in check.observed
        assert "disallow" in check.observed


def test_a_missing_robots_txt_allows_everything():
    pages = {**GOOD, "/robots.txt": Response(404, "")}
    audit = audit_domain("nike.com", site(pages))
    for bot in BOTS:
        check = next(c for c in audit.checks if c.code == f"bot_blocked:{bot}")
        assert (check.ok, check.observed) == (True, "no robots.txt (HTTP 404)")


def test_evidence_too_long_to_show_keeps_what_decides():
    rules = "\n".join(f"Disallow: /private/{i}" for i in range(40))
    robots = f"User-agent: Bingbot\nUser-agent: GPTBot\n{rules}\nDisallow: /\n"
    check = _bot_check(robots, "GPTBot")
    assert not check.ok
    assert check.observed == "User-agent: GPTBot\nDisallow: /"
    assert robots_allows(check.observed) is check.ok


def _token(agent):
    """The test's own reading of a product token, for the fuzz oracle."""
    agent = agent.strip()
    return "*" if agent == "*" else re.match(r"[A-Za-z_-]*", agent)[0].lower()


def test_observed_always_agrees_with_the_verdict():
    # Seeded fuzz. Each group carries a marker rule /gN that never matches
    # "/", so the markers in `observed` say which groups were used. For
    # every bot: the evidence alone gives the same verdict, and it shows
    # exactly the groups that name the bot (or, failing that, `*`).
    rng = random.Random(9309)
    agents = [
        "*",
        "Claude",
        "ClaudeBot",
        "claudebot/1.0",
        "GPTBot",
        "gptbot",
        "Googlebot-News",
        "Google-Extended",
        "Bot",
        "",
    ]
    rules = ["/", "/*", "*", "/$", "/*$", "", "/*.pdf", "/x"]
    noise = ["", "   ", "# c", "Sitemap: https://nike.com/s.xml", "Host: x"]
    for _ in range(3000):
        lines = ["Disallow: /"] if rng.random() < 0.2 else []
        groups = []
        for g in range(rng.randint(1, 3)):
            names = [rng.choice(agents) for _ in range(rng.randint(1, 2))]
            groups.append(names)
            for name in names:
                lines.append(f"User-agent: {name}")
                if rng.random() < 0.3:
                    lines.append(rng.choice(noise))
            lines.append(f"Disallow: /g{g}")
            if rng.random() < 0.8:
                kind = rng.choice(["Allow", "Disallow"])
                comment = " # why" if rng.random() < 0.2 else ""
                lines.append(f"{kind}: {rng.choice(rules)}{comment}")
        robots = rng.choice(["\n", "\r\n"]).join(lines) + "\n"
        pages = {**GOOD, "/robots.txt": Response(200, robots)}
        checks = {
            c.code: c for c in audit_domain("nike.com", site(pages)).checks
        }
        for bot in BOTS:
            check = checks[f"bot_blocked:{bot}"]
            assert robots_allows(check.observed) is check.ok, (robots, bot)
            tokens = [{_token(n) for n in names} for names in groups]
            used = {g for g, t in enumerate(tokens) if bot.lower() in t} or {
                g for g, t in enumerate(tokens) if "*" in t
            }
            shown = {int(m) for m in re.findall(r"/g(\d)", check.observed)}
            assert shown == used, (robots, bot)


def test_too_many_robots_redirects_is_unavailable_so_allow_all():
    # RFC 9309 §2.3.1.2: unresolved redirects mean "unavailable" (§2.3.1.3).
    refused = Response(0, "", "refused: too many redirects")
    audit = audit_domain("nike.com", site({**GOOD, "/robots.txt": refused}))
    for bot in BOTS:
        check = next(c for c in audit.checks if c.code == f"bot_blocked:{bot}")
        assert (check.ok, check.observed) == (
            True,
            "robots.txt: more than 5 redirects, read as unavailable "
            "(RFC 9309 §2.3.1.2)",
        )


def test_any_other_refusal_of_robots_txt_is_unreachable_so_disallow_all():
    refused = Response(0, "", "refused: 10.0.0.1 is not a public address")
    audit = audit_domain("nike.com", site({**GOOD, "/robots.txt": refused}))
    for bot in BOTS:
        check = next(c for c in audit.checks if c.code == f"bot_blocked:{bot}")
        assert not check.ok
        assert "10.0.0.1 is not a public address" in check.observed


def test_a_leading_bom_does_not_hide_the_first_line():
    robots = "\ufeffUser-agent: *\nDisallow: /"
    for bot in BOTS:
        assert not _bot_check(robots, bot).ok, bot


@pytest.mark.parametrize(
    "robots",
    [
        "User-agent: GPTBot\x85Disallow: /",  # NEL is not an end of line
        "User-agent: GPTBot\u2028Disallow: /",  # nor is U+2028
        "User-agent: *\nDisallow\xa0: /",  # NBSP is not whitespace: key unknown
    ],
)
def test_only_cr_and_lf_end_a_line_and_only_space_and_tab_are_whitespace(
    robots,
):
    assert _bot_check(robots, "GPTBot").ok


def test_a_padded_rule_is_shown_normalized():
    check = _bot_check("User-agent: *\nDisallow:" + " " * 300 + "/", "GPTBot")
    assert not check.ok
    assert "Disallow: /" in check.observed
    assert robots_allows(check.observed) is check.ok


# An independent RFC 9309 reading, written from the RFC text (from the
# security review's fuzz.py), to check verdicts and not only evidence.


def _rfc_verdict(text, bot):
    groups, current, in_rules = [], None, False
    for raw in re.split(r"\r\n|\r|\n", text.removeprefix("\ufeff")):
        line = raw.split("#", 1)[0]
        if ":" not in line:
            continue
        key, value = (x.strip(" \t") for x in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if current is None or in_rules:
                current, in_rules = (set(), []), False
                groups.append(current)
            token = "*" if value == "*" else re.match(r"[A-Za-z_-]*", value)[0]
            current[0].add(token.lower())
        elif key in ("allow", "disallow") and current is not None:
            current[1].append((key, value))
            in_rules = True
    used = [g for g in groups if bot.lower() in g[0]] or [
        g for g in groups if "*" in g[0]
    ]
    best = None
    for key, value in (r for g in used for r in g[1]):
        if value and _glob(value, "/"):
            rank = (len(value.encode()), key == "allow")
            best = rank if best is None or rank > best else best
    return best is None or best[1]


def _glob(pattern, path):
    anchored = pattern.endswith("$")
    pos = {0}
    for ch in pattern[:-1] if anchored else pattern:
        if ch == "*":
            pos = set(range(min(pos), len(path) + 1)) if pos else pos
        else:
            pos = {i + 1 for i in pos if i < len(path) and path[i] == ch}
    return len(path) in pos if anchored else bool(pos)


def test_verdicts_match_an_independent_rfc_reading():
    rng = random.Random(2)
    agents = ["*", "* ", "GPTBot", "gptbot", "GPTBOT/1.0", "GPTBot*", "Claude"]
    agents += ["ClaudeBot", "claudebot/1.1", "Claude-SearchBot", "bingbot"]
    agents += ["oai-searchbot (x)", "Google-Extended", "Googlebot", "", "-"]
    ua_keys = ["User-agent", "user-agent", "USER-AGENT", "User-Agent ", " ua"]
    rule_keys = [
        "Allow",
        "Disallow",
        "allow",
        "DISALLOW",
        "Disallow ",
        " allow",
    ]
    other = ["Sitemap: https://x.com/s.xml", "Host: x", "# c", "", "junk"]
    weird = ["\x0c", "\x85", "\xa0", "\u2028", "\ufeff", "\x0b", "\x1e"]
    for _ in range(3000):
        lines = []
        for _ in range(rng.randint(1, 40 if rng.random() < 0.3 else 12)):
            r = rng.random()
            if r < 0.3:
                line = f"{rng.choice(ua_keys)}: {rng.choice(agents)}"
            elif r < 0.75:
                pattern = "".join(
                    rng.choice("/*$a.") for _ in range(rng.randint(0, 5))
                )
                line = (
                    f"{rng.choice(rule_keys)}:{rng.choice(['', ' '])}{pattern}"
                )
            else:
                line = rng.choice(other)
            if rng.random() < 0.05:
                i = rng.randint(0, len(line))
                line = line[:i] + rng.choice(weird) + line[i:]
            lines.append(line)
        text = rng.choice(["\n", "\r\n", "\r"]).join(lines)
        if rng.random() < 0.05:
            text = "\ufeff" + text
        pages = {**GOOD, "/robots.txt": Response(200, text)}
        checks = {
            c.code: c for c in audit_domain("nike.com", site(pages)).checks
        }
        for bot in BOTS:
            check = checks[f"bot_blocked:{bot}"]
            assert check.ok is _rfc_verdict(text, bot), (text, bot)
            assert robots_allows(check.observed) is check.ok, (text, bot)


@pytest.mark.parametrize("tail", ["\x0b", "\x85", "\xa0", "\u2028", "\x1e"])
def test_clipping_evidence_keeps_characters_the_rfc_does_not_strip(tail):
    # `Disallow: *<tail>` does not match "/"; str.strip() would drop the
    # tail from the evidence and make it read as a match.
    check = _bot_check(f"User-agent: *\nDisallow: *{tail}", "GPTBot")
    assert check.ok
    assert robots_allows(check.observed) is check.ok
