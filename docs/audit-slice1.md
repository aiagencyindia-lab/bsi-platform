# Slice 1 audit: every task checked step by step

On 2026-09-19, after slice 1 was built and passed review, every task was
re-checked against the plan
(`superpowers/plans/2026-09-19-slice1-measurement-core.md`). Each check ran
in a throwaway checkout with a throwaway database:

1. Diff each file against the plan's code, ignoring formatting and import order.
2. Replay the red → green steps.
3. Run the gate (ruff, format, mypy, pytest) at each of the task's commits.
4. Probe edge cases the tests don't cover.

Every defect found was fixed test-first and committed.

## Results by task

| Task | Built as planned? | Found by the audit | Fix |
|---|---|---|---|
| 1 Skeleton, Postgres, settings | Yes. Two approved extras: `.superpowers/` ignore and a ruff `docs` exclude | The README spec link pointed at a git-ignored folder. Already fixed in the final review | — |
| 2 Models, RLS, sessions | Yes. Typing and formatting only. Its fix round added the `observation.status` CHECK (migration 0003) | Grants, the NULLIF policy, function ACLs, and the 0003 up/down round-trip all verified in the database | — |
| 3 Matcher, Wilson | Yes. Its fix round fixed Devanagari tokens, bare domains and the curly-apostrophe test | Wilson bounds were off by float rounding at k=0 and k=n for 73 of the sample sizes up to 200 (e.g. `ci_low=2.8e-17`) | `7fea449` |
| 4 API foundation, CRUD | Yes | **A failed commit was reported as 200 while the write was lost** (the session committed after the response was sent). Also, an explicit `null` in a PATCH body gave 500 | `9aa5cd7` |
| 5 Runs, jobs | Yes | **Runs above 8,191 observations failed** (Postgres's 65,535 bind-parameter limit). Archived brands could still be run. Unknown fields were silently ignored | `d4d9b88` |
| 6 Gemini adapter, raw store | Yes, with typing-only changes | **Grounding was mispriced:** $14 per 1k flat per answer is Gemini 3's price per search query. Gemini 2.5 Flash is $35 per 1k grounded prompts, after 1,500 free per day. The findings cost section was wrong by 2–3× | `6d281a0` |
| 7 Extraction | Yes, with ruled deviations. The genai client GC fix was real: `Client.__del__` closes the connection | Nothing new. Name variants lost 0 of 50 labels in the live run. Of the 121 model-only notes, 105 were tracked brands the answer never named and 16 were untracked brands | — |
| 8 Worker | Yes. Its first commit was flaky (4 of 20 runs failed on host-vs-DB clock skew); fixed in its fix round (0 of 20) | **Retries gave up after 6 s of 429s**, but Vertex quotas reset per minute. Brands archived after their run was queued were still queried and billed | `c28a06f` |
| 9 Metrics, endpoints | Yes | Nothing new. All five metrics, average position and per-entity mentions matched a recomputation from the stored rows exactly | — |
| 10 Isolation sweep | Yes | **With RLS turned off on 6 tables (domain, competitor, prompt, extraction, mention, citation), no test failed.** The API didn't leak, but the database guarantee was untested | `8d4e8e4` |
| 11 Live run, benchmark, findings | Yes | The findings run time was 22m07s; the real figure is 21m54s (the end timestamp was when `/metrics` was read). Everything else matched the database | `2f78f51` |

## How the Task 10 fix was proven

RLS was turned off on one table at a time and the RLS and isolation tests
were re-run each time. Before `8d4e8e4`, 6 of the 13 tables failed no test.
After it, all 13 fail at least 2 tests. The table list is also checked
against every table in the schema that has an `org_id` column, so a new
tenant table can't be left out.

## Still open (minor, recorded, not fixed)

- `parse()` raises on a response part that isn't a dict. The SDK never produces one.
- A deleted raw file returns 500 from `/observations/{id}/raw`, instead of 404.
- An unknown `status` filter on `/observations` returns `[]` instead of 422.
- A date without a timezone is read as UTC.
- A duplicate model judgement for one entity is dropped without a note.
- An entity name containing `</answer>` gets past the prompt delimiter. Names are entered by the tenant, so a tenant can only affect its own labels.
- A raw file is left behind when extraction fails on every attempt.
- The SOV denominator drops competitors that were hard-deleted.
