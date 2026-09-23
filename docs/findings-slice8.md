# Slice 8 findings: entity consistency audit

Date: 2026-09-23. Branch `slice8-entity-consistency`. Sources: direct
calls of `bsi_core.entity.audit_entity()` against five real public domains
through `bsi_core.crawl.http_fetch` (the SSRF-guarded fetcher), plus a few
plain-HTTP probes of the same Wikidata endpoints and home pages to explain
what the audit returned. Plain HTTP only: no model call, no spend, and
nothing written to the dev database. Afterwards the dev tables
`recommendation`, `task` and `site_audit` held `0|0|0` rows.

The audit ran three times. The first run exposed a defect that skipped
every Wikidata check for large brands, fixed on this branch in `b67cf8f`
(section 3). The second run caught a gap in that fix before it was
committed. The results below come from the third run. A fourth run on the
committed code (`b67cf8f`) printed the same output except for one line:
Mozilla's About link came back as `/en-GB/about/` rather than
`/en-US/about/`, because mozilla.org picks the locale per request.

## 1. What was measured, and how

Run with `uv run python live_entity.py` from the repo root:

```python
import logging
from bsi_core.crawl import http_fetch
from bsi_core.entity import audit_entity

logging.basicConfig(level=logging.WARNING, format="LOG %(name)s %(message)s")
CASES = [
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
run returned no Wikidata rows for Mozilla. The third run logged no
warnings.

## 2. Results

A check that is not listed was skipped, not passed. The four `org_*` rows
need a schema.org Organization node on the home page, and none of these
five home pages has one: that gap is crawl's `org_schema_missing`, not an
entity finding.

### mozilla.org (Mozilla), fetches=3

| Check | Result | Severity | Observed |
|---|---|---|---|
| `website_schema_missing` | FAIL | low | 0 ld+json block(s) |
| `title_brand_missing` | ok | medium | Internet for people, not profit — Mozilla Global |
| `about_missing` | ok | low | https://mozilla.org/en-US/about/ (fourth run: https://mozilla.org/en-GB/about/) |
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
  are now accepted (section 3), and the second run found the link.
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
| wikimedia.org | Q57077840 "Wikimedia Foundation Governance Wiki" | P856 `https://foundation.wikimedia.org/`, a subdomain |

For Mozilla, the SPARQL probe listed each candidate's P856 in search
order:
- Q698 Mozilla Firefox: `https://www.firefox.com`, rejected (another
  domain).
- Q169925 Mozilla Corporation: `https://www.mozilla.org`, root, matched.
- Q308915 Mozilla Public License: `https://www.mozilla.org/MPL/`, on the
  domain but not the root.
- Q9661 (no English label): `https://www.mozilla.org/en-US/`.
- Q3273508 MDN Web Docs: `https://developer.mozilla.org/`.

Firefox is not the risk it looked like, since its site is firefox.com.
The root preference guards against Q308915 or Q9661 appearing first.

**Wikimedia matched the wrong item.** Q180, the Wikimedia Foundation
itself, lists P856 `https://wikimediafoundation.org/`, so the declared
domain wikimedia.org does not verify it. Q57077840 lists
`https://foundation.wikimedia.org/`, a subdomain of wikimedia.org, and
`is_owned` counts subdomains. It matched, and `wikidata_name_mismatch`
failed against its label, which is the check doing its job.

The case itself was chosen badly: the Foundation's own site is
wikimediafoundation.org. It does show that a subdomain's item can verify
against the parent domain.

**English labels.** Q180 and Q9661 have no English label, only a `mul`
("default for all languages") label: "Wikimedia Foundation" and "Mozilla".
Had either been matched, `wikidata_name_mismatch` would have failed with
"no English label", although the label reads as the brand.

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

## 5. Deferred, by decision

- The About page is not fetched.
- The description is not compared.
- The logo URL is not fetched.
- Wikipedia text is not read.
- Product, Article and BreadcrumbList schema are not checked.
- The Wikidata search repeats for each declared domain, so a two-domain
  brand gets two `wikidata_missing` recs.
- Only four social properties are compared (YouTube excluded: handle vs
  channel id), and `x.com` is the only host alias.
- A brand whose item lacks P856 reads as `wikidata_missing`, which errs
  on the safe side.
- `/aboutique`-style paths count as an About link (prefix match).
- The cadence is weekly; the PRD asks for monthly.

**Open, found in this run.**
- An item whose P856 sits on a subdomain of a declared domain is
  domain-verified (Wikimedia, section 3).
- Items that carry only a `mul` label read as "no English label".

## 6. Spend

Unchanged: $9.2762 of the $15 cap. This run made no model calls.
