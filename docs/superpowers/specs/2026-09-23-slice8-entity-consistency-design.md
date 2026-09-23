# Slice 8 design: entity consistency audit (PRD F08, first cut)

## Context

Slices 1–7 measure a brand in AI answers, recommend actions, and audit the
brand's site for crawlability. Nothing yet checks whether the brand is a
*consistent entity*: whether its own schema.org markup names it the way the
operator does, whether it links its social profiles, and whether a public
knowledge source (Wikidata) agrees. PRD F08 asks for an editable entity
graph, a cross-source consistency audit (website, About page, LinkedIn,
Crunchbase, G2, Capterra, Wikipedia/Wikidata) and schema.org checks.
Decisions made in brainstorming:

- **Scope:** the brand's site, its schema.org Organization markup, and
  Wikidata. No entity graph, no LinkedIn/Crunchbase/G2/Capterra (bot-blocked
  and against their terms), no About-page fetch. Each can be a later slice.
- **Truth source:** brand name, aliases and declared domains from the brand
  record. Everything else (logo, socials) is cross-source agreement. No new
  brand fields, no editor.
- **Wikidata match:** automatic by name search, accepted only when the
  item's official website (P856) host is a declared domain. Never a guess.
- **Structure:** lives *inside* the existing crawl audit. A new module
  `entity.py` produces `Check`s; `run_crawl_audit` appends them to the same
  `site_audit` row; the `_crawl` rule emits a new recommendation type
  `fix_entity` for entity families. Migration 0013 only widens the rec-type
  constraint. No new table, job kind, endpoint or tab. Cadence is therefore
  weekly plus on demand (the PRD asks for monthly; weekly is a superset).

Nothing spends money: three extra HTTP fetches per declared domain per week.

## Design

### A. Checks — `bsi_core/entity.py`

`audit_entity(host, brand_name, aliases, hosts, fetch: Fetch, *, pause=0.0)
-> Audit`. Same `Audit(checks, fetches)` NamedTuple and `Check(code, ok,
severity, observed, expected, url)` dataclass as `crawl.py`. Pure; unit
tested from canned `Response`s; never raises.

**Parser reuse.** Promote `crawl._Head` → `crawl.Head` (a second module
now uses it). `Head` gains `links: list[str]` (every `<a href>` value),
nothing else. JSON-LD nodes are walked in `entity.py` itself, since the
checks need the nodes, not just their types.

**Name normalisation.** `_norm(s)`: casefold, keep alphanumerics only. A
name "matches the brand" when `_norm(name)` is in
`{_norm(brand_name)} | {_norm(a) for a in aliases}`.

**Organization node.** The first JSON-LD node (recursing `@graph`) whose
`@type` set intersects `ORG_TYPES = {Organization, Corporation,
LocalBusiness, OnlineBusiness, NGO, EducationalOrganization,
GovernmentOrganization, SportsOrganization, MedicalOrganization}`.

**From the home page** (`https://{host}/`, browser UA, 1 fetch). If the
home fetch is not 2xx, all home checks are skipped (slice 7 already emits
`home_unreachable`). If there is no Organization node, the `org_*` rows are
skipped (slice 7 emits `org_schema_missing`, high).

| Code | Severity | Fails when | observed |
|---|---|---|---|
| `org_name_mismatch` | high | Organization `name` does not match the brand | the name |
| `org_url_mismatch` | medium | Organization `url` host (via `matching.normalize_domain`) is not owned by a declared domain (`matching.is_owned`, so a subdomain counts); missing `url` also fails | the url or "absent" |
| `org_logo_missing` | medium | no `logo` (accept a string, an object with `url`, or a list of either) | "absent" |
| `org_sameas_missing` | medium | `sameAs` absent or empty (accept string or list) | "absent" |
| `website_schema_missing` | low | no node with `@type` `WebSite` in any block | "N ld+json block(s)" |
| `title_brand_missing` | medium | normalised `<title>` does not contain the normalised brand name or any alias | the title (clipped) |
| `about_missing` | low | no `<a href>` that resolves (`urllib.parse.urljoin` against the home URL) to the same host with a path starting `/about` or `/company`, optionally under one locale segment (`/en/`, `/en-US/`, `/en_GB/`), case-insensitive | "no /about or /company link among N links" |

**From Wikidata** (2 fetches, both through `http_fetch`, user agent
`bsi-platform/0.1 entity-audit (+https://github.com/aiagencyindia-lab/bsi-platform)`):

1. `https://www.wikidata.org/w/api.php?action=wbsearchentities&search={brand_name}&language=en&type=item&limit=10&format=json`
2. `https://query.wikidata.org/sparql?format=json&query={urlencoded}`,
   only if step 1 yielded ids. One SPARQL query returns one row per
   candidate (`VALUES ?item { wd:Q1 wd:Q2 … }`, `GROUP BY ?item`): the
   English label and the `mul` ("default for all languages") label, a
   count of P154 values, and the P856 and social-property
   values each joined by tabs. It replaced `wbgetentities`, which returns
   every claim of every candidate: for large brands (Mozilla, Wikimedia
   Foundation) ten items passed `http_fetch`'s 512 KiB body cap, the JSON
   was cut off and every Wikidata check was skipped (findings-slice8 §3).
   An aggregate with no values is left out of the row and reads as empty.
   The label used is English, else `mul`: many items (Q180 Wikimedia
   Foundation, Q9661 Mozilla) now carry only a `mul` label.

**Id validation.** Search ids go into the query text, so only ids that
fully match `Q[0-9]+` are kept; the rest are dropped. If none remain, the
search counts as empty.

Match: among candidates with any P856 value whose host
(`normalize_domain`) is owned by a declared domain (`is_owned`), rank each
by its best owned P856 URL: exact host (equal to a normalised declared
host) with an empty or `/` path, then exact host, then subdomain root, then
subdomain. Ties keep search order. A product item can list a page on the
brand's domain (`mozilla.org/MPL/`), and a project a subdomain
(`foundation.wikimedia.org`); the ranking keeps both from beating the
organisation. A subdomain item still matches when it is the only
domain-verified candidate. For either call, a non-2xx status, a
`json.loads` failure or an unexpected shape skips **all** Wikidata checks
(fetches still counted) and logs a warning on `bsi.entity` naming the host
and the reason. A search that returns zero valid ids fails
`wikidata_missing` with observed "no search results".

| Code | Severity | Fails when | observed |
|---|---|---|---|
| `wikidata_missing` | low | no domain-verified candidate | "candidates: Q1 Label, Q2 Label …" (clipped) or "no search results" |
| `wikidata_name_mismatch` | medium | matched item's `labels.en.value` does not match the brand | "Q123: Label" |
| `wikidata_logo_missing` | low | matched item has no P154 | "Q123" |
| `social_links_conflict` | medium | see below | "on Wikidata only: …; on site only: …" |

The three matched-item checks are emitted only when a match exists; a match
passes `wikidata_missing` with observed "Q123: Label".

**Social profiles.** Wikidata `SOCIAL_PROPS`: P2002 → `twitter.com/{v}`,
P2013 → `facebook.com/{v}`, P2003 → `instagram.com/{v}`, P4264 →
`linkedin.com/company/{v}`. YouTube is left out: a site's `sameAs`
usually holds `youtube.com/@handle`, which never equals Wikidata P2397's
`youtube.com/channel/<id>`, so comparing them raised false conflicts. Site
side: `sameAs` URLs whose host, without `www.` and with `x.com` read as
`twitter.com`, is one of those four. Both sides normalised to `host + path`,
lowercase, no `www.`, no trailing slash, then compared as sets. Conflict
when the sets differ **and both are non-empty**; if one side has no socials
at all, `org_sameas_missing` or Wikidata's own incompleteness covers it and
no conflict is raised. Passing observed: "N profiles agree".

**Constants.** `entity.SEVERITY` and `entity.EXPECTED` keyed by family,
mirroring `crawl`. Every `EXPECTED` string ends with "This is an
optimisation signal, not a promised outcome." (The copy test forbids the
word "guarantee" anywhere in recommendation text.) `entity.FAMILIES =
frozenset(SEVERITY)`.

**Fetch order and count.** Home (1), search (1), SPARQL (0 or 1).
With `pause` set, the entity audit sleeps before every one of its fetches,
since it always follows `audit_domain`'s fetches to the same host. Per
domain: 12 + 3 = 15.

### B. Worker — `apps/workers/bsi_workers/worker.py`

`run_crawl_audit` reads `brand.name`, `brand.aliases` and all hosts in its
first tenant session. Per host, with no transaction open:
`a = audit_domain(host, fetch, pause=…)` then
`e = audit_entity(host, name, aliases, hosts, fetch, pause=…)`. A crash in
`audit_domain` skips the host, as today (no row, so the domain stays due).
A crash in `audit_entity` is logged and read as `Audit([], 0)`, so the
crawl checks are still stored. Store one `SiteAudit(checks=[asdict(c) for c in a.checks +
e.checks], fetches=a.fetches + e.fetches)`. `refresh()` at the end as
today. Nothing else in the worker changes: same job kind, same
`JOB_ESTIMATES`, same `queue_due_crawl_audits`.

### C. Rule and recommendation — `bsi_core/recommend.py`, `models.py`

- `REC_TYPES` gains `fix_entity` (six types). `FEASIBILITY["fix_entity"] =
  0.7` (site markup is easy, Wikidata edits less so).
- `_crawl`: for each failing check, `fam = family(code)`. If `fam in
  entity.FAMILIES` → type `fix_entity`, severity and expected from
  `entity`, copy from `entity_copy`. Elif `fam in crawl.SEVERITY` → as
  today. Else skip with a warning (unchanged). `subject_key` stays
  `f"{domain}:{code}"`, reach 1.0, pressure `PRESSURE_BY_SEVERITY[sev]`.
- `_ENTITY_TITLES` per family, e.g. `org_name_mismatch`: "Fix the
  Organization name on {domain}"; `wikidata_missing`: "Create or claim
  {brand}'s Wikidata item"; `social_links_conflict`: "Align social profiles
  between {domain} and Wikidata".
- `entity_copy(brand, domain, check) -> (title, body)`. Body: "The weekly
  audit of {url} observed: {observed}. Expected: {expected} Engines resolve
  a brand to one entity by agreement between its site markup and public
  knowledge sources; a disagreement makes {brand} harder to identify and
  cite. Metric to watch: this check on the next weekly audit, then the
  mention rate."
- `routers/recommendations.py`: `NO_IMPACT` gains `fix_entity` (accepted
  tasks do not measure impact, as for `fix_crawlability`).

### D. Migration `0013_fix_entity_rec_type.py`

Copy `_rec_type_check` from 0012. Upgrade: recreate
`ck_recommendation_type` with six values. Downgrade: delete tasks whose
recommendation has type `fix_entity`, delete those recommendations, restore
the five-value constraint. No table or function changes.

### E. API — `apps/api/bsi_api/schemas.py`

Routes unchanged. `CheckOut.severity` stays
`Literal["high", "medium", "low"]` and gains a `field_validator(mode=
"before")` that maps any other stored value to `"low"`, closing the
deferred 500 on an unknown severity. `SiteAuditOut` unchanged. The OpenAPI
document should not change; if `gen:check` differs, regenerate and stage.

### F. Web — `apps/web/src/lib/format.ts`

`KIND` gains `fix_entity: "Entity fix"` so the Recommendations and Tasks
pages label it. The Site page is unchanged: entity rows appear in the same
table. The frontend computes nothing.

### Testing

**Unit** — `tests/unit/test_entity.py`, fake `Fetch` keyed by URL returning
canned `Response`s, no network:

- All-pass fixture: real-shaped JSON-LD with Organization and WebSite in
  `@graph`, `sameAs` to twitter and linkedin, a `/about` link; Wikidata
  search returns two candidates, the first an impostor (P856 on another
  domain), the second matching with the same socials. Every check ok,
  `fetches == 3`.
- Each check failing alone (parametrised by mutating the fixture).
- Name normalisation: "Acme, Inc." vs alias "acme inc"; case; unicode.
- `url` with `www.` and trailing slash matches the bare host.
- Logo as string, ImageObject and list; `sameAs` as a string.
- `Corporation` counts as Organization.
- No Organization → no `org_*` rows, other rows present.
- Home non-2xx → no home rows, Wikidata rows present, `fetches == 3`.
- Wikidata search 500, bad JSON, or empty → skipped vs `wikidata_missing`
  per spec; SPARQL failure → skipped; fetches counted each time.
- `x.com` in `sameAs` equals Wikidata twitter; social conflict in each
  direction; one side empty → no conflict.
- `about_missing` with relative, absolute same-host and other-host links.

**Integration:**

- `test_crawl_audit.py`: `run_crawl_audit` stores crawl and entity checks
  in one row with `fetches` summed; an entity crash does not lose the crawl
  checks.
- `test_recommend.py`: failing entity checks → one `fix_entity` rec each
  with priority `round(1.0 * pressure * 0.7, 4)`; crawl recs unchanged;
  unknown family still skipped; `top_by_type` with six types.
- Recommendations/tasks API: accepting a `fix_entity` rec creates a task
  with `measures_impact` false.
- `test_api_audits.py`: a stored severity `"weird"` → 200 with `low`.
- Migration 0013 downgrade deletes `fix_entity` recs and their tasks.
- `test_rls.py` / `test_isolation.py`: no new tables or routes, unchanged.

Expectations are computed from the canned data, never guessed.

### Live check (no spend)

A throwaway script in the scratchpad calls `audit_entity` for two real
domains with a fabricated brand record: one brand present on Wikidata with
social claims, one absent. It prints the checks and writes nothing to the
database, so the dev `recommendation`, `task` and `site_audit` tables stay
empty. Results go into `docs/findings-slice8.md`.

## Files touched

- `packages/core/bsi_core/crawl.py` (promote `Head`, `ld_types`; collect
  links), `entity.py` (new), `models.py`, `recommend.py`
- `migrations/versions/0013_fix_entity_rec_type.py` (new)
- `apps/workers/bsi_workers/worker.py`
- `apps/api/bsi_api/schemas.py`, `routers/recommendations.py`
- `apps/web/src/lib/format.ts`
- `tests/unit/test_entity.py` (new); `tests/integration/test_crawl_audit.py`,
  `test_recommend.py`, `test_api_audits.py`, recommendations/tasks API tests
- `docs/README.md`, `docs/findings-slice8.md`, this spec, the plan

## Out of scope, by decision

- Editable entity graph (`entity_node` / `entity_edge`), seeding, editor UI.
- LinkedIn, Crunchbase, G2, Capterra, directories: bot-blocked or paid.
- Fetching the About page or the logo URL; comparing descriptions;
  Wikipedia article text; Product, Article, BreadcrumbList schema.
- Caching the Wikidata search across a brand's domains (repeated per
  domain; cheap).
- Social properties beyond the four listed (YouTube excluded: handle vs
  channel id); `x.com` is the only host alias.

## Risks

- **Wrong Wikidata match.** Guarded by the P856 domain check; a brand whose
  item lacks P856 reads as `wikidata_missing` (low), which is the safe
  direction.
- **Wikimedia rate limits.** Two calls per domain per week with a
  descriptive user agent is far below any limit; failures skip, not fail.
- **Crowding.** A site with no Organization node produces one high crawl rec
  and no entity rows; a site with a bad node produces up to four entity recs.
  Acceptable; the type-diverse top three keeps the list readable.
- **Longer audits.** 15 fetches instead of 12 per domain; the 0.5 s pause
  adds about 1.5 s per domain. Negligible for a weekly job.
