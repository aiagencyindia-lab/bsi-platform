# Slice 8 findings: entity consistency audit

Date: 2026-09-23. Branch `slice8-entity-consistency`. Sources: direct
calls of `bsi_core.entity.audit_entity()` against six real public domains
through `bsi_core.crawl.http_fetch` (the SSRF-guarded fetcher), plus a few
plain-HTTP probes of the same Wikidata endpoints and home pages to explain
what the audit returned. Plain HTTP only: no model call, no spend, and
nothing written to the dev database. Afterwards the dev tables
`recommendation`, `task` and `site_audit` held `0|0|0` rows.

The audit ran several times while the Wikidata matching was fixed on this
branch (section 3):
- `b67cf8f` read Wikidata through one SPARQL query, after the first run
  showed large brands losing every Wikidata check.
- `1218dba` ranked the exact host over a subdomain and read `mul` labels,
  after the SPARQL run matched a Wikimedia governance wiki and showed
  `mul`-only items.

The results below are from the final run on `1218dba`. Two runs on that
commit printed identical output.

## 1. What was measured, and how

Run with `uv run python live_entity_fix2.py` from the repo root (the
script of the final run):

```python
import logging
from bsi_core.crawl import http_fetch
from bsi_core.entity import audit_entity

logging.basicConfig(level=logging.WARNING, format="LOG %(name)s %(message)s")
CASES = [
    ("wikimediafoundation.org", "Wikimedia Foundation", []),
    ("mozilla.org", "Mozilla", ["Mozilla Foundation", "Mozilla Corporation"]),
    ("python.org", "Python Software Foundation", ["Python"]),
    ("apache.org", "Apache Software Foundation", []),
    ("wikimedia.org", "Wikimedia Foundation", []),
    # A brand that should not be on Wikidata.
    ("example.com", "Acme Rocket Widgets Pvt", []),
]
for host, name, aliases in CASES:
    a = audit_entity(host, name, aliases, [host], http_fetch, pause=0.5)
    print(f"\n== {host} ({name}) fetches={a.fetches}")
    for c in a.checks:
        print(f"  {'ok ' if c.ok else 'FAIL'} {c.severity:6} {c.code:24} {c.observed}")
```

The plan's first three cases were mozilla.org, python.org and example.com.
wikimedia.org and apache.org are the plan's fallbacks, added when the first
run returned no Wikidata rows for Mozilla. wikimediafoundation.org was
added once it was clear that it, not wikimedia.org, is the Foundation's own
site. The final run logged no warnings.

## 2. Results

A check that is not listed was skipped, not passed. The four `org_*` rows
need a schema.org Organization node on the home page, and none of these
five home pages has one: that gap is crawl's `org_schema_missing`, not an
entity finding. The one exception is wikimediafoundation.org, the only
home page with an Organization node, so the only one with `org_*` rows.

### wikimediafoundation.org (Wikimedia Foundation), fetches=3

| Check | Result | Severity | Observed |
|---|---|---|---|
| `org_name_mismatch` | ok | high | Wikimedia Foundation |
| `org_url_mismatch` | ok | medium | https://wikimediafoundation.org/ |
| `org_logo_missing` | ok | medium | https://wikimediafoundation.org/wp-content/uploads/2022/04/foundation.png |
| `org_sameas_missing` | ok | medium | https://www.facebook.com/wikipedia/, https://x.com/wikimedia, https://www.instagram.com/wikimediafoundation/, https://www.linkedin.com/company/wikimedia-foundation |
| `website_schema_missing` | ok | low | 1 ld+json block(s) |
| `title_brand_missing` | ok | medium | Home – Wikimedia Foundation |
| `about_missing` | FAIL | low | no /about or /company link among 158 links |
| `wikidata_missing` | ok | low | Q180: Wikimedia Foundation |
| `wikidata_name_mismatch` | ok | medium | Q180: Wikimedia Foundation |
| `wikidata_logo_missing` | ok | low | Q180 |
| `social_links_conflict` | FAIL | medium | on Wikidata only: facebook.com/wikimediafoundation; on site only: facebook.com/wikipedia |

This is the one domain where every check had something to read.
- The social conflict is real. The site's sameAs links the Wikipedia
  Facebook page, while Wikidata lists the Foundation's own page. Twitter,
  Instagram and LinkedIn agree.
- `about_missing` fails because the Foundation's About section is
  `/who-we-are/`. A probe of the home page found `/who-we-are/`,
  `/who-we-are/people/` and similar, and the check knows only `/about` and
  `/company`.

### mozilla.org (Mozilla), fetches=3

| Check | Result | Severity | Observed |
|---|---|---|---|
| `website_schema_missing` | FAIL | low | 0 ld+json block(s) |
| `title_brand_missing` | ok | medium | Internet for people, not profit — Mozilla Global |
| `about_missing` | ok | low | https://mozilla.org/en-GB/about/ |
| `wikidata_missing` | ok | low | Q169925: Mozilla Corporation |
| `wikidata_name_mismatch` | ok | medium | Q169925: Mozilla Corporation |
| `wikidata_logo_missing` | ok | low | Q169925 |
| `social_links_conflict` | ok | medium | nothing to compare: 2 on Wikidata, 0 on site |

### python.org (Python Software Foundation), fetches=3

| Check | Result | Severity | Observed |
|---|---|---|---|
| `website_schema_missing` | ok | low | 1 ld+json block(s) |
| `title_brand_missing` | ok | medium | Welcome to Python.org |
| `about_missing` | ok | low | https://python.org/about/ |
| `wikidata_missing` | ok | low | Q83818: Python Software Foundation |
| `wikidata_name_mismatch` | ok | medium | Q83818: Python Software Foundation |
| `wikidata_logo_missing` | ok | low | Q83818 |
| `social_links_conflict` | ok | medium | nothing to compare: 2 on Wikidata, 0 on site |

### apache.org (Apache Software Foundation), fetches=3

| Check | Result | Severity | Observed |
|---|---|---|---|
| `website_schema_missing` | FAIL | low | 0 ld+json block(s) |
| `title_brand_missing` | ok | medium | Welcome to The Apache Software Foundation \| Apache Software Foundation |
| `about_missing` | FAIL | low | no /about or /company link among 175 links |
| `wikidata_missing` | ok | low | Q489709: Apache Software Foundation |
| `wikidata_name_mismatch` | ok | medium | Q489709: Apache Software Foundation |
| `wikidata_logo_missing` | ok | low | Q489709 |
| `social_links_conflict` | ok | medium | nothing to compare: 1 on Wikidata, 0 on site |

### wikimedia.org (Wikimedia Foundation), fetches=3

| Check | Result | Severity | Observed |
|---|---|---|---|
| `website_schema_missing` | FAIL | low | 0 ld+json block(s) |
| `title_brand_missing` | FAIL | medium | Wikimedia |
| `about_missing` | FAIL | low | no /about or /company link among 22 links |
| `wikidata_missing` | ok | low | Q57077840: Wikimedia Foundation Governance Wiki |
| `wikidata_name_mismatch` | FAIL | medium | Q57077840: Wikimedia Foundation Governance Wiki |
| `wikidata_logo_missing` | ok | low | Q57077840 |
| `social_links_conflict` | ok | medium | nothing to compare: 0 on Wikidata, 0 on site |

### example.com (Acme Rocket Widgets Pvt), fetches=2

| Check | Result | Severity | Observed |
|---|---|---|---|
| `website_schema_missing` | FAIL | low | 0 ld+json block(s) |
| `title_brand_missing` | FAIL | medium | Example Domain |
| `about_missing` | FAIL | low | no /about or /company link among 1 links |
| `wikidata_missing` | FAIL | low | no search results |

Two fetches: an empty search skips the SPARQL call, as designed.

**Reading the home-page rows.**
- `title_brand_missing` on wikimedia.org is a true miss against the name
  as given. The title is "Wikimedia", the brand is "Wikimedia
  Foundation", and the check asks whether the title contains a declared
  name. An operator who declares "Wikimedia" as an alias clears it.
- `about_missing` on mozilla.org failed in the first run: its About link
  is `/en-US/about/`, and the prefix test wanted `/about`. Locale segments
  are now accepted (section 3). The site chooses the locale per request:
  one run found `/en-US/about/`, the final runs `/en-GB/about/`.
- wikimedia.org's only About-like link is
  `https://wikimediafoundation.org/about/contact/`, on another host, so its
  failure is correct as designed.
- apache.org's home page has no link containing "about" at all.

## 3. What the matching did

**Found and fixed: a truncated Wikidata answer.** The first run fetched
candidates with `wbgetentities`, which returns every claim of every item.
For "Mozilla" and "Wikimedia Foundation" the ten-item answer hit
`http_fetch`'s `BODY_CAP_BYTES` exactly:

```
Wikimedia Foundation ids= ['Q180', 'Q14827288', ...] entities body bytes= 524288 cap= 524288
Mozilla ids= ['Q698', 'Q169925', ...] entities body bytes= 524288 cap= 524288
```

The JSON was cut off mid-string, `json.loads` raised, and `audit_entity`
skipped all four Wikidata checks with no trace. Q698 (Mozilla Firefox)
alone overflowed the cap. The brands most likely to have a rich Wikidata
item were the ones that got no Wikidata checks.

What changed in `b67cf8f`:
- **One SPARQL query** to `query.wikidata.org` replaces `wbgetentities`.
  It asks only for the English label, a P154 count, and the P856 and
  social values, one row per candidate. The same two probes now return
  4621 bytes (Wikimedia Foundation) and 6265 bytes (Mozilla).
- **Id validation.** Only ids matching `Q[0-9]+` enter the query.
- **Root-path preference.** Among domain-verified candidates, the first
  whose P856 is the domain root wins over search order.
- **Locale About paths** (`/en-US/about/`) count.
- **A warning is logged** on `bsi.entity` whenever a Wikidata answer is
  skipped.

Live SPARQL answers leave out an aggregate that has no values. The first
live run of the fix hit this as `KeyError('P2013')` and similar, logged
it, and skipped the rows. The parser now reads a missing aggregate as
empty, and the test fixtures leave empty aggregates out the same way.

**Matched, by P856.**

| Domain | Match | Why |
|---|---|---|
| mozilla.org | Q169925 "Mozilla Corporation" | P856 `https://www.mozilla.org`, the domain root |
| python.org | Q83818 "Python Software Foundation" | P856 on python.org |
| apache.org | Q489709 "Apache Software Foundation" | P856 on apache.org |
| wikimediafoundation.org | Q180 "Wikimedia Foundation" | P856 `https://wikimediafoundation.org/`, exact host at the root; the label is `mul` only |
| wikimedia.org | Q57077840 "Wikimedia Foundation Governance Wiki" | P856 `https://foundation.wikimedia.org/`, a subdomain, and the only candidate on wikimedia.org |

For Mozilla, the SPARQL probe listed each candidate's P856 in search
order:
- Q698 Mozilla Firefox: `https://www.firefox.com`, rejected (another
  domain).
- Q169925 Mozilla Corporation: `https://www.mozilla.org`, root, matched.
- Q308915 Mozilla Public License: `https://www.mozilla.org/MPL/`, on the
  domain but not the root.
- Q9661 "Mozilla" (`mul` label only): `https://www.mozilla.org/en-US/`.
- Q3273508 MDN Web Docs: `https://developer.mozilla.org/`.

Firefox is not the risk it looked like, since its site is firefox.com.
The root preference guards against Q308915 or Q9661 appearing first.

**Found and fixed: a subdomain item and `mul` labels (`1218dba`).**
- **Subdomain.** Q180, the Wikimedia Foundation itself, lists P856
  `https://wikimediafoundation.org/`. Q57077840 lists
  `https://foundation.wikimedia.org/`, and `is_owned` counts subdomains.
  Candidates are now ranked: exact host at the root, then exact host,
  then subdomain root, then subdomain. Ties keep search order.
- **wikimedia.org still matches Q57077840.** No candidate has P856 on
  wikimedia.org itself, so the subdomain item is the best there is.
  `wikidata_name_mismatch` fails against its label, so the operator sees
  the mismatch. The declared domain was the case's mistake; with
  wikimediafoundation.org declared, Q180 matches.
- **`mul` labels.** Q180 and Q9661 have no English label, only a `mul`
  ("default for all languages") label: "Wikimedia Foundation" and
  "Mozilla". The query now fetches both and uses English, else `mul`. Q180
  on wikimediafoundation.org passes `wikidata_name_mismatch` through its
  `mul` label.

**Found and fixed: legal suffixes (final review, not the live run).**
`org_name_mismatch` and `wikidata_name_mismatch` compared whole names, so
an Organization named "Nike, Inc." failed against the brand "Nike" (high,
priority 0.7), and so would a Wikidata label like "Apple Inc.". Both
checks now drop trailing legal-suffix words (inc, ltd, llc, gmbh, pvt,
co, …) from both sides before comparing, always keeping one word. The
same review made a relative Organization `url` ("/") resolve against the
homepage, and read `m.` and `mobile.` social hosts as the plain host. None
of the six live cases hit these, so the results above are unchanged.

**Rejected.** example.com: the search for "Acme Rocket Widgets Pvt"
returned nothing, so `wikidata_missing` fails with "no search results".

## 4. Where `fix_entity` lands

Site-check recommendations are judged, not measured. Reach is 1.0,
pressure is the check's severity weight (`high` 1.0, `medium` 0.5, `low`
0.2), and priority is reach x pressure x feasibility.

| Severity | `fix_entity` (feasibility 0.7) | `fix_crawlability` (feasibility 0.8) |
|---|---|---|
| high | 0.7 | 0.8 |
| medium | 0.35 | 0.4 |
| low | 0.14 | 0.16 |

A high entity finding sits just under a high crawl finding and above a
medium one. Every entity finding from this run is medium or low, so all of
them rank below any high crawl finding for the same brand.

## About page (added later)

The entity audit now fetches the About page that `about_missing` finds
(one browser-UA fetch, after the homepage and before Wikidata) and adds
two checks: `about_unreachable` (medium, the fetch is not 2xx) and
`about_brand_missing` (low, neither its `<title>` nor its first `<h1>`
names the brand or an alias). When the homepage has no Organization node,
an Organization on the About page supplies the four `org_*` rows. Up to
16 fetches per domain.

Live re-run, plain HTTP through `http_fetch`, pause 0.5 s, no model call,
nothing written to the database (the About and `org_*` rows only):

```
== mozilla.org fetches=4
  about_missing ok=True observed='https://mozilla.org/en-US/about/' url=https://mozilla.org/
  about_unreachable ok=True observed='HTTP 200' url=https://mozilla.org/en-US/about/
  about_brand_missing ok=True observed='title: Learn about Mozilla; h1: Guard the Open Internet' url=https://mozilla.org/en-US/about/
== python.org fetches=4
  about_missing ok=True observed='https://python.org/about/' url=https://python.org/
  about_unreachable ok=True observed='HTTP 200' url=https://python.org/about/
  about_brand_missing ok=True observed='title: About Python™ | Python.org; h1: Python is powerful... and fast; \r\n    plays well with others; \r\n    runs everywhere; \r\n    is friendly & easy to learn; \r\n    is Open.' url=https://python.org/about/
```

Both About pages answer and name the brand: Mozilla in the title, Python
in the title (`About Python™`, matched through the alias). Neither home
nor About page carries an Organization node, so no `org_*` rows appear
and the fallback did not fire. Four fetches each: home, About, search,
SPARQL. python.org's first `<h1>` spans several lines, and `observed`
keeps its line breaks as written.

## 5. Deferred, by decision

- The description is not compared.
- The logo URL is not fetched.
- Wikipedia text is not read.
- Product, Article and BreadcrumbList schema are not checked.
- Fixed: duplicate Wikidata recs on a multi-domain brand. The audit
  still runs the Wikidata checks once per declared domain; the rule now
  merges the three brand-level ones. `wikidata_missing` gives at most one
  rec per brand (`subject_key` `wikidata:wikidata_missing`), and none if
  any domain matched an item, so nike.com matching an item while nike.in
  finds none no longer asks to create an item that exists. A domain with
  no Wikidata rows neither fires nor suppresses it.
  `wikidata_name_mismatch` and `wikidata_logo_missing` give one rec per
  item (`wikidata:<QID>:<code>`, QID from the check's `/wiki/Q…` url;
  any other url keeps `<domain>:<code>`). Evidence lists every reporting
  domain under `domains`. `social_links_conflict` stays per domain, since
  each site has its own `sameAs`.
  A rec dismissed under an old per-domain key stays dismissed, and the
  new brand-level key appears once as a new open rec, because refresh
  deletes only open rows.
- Only four social properties are compared (YouTube excluded: handle vs
  channel id). Host aliases are `x.com` for twitter.com and a leading
  `www.`, `m.` or `mobile.`.
- A brand whose item lacks P856 reads as `wikidata_missing`, which errs
  on the safe side.
- `/aboutique`-style paths count as an About link (prefix match), and an
  About section under another name (`/who-we-are/` on
  wikimediafoundation.org) does not.
- The cadence is weekly; the PRD asks for monthly.

**Open, found in this run.** When the only domain-verified candidate sits
on a subdomain, it still matches (wikimedia.org, section 3).
`wikidata_name_mismatch` is what flags it.

## 6. Spend

Unchanged: $9.2762 of the $15 cap. This run made no model calls.
