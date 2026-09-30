# Slice 25 design: store the raw keyword samples and the raw rewrite

## Context

`run_products` (`packages/core/bsi_core/products.py`) throws away two things every live check has needed: the three keyword-prompt sample lists that each product's `choose_keywords` call received, and the rewrite call's title before `rule_check`. Because of that, the findings for slices 23 and 24 mark every statement about which sample offered a keyword, or which words the rule check removed, as *inferred* (docs/findings-slice23.md §2 "The raw samples of those runs were not stored", §3 "the raw samples are not stored, so which path is not known"; docs/findings-slice24.md §2 "*Inferred*: the rewrite call varies between runs" and its *inferred* note on the `keywords` lists). Slice 23's out-of-scope list names "Storing the raw keyword samples or the raw rewrite" (docs/findings-slice23.md §4).

Classification, said in chat as the first line of the first brainstorming reply: **architectural** — "it adds columns (migration 0021) and touches the run loop, the API schema and the docs, so it gets the full spec-and-plan process like slices 22–24." (After the visibility decision below, the API schema is untouched.)

Decisions approved in chat (brainstorming on Fable 5.1, 2026-09-30). Sections 1 to 4 each had their design text in chat before their approval:

- **Visibility:** database only. Read with psql during live checks. No API, web or CSV change. Rejected: exposing the fields on `GET /v1/brands/{id}/products`; exposing them there and in the Products tab and `export.csv`.
- **Retention:** latest run only, two columns on `product` with the lifetime of `keyword`, `suggested_title` and `dropped_words`. Rejected: a table keyed by (product, job) that keeps every run.
- **Approach 1:** `keyword_samples` JSONB and `raw_title` text on `product`, migration 0021. Rejected: stashing both in `job.params`.
- **Testing:** the user added a JSONB round-trip test to §2.

Codebase facts (main `0f6824c`, checked 2026-09-30):

- Per batch, `run_products` calls `generator(keyword_prompt(brand.name, batch), KeywordSet, KEYWORD_TEMPERATURE)` `SAMPLES` (3) times and builds `samples: list[dict[int, list[str]]]`, one dict per sample mapping a product's batch index to its keywords after `_clean` (casefold, whitespace collapsed; blank strings dropped). A product's `choose_keywords` input is `[sm.get(i, []) for sm in samples]`, a list of three lists.
- The first per-batch UPDATE writes `keyword` and `keywords`; when a product has no keyword it also writes the R13 `cleared` dict (`missing_keywords`, `suggested_title`, `suggested_bullets`, `rule_check`, `dropped_words` to NULL; `job_id`, `result_at`).
- The rewrite step calls `generator(rewrite_prompt(brand.name, kept), RewriteSet, 0.0)` once per batch; per product `suggestion = (item.title.strip() if item else "") or p["title"]`, then `rule_check(p["title"], suggestion, names, allowed=[*p["backing"], *p["missing"]])`; the second UPDATE writes `missing_keywords`, `suggested_title`, `suggested_bullets`, `rule_check`, `dropped_words`, `job_id`, `result_at`. `suggestion` is not stored.
- `Product` (`packages/core/bsi_core/models.py`) has no JSONB result column; `Base.type_annotation_map` maps `dict[str, Any]` to `JSONB` and `list[str]` to `ARRAY(Text)`, so a `list[list[str]]` column must name its type. `Job` has no result column.
- Migration `0020_product_review.py` is the latest; `product` already has RLS from `_protect("product")` in 0019, which covers new columns.
- The test database is built by `alembic upgrade head` (`tests/conftest.py`), so the new migration runs in every suite.
- In `tests/integration/test_products_run.py`, `_generator(...)` answers every keyword call with `(by_index or {}).get(i) or keywords or ["kids sandals", "walkaroo kids"]` per product index, and every rewrite call with `rewrite or "Walkaroo Kids Summer Sandals Sandals"` for every index in the prompt; it cannot omit an index. `_seed(owner, org, bid, n, description=None)` writes products titled `Walkaroo Boys Sandal {i}`.
- `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked` asserts `p.suggested_title == "Walkaroo Kids Summer Sandals"` and `(p.rule_check, p.dropped_words) == ("review", ["boys"])` for `_seed(..., 3, description="Summer sandal")`. `test_a_product_whose_keyword_drops_loses_its_old_suggestion` seeds a product with `keyword="kids sandals"`, `suggested_title="Old"`, runs with `_generator(keywords=["walkaroo sandals"])` (a brand term, so no keyword) and asserts `keyword`, `suggested_title`, `rule_check`, `missing_keywords` and `dropped_words` are NULL and `job_id` is the new job. `test_the_database_accepts_review_and_rejects_an_unknown_status` writes columns through the `owner` fixture (after `_seed`) and reads them back.

## Design

Changes: one migration, two ORM columns, a few lines in `run_products`, tests. No API, web, prompt or copy change.

### 1. Storage and writes

`migrations/versions/0021_product_raw.py` (`revision = "0021"`, `down_revision = "0020"`):

```python
def upgrade() -> None:
    op.add_column(
        "product",
        sa.Column("keyword_samples", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.add_column("product", sa.Column("raw_title", sa.Text()))


def downgrade() -> None:
    op.drop_column("product", "raw_title")
    op.drop_column("product", "keyword_samples")
```

No constraint, index or `_protect` call: the table is already protected.

`Product` in `packages/core/bsi_core/models.py`, after `dropped_words`:

```python
    # The three keyword-prompt sample lists choose_keywords received
    # (after _clean), and the rewrite call's title before rule_check
    # (slice 25). Read with psql; not exposed by the API.
    keyword_samples: Mapped[list[list[str]] | None] = mapped_column(JSONB)
    raw_title: Mapped[str | None]
```

`run_products`:

- Keyword step: the per-product loop keeps what it hands to `choose_keywords`, `p["samples"] = [sm.get(i, []) for sm in samples]`, and passes `p["samples"]` to `choose_keywords`. The first UPDATE adds `keyword_samples=p["samples"]` next to `keyword` and `keywords`. It is written for every product in the batch, a product that ends with no keyword included: that is the case a live check needs to explain. `keyword_samples` is not in `cleared` because the same statement always sets it.
- Rewrite step: `title_in = item.title.strip() if item else ""`; `p["raw_title"] = title_in or None`; `suggestion = title_in or p["title"]` (the same value as today; `raw` is not reused, it already names the model JSON). The second UPDATE adds `raw_title=p["raw_title"]`.
- R13: `cleared` gains `"raw_title": None`, so a product that loses its keyword loses its old raw rewrite with its old suggestion.
- If a batch fails after its keyword write (`OverBudget` before the searches, or a `JudgeFailed` in the search, titles or rewrite step), a product with a keyword has `keyword_samples` from the failed run and `raw_title` from the last finished one, as with `keyword` and `suggested_title` today; `job_id` tells them apart.

Not stored: `p["backing"]`, the raw model JSON, the bullets before trimming.

### 2. Testing

All in `tests/integration/test_products_run.py`, fake generator, no model call.

- `_generator` gains `skip_rewrite=()`: product indexes left out of the rewrite body. Callers that do not pass it are unchanged.
- `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked` also asserts `p.keyword_samples == [["kids sandals", "walkaroo kids"]] * 3` and `p.raw_title == "Walkaroo Kids Summer Sandals Sandals"` (the stored raw title differs from the checked `suggested_title`, "Walkaroo Kids Summer Sandals").
- `test_a_product_whose_keyword_drops_loses_its_old_suggestion` seeds `raw_title="Old raw"` on its product and also asserts `p.raw_title is None` and `p.keyword_samples == [["walkaroo sandals"]] * 3` after the run.
- New test, `test_a_product_without_a_rewrite_keeps_its_title_and_no_raw_title`: `_seed(owner, org, bid, 1)`; `gen = _generator(skip_rewrite={0})`. After `_run`: `p.raw_title is None`, `p.suggested_title == "Walkaroo Boys Sandal 0"`, `(p.rule_check, p.dropped_words) == ("pass", [])`, `p.suggested_bullets == []`.
- New test, `test_keyword_samples_round_trip`: through the `owner` fixture (as `test_the_database_accepts_review_and_rejects_an_unknown_status`), add a product with `keyword_samples=[["kids sandals", "men’s chappals"], [], ["bübchen sandalen"]]` and `raw_title="Kids Sandals — Summer"`, read it back in a new session and assert both values are equal to what was written.

Unchanged: `tests/unit`, `tests/unit/test_recommend_copy.py` fixtures, `test_rls.py` and `test_isolation.py` (no new table or route), `ProductOut`, `EXPORT_COLUMNS`, the Products page, `apps/web/openapi.json` and `schema.d.ts` (no `npm run gen`).

### 3. Dev migration and re-check

Both run by the controller only with the user's OK at that point.

- Migration: `uv run alembic upgrade head` on dev takes it from 0020 to 0021. Rollback: `uv run alembic downgrade 0020`, which drops the two columns and nothing else.
- Re-check: one `product_run` by the live-check pattern (API queued, `process_job` once, the worker loop never started). The 9 fresh valid `keyword_search` rows listed in the slice 24 spec §3 (7 plural spellings and "navy flip flops" searched 2026-09-29 13:10:34 UTC, "mens flip flops" 2026-09-30 09:27:13 UTC) last until 2026-10-06 13:10 and 2026-10-07 09:27 UTC, so if the model votes the cached spellings again there is no grounded search. Expected cost about 6,400 micros (3 keyword calls and 1 rewrite call; slice 24's re-check measured 6,407 for the same 4 calls), plus about 38,000 per keyword whose key has no fresh valid row. Writes: the job, 10 product rows, `api_key.last_used_at`, any new `keyword_search` row.
- Read-back with psql, per LC-01..LC-10: `keyword`, `keyword_samples`, `raw_title`, `suggested_title`, `dropped_words`. The findings state, as observed, which sample offered each stored keyword and what the rule check removed. This is the first live check that can say so; anything it shows about keyword choice is recorded in findings, not changed in this slice.

### 4. Docs

- `docs/findings-slice25.md`: the re-check table, every `minor (deferred)` and `parked` ledger line quoted as recorded, the open list carried forward (stale duplicate `keyword_search` rows, the seed's untested `error` filter and newest-wins, the judge-agreement question).
- `docs/README.md`: rows for this spec, its plan and its findings.
- `docs/findings-slice24.md`: the two "(this commit)" notes (the commit table in §1 and the §3 note "recorded in §2 (this commit)") become "e315b44", the hash of that docs commit.
- `docs/findings-slice23.md` §4: the line "Storing the raw keyword samples or the raw rewrite." gets a nested bullet under it, "  - Done in slice 25." (the form the findings files use for notes); the line itself is not edited.

## Rulings

None.

## Out of scope

- Exposing `keyword_samples` or `raw_title` through the API, the Products tab or `export.csv`.
- Storing `backing`, the raw model JSON, the untrimmed bullets, or any history across runs.
- Deleting stale duplicate `keyword_search` rows; the seed's untested filters; the judge-agreement labels.
- The deferred minors in docs/findings-slice23.md §4 and docs/findings-slice24.md §3.
