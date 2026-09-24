# Plan: brand domains re-flag citation ownership

Spec: [../specs/2026-09-24-domains-reflag-citations-design.md](../specs/2026-09-24-domains-reflag-citations-design.md). Written after the build as a process fix; it records the plan approved in plan mode.

Branch `domains-reflag-citations` from `main` 14a7ac5. Implementers and reviewers run on Opus 5.5 with the model parameter omitted.

## Task 1: re-flag helper, routes and tests (one implementer, one reviewer)

1. Add `reflag_citations(s, brand_id)` to `packages/core/bsi_core/citations.py`: one bound UPDATE with the `is_owned` host rule that returns the changed row count and passes `mypy --strict`.
2. Call it in `apps/api/bsi_api/routers/brands.py`, in `create_domain` after the flush and in `delete_domain` after a flush.
3. Replace the comment in `competitors.py` that said the Overview flag and `k_cit` can differ after a domain change.
4. Add tests to `tests/integration/test_citations.py`, as listed in the spec.

## Task 2: findings note

Add a section to `docs/findings-slice12.md` with the limits: no bulk backfill, a narrow race with a running extraction, rival ownership read live, and suggested competitor domains skipping `is_public_hostname`.

## Finish

1. Run the full gate: backend (ruff, mypy, pytest with 100% metrics coverage) and web (`npm run gate`, with `npm run gen` producing no diff).
2. Final whole-branch review.
3. Present the finishing menu.
4. After merge, do the data step in the spec and verify it read-only on dev: Run 1's walkaroo.in citations are owned, and the citations table shows walkaroo.in as the brand and adidas.com and skechers.com as rivals.
