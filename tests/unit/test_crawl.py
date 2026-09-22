"""audit_domain from canned responses. Nothing here touches the network."""

import random
import re
from urllib import robotparser

import pytest
from bsi_core.crawl import (
    BODY_CAP,
    BOTS,
    BROWSER_UA,
    Response,
    audit_domain,
    expected,
    family,
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
    # http_fetch keeps the first BODY_CAP characters, so a large sitemap
    # arrives truncated mid-element. Only the root element decides.
    url = "<url><loc>https://nike.com/p</loc></url>"
    body = SITEMAP.replace("</urlset>", url * 20_000)[:BODY_CAP]
    assert len(body) == BODY_CAP  # really truncated
    pages = {**GOOD, "/sm.xml": Response(200, body)}
    audit = audit_domain("nike.com", site(pages))
    assert codes(audit, False) == []
    check = next(c for c in audit.checks if c.code == "sitemap_invalid")
    assert check.observed == "root <urlset>"


def test_a_fetch_error_is_a_failed_check_not_an_exception():
    def fetch(url, ua):
        return Response(0, "", "ConnectError('boom')")

    audit = audit_domain("nike.com", fetch)
    assert codes(audit, False) == [
        "home_unreachable",
        "llms_missing",
        "sitemap_missing",
    ]
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


def test_disallow_trailing_star_blocks_like_a_bare_slash():
    robots = "User-agent: GPTBot\nDisallow: /*\n"
    pages = {**GOOD, "/robots.txt": Response(200, robots)}
    audit = audit_domain("nike.com", site(pages))
    assert "bot_blocked:GPTBot" in codes(audit, False)


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


def test_bot_blocked_observed_matches_robotparser_substring_rule():
    # robotparser applies `User-agent: Claude` to any bot whose name
    # contains "claude", so the evidence must be that group, not `*`.
    robots = "User-agent: *\nAllow: /\n\nUser-agent: Claude\nDisallow: /\n"
    pages = {**GOOD, "/robots.txt": Response(200, robots)}
    audit = audit_domain("nike.com", site(pages))
    for bot in ("ClaudeBot", "Claude-SearchBot"):
        check = next(c for c in audit.checks if c.code == f"bot_blocked:{bot}")
        assert not check.ok
        assert "User-agent: Claude" in check.observed
        assert "Disallow: /" in check.observed
        assert "User-agent: *" not in check.observed


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


def test_bot_blocked_observed_is_only_the_first_applicable_group():
    # robotparser applies the first matching named group and ignores the
    # rest, so the evidence must be that group alone.
    allow = "User-agent: Claude\nAllow: /\n"
    block = "User-agent: ClaudeBot\nDisallow: /\n"
    first_allows = _bot_check(allow + block, "ClaudeBot")
    assert first_allows.ok
    assert "Allow: /" in first_allows.observed
    assert "Disallow" not in first_allows.observed
    first_blocks = _bot_check(block + allow, "ClaudeBot")
    assert not first_blocks.ok
    assert "Disallow: /" in first_blocks.observed
    assert "Allow" not in first_blocks.observed.replace("Disallow", "")


def test_a_group_naming_star_is_the_default_not_a_named_match():
    # robotparser files any group containing `*` as the default entry,
    # so GPTBot in that group does not count as naming it.
    robots = (
        "User-agent: *\nUser-agent: GPTBot\nDisallow: /\n\n"
        "User-agent: GPT\nAllow: /\n"
    )
    check = _bot_check(robots, "GPTBot")
    assert check.ok
    assert check.observed == "User-agent: GPT\nAllow: /"


def test_comment_and_sitemap_lines_do_not_split_a_group():
    # robotparser ignores comments and gives Sitemap: no grouping effect,
    # so all of these are one `*` group whose Disallow applies to GPTBot.
    for between in ("# note", "Sitemap: https://nike.com/sm.xml", "Host: x"):
        robots = f"User-agent: *\n{between}\nUser-agent: Google-Extended\n"
        check = _bot_check(robots + "Disallow: /\n", "GPTBot")
        assert not check.ok
        assert "Disallow: /" in check.observed, between


def test_a_user_agent_cut_off_by_a_blank_line_names_nobody():
    # A blank line straight after User-agent: makes robotparser drop it,
    # and the Disallow that follows then belongs to no group at all.
    check = _bot_check("User-agent: GPTBot\n\nDisallow: /\n", "GPTBot")
    assert check.ok
    assert check.observed == "no matching group"


def _applied_markers(robots, bot):
    """The /gN rule markers of the entry robotparser applies to bot."""
    rp = robotparser.RobotFileParser()
    rp.parse(robots.splitlines())
    entry = next((e for e in rp.entries if e.applies_to(bot)), rp.default_entry)
    return set() if entry is None else {r.path for r in entry.rulelines}


def test_observed_is_always_the_group_robotparser_applied():
    # Seeded fuzz: every group gets a unique marker rule, and the evidence
    # must carry exactly the markers of the entry robotparser chose.
    rng = random.Random(7)
    tokens = ["*", "Claude", "ClaudeBot", "Google", "GPTBot", "Bot", "gpt"]
    noise = ["", "# c", "Sitemap: https://nike.com/s.xml", "Host: nike.com"]
    for _ in range(3000):
        lines = []
        for g in range(rng.randint(1, 4)):
            for _ in range(rng.randint(1, 3)):
                lines.append(f"User-agent: {rng.choice(tokens)}")
                if rng.random() < 0.3:
                    lines.append(rng.choice(noise))
            lines.append(f"{rng.choice(['Allow', 'Disallow'])}: /g{g}")
            if rng.random() < 0.3:
                lines.append(rng.choice(noise))
        robots = "\n".join(lines) + "\n"
        for bot in BOTS:
            observed = _bot_check(robots, bot).observed
            shown = set(re.findall(r"/g\d", observed))
            assert shown == _applied_markers(robots, bot), (robots, bot)
