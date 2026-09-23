# Slice 8 findings: entity consistency audit

Date: 2026-09-23. Branch `slice8-entity-consistency`. Sources: a direct
call of `bsi_core.entity.audit_entity()` against real public domains
through `bsi_core.crawl.http_fetch` (the SSRF-guarded fetcher), plus a few
plain-HTTP probes of the same Wikidata API and home pages to explain what
the audit returned. Plain HTTP only: no model call, no spend, and nothing
written to the dev database. The dev tables were checked afterwards:
`recommendation`, `task` and `site_audit` held `0|0|0` rows.

## 1. What was measured, and how

The script from the plan, run with
`uv run python live_entity.py` from the repo root:

```python
from bsi_core.crawl import http_fetch
from bsi_core.entity import audit_entity

CASES = [
    ("mozilla.org", "Mozilla", ["Mozilla Foundation", "Mozilla Corporation"]),
    ("python.org", "Python Software Foundation", ["Python"]),
    # A brand that should not be on Wikidata.
    ("example.com", "Acme Rocket Widgets Pvt", []),
]
for host, name, aliases in CASES:
    a = audit_entity(host, name, aliases, [host], http_fetch, pause=0.5)
    print(f"\n== {host} ({name}) fetches={a.fetches}")
    for c in a.checks:
        print(f"  {'ok ' if c.ok else 'FAIL'} {c.severity:6} {c.code:24} {c.observed}")
```

Mozilla returned no Wikidata rows (section 3 says why), so a second run
used the same loop on the plan's fallbacks: `wikimedia.org` / "Wikimedia
Foundation" and `apache.org` / "Apache Software Foundation", both with no
aliases.

The run used the code as of `19c7b0a`, which leaves YouTube out of the
social comparison.

## 2. Results

A check that is not listed was skipped, not passed. The four `org_*` rows
need a schema.org Organization node on the home page, and none of these
five home pages has one: that gap is crawl's `org_schema_missing`, not an
entity finding. The four Wikidata rows are skipped when the Wikidata
answer can't be read.

### mozilla.org (Mozilla), fetches=3

| Check | Result | Severity | Observed |
|---|---|---|---|
| `website_schema_missing` | FAIL | low | 0 ld+json block(s) |
| `title_brand_missing` | ok | medium | Internet for people, not profit — Mozilla Global |
| `about_missing` | FAIL | low | no /about or /company link among 136 links |

No Wikidata rows (section 3).

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

### example.com (Acme Rocket Widgets Pvt), fetches=2

| Check | Result | Severity | Observed |
|---|---|---|---|
| `website_schema_missing` | FAIL | low | 0 ld+json block(s) |
| `title_brand_missing` | FAIL | medium | Example Domain |
| `about_missing` | FAIL | low | no /about or /company link among 1 links |
| `wikidata_missing` | FAIL | low | no search results |

Two fetches: an empty search skips the entities call, as designed.

### wikimedia.org (Wikimedia Foundation), fetches=3

| Check | Result | Severity | Observed |
|---|---|---|---|
| `website_schema_missing` | FAIL | low | 0 ld+json block(s) |
| `title_brand_missing` | FAIL | medium | Wikimedia |
| `about_missing` | FAIL | low | no /about or /company link among 22 links |

No Wikidata rows (section 3).

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

**Reading the home-page rows.**
- `title_brand_missing` on wikimedia.org is a true miss against the name
  as given. The title is "Wikimedia" and the brand is "Wikimedia
  Foundation"; the check asks whether the title contains a declared name,
  not the other way round. An operator who declares "Wikimedia" as an
  alias clears it.
- `about_missing` on mozilla.org is a false positive. A probe of the same
  home page found About links at `/en-US/about/`: the path starts with a
  locale, so the `/about` prefix test misses it.
- wikimedia.org's only About-like link is
  `https://wikimediafoundation.org/about/contact/`, on another host, so the
  failure is correct as designed.
- apache.org has no link containing "about" at all.

## 3. What the matching did

**Matched, by P856.**
- python.org: Q83818 "Python Software Foundation".
- apache.org: Q489709 "Apache Software Foundation".

In both cases the item's official website (P856) is on the declared host
and the English label equals the brand name, so every Wikidata check
passed. Neither home page has an Organization `sameAs`, so the social
comparison had nothing on the site side: "nothing to compare", not a
conflict.

**Rejected.** example.com: the search for "Acme Rocket Widgets Pvt"
returned nothing, so `wikidata_missing` fails with "no search results".

**Skipped: the Wikidata answer was cut off by the fetch cap.** For Mozilla
and Wikimedia the search succeeded and the entities call returned 200, but
`http_fetch` keeps only `BODY_CAP_BYTES` = 524288 bytes (512 KiB). A probe
of the same two calls printed:

```
Wikimedia Foundation ids= ['Q180', 'Q14827288', ...] entities body bytes= 524288 cap= 524288
Mozilla ids= ['Q698', 'Q169925', ...] entities body bytes= 524288 cap= 524288
```

The Mozilla body ends mid-string ("Unterminated string starting at: line 1
column 524287"). `json.loads` raises, and `audit_entity` skips every
Wikidata row, just as it would for a non-2xx answer. Q698 (Mozilla Firefox)
alone overflows the cap: a `wbgetentities` call for Q698 by itself failed
the same way. The ten-item search for a well-known brand pulls in its
largest items (products, licences), whose `claims` run to hundreds of
kilobytes. So the brands most likely to have a rich Wikidata item are the
ones that get no Wikidata checks, and nothing tells the operator. This is
a defect, not a design choice, and it is not fixed on this branch (see
section 5).

Had the answer been complete, Mozilla might still have matched the wrong item.
Wikidata's search order puts Q698 first, and a smaller probe of the three
Mozilla organisation items returned these P856 values:
- Q169925 Mozilla Corporation: `https://www.mozilla.org`
- Q9661 (no English label): `https://www.mozilla.org/en-US/`
- Q55672 Mozilla Foundation: `https://foundation.mozilla.org/`,
  `https://www.mozillafoundation.org`

Q698 was not measured. If Firefox's P856 is on mozilla.org, the first
domain-verified candidate would be the product, not the company. The
domain check proves the item is the site's, not that it is the brand's
organisation.

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

- The About page is not fetched, only linked. The prefix test also misses
  locale-prefixed paths such as mozilla.org's `/en-US/about/` (section 2).
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

**Found in this run, not fixed.** The 512 KiB fetch cap truncates the
`wbgetentities` answer for large brands, which skips all Wikidata checks
without saying so (section 3). A candidate that shares the brand's domain
can also be a product rather than the organisation.

## 6. Spend

Unchanged: $9.2762 of the $15 cap. This run made no model calls.
