# Design: brand domains re-flag citation ownership

Written after the build, as a process fix: this change was planned in plan mode without the brainstorming skill, so no spec existed while it was built. The decisions below were each approved by the user in chat before implementation.

## Context

Run 1 (brand `BSOAgentTestBrand`) had no brand domain, and its competitors declared only their Indian hosts. The next step was to declare them:
- brand domain **walkaroo.in**, a real kids-shoe site cited 28 times in Run 1 and not a declared competitor;
- **adidas.com** on Adidas and **skechers.com** on Skechers, which Run 1 cites more often than their Indian hosts.

The API already accepts both (`POST /brands/{id}/domains`, `PATCH /brands/{id}/competitors/{cid}`), so declaring them is a data task. One gap blocks it: `citation.is_brand_owned` is set once, at extraction. A brand domain declared later never flags existing citations. The Overview citation rate, content gaps, recommendations and the URL optimizer's cited-URL list all read that flag.

Competitor ownership has no such gap: it is read live from `competitor.domains`.

## Design

- **`citations.reflag_citations(s, brand_id) -> int`**: one UPDATE recomputes `is_brand_owned` for every citation of that brand from its current `domain` rows. It uses the host rule of `matching.is_owned` (equal, or a dot then the host, no LIKE) and writes only rows whose flag changes. It runs in the tenant session, so RLS bounds it to the caller's org.
- **Both domain routes call it**: create after flushing the new row, delete after flushing the removal. A removed host un-owns its citations.
- **No new route or schema**, so the OpenAPI types don't change.
- **No bulk backfill**: stale flags on other brands are corrected on their next domain change. Run 1's are corrected by the data step itself.

## Data step (after merge)

With the API running the merged code:
1. Add walkaroo.in to Run 1 as its primary domain.
2. Set Adidas's domains to adidas.co.in and adidas.com.
3. Set Skechers's domains to skechers.in and skechers.com.

The worker is not started. Once it runs, it audits walkaroo.in and crawls the two new competitor hosts.

## Tests

Integration tests through the API cover:
- an exact host and a subdomain become owned;
- two lookalikes stay unowned;
- another brand in the same org is untouched;
- a second re-flag is a no-op;
- a delete clears the flags;
- deleting one of two domains keeps the other owned.
