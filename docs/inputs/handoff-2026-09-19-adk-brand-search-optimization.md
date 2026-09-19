# Handoff: Brand Search Optimization agent

> Provided at the start of the 2026-09-19 session that built this repo. It
> describes the ADK demo app (`brand-search-optimization`) that this
> platform grew out of. Reproduced as given.

## 1. Project overview

**What it is:** a Google **ADK (Agent Development Kit) multi-agent app** that audits e-commerce product titles. The user types a brand name, and the app:
1. reads that brand's products from **BigQuery**,
2. works out which generic keywords shoppers would search for,
3. finds which competitor products currently rank for the top keyword,
4. writes a side-by-side report of missing keywords with suggested rewritten titles.

The whole pipeline runs in **one chat turn**.

**Origin:** it started as `google/adk-samples` → `python/agents/brand-search-optimization`. We fixed it heavily, extracted it into a **standalone repo**, deployed and tested it on Vertex AI Agent Engine, and pushed it to GitHub.

**The goal so far:** make it actually run, make it reliable, make its tests mean something, document it, deploy it, and publish it. All of that is done.

**Tech stack** (as installed in `.venv`):

| Component | Version |
|---|---|
| Python | 3.13.11, managed by `uv` (0.9.x) |
| google-adk | 1.32.0 |
| google-genai | 1.75.0 |
| google-cloud-aiplatform | 1.164.0 |
| google-cloud-bigquery | 3.41.0 |
| selenium | 4.49.0 |
| webdriver-manager | 4.1.2 |
| pydantic | 2.12.5 |
| pytest | 9.0.3 (plus pytest-asyncio) |
| ruff | 0.15.12 |
| mypy | 1.20.2 |

- **Model:** `gemini-2.5-flash` via **Vertex AI**, pinned to `temperature=0.0, seed=42`.
- **Data:** BigQuery.
- **Search:** ADK's built-in `google_search` tool (Gemini search grounding) by default; Selenium + Chrome only when the user names a specific site.

---

## 2. Project structure

**Canonical copy (the one to work in):** `/Users/vineet/Downloads/ADK/brand-search-optimization`

- A git repo on branch `main`, with 6 commits and a clean tree.
- `origin` = `https://github.com/aiagencyindia-lab/brand-search-optimization` (private).
- A second remote, `vineetyad`, points to `https://github.com/vineetyad/brand-search-optimization` (private, the old copy).

```
brand-search-optimization/
├── .gitignore                 # ignores .env, .venv/, __pycache__/, .adk/, caches, screenshot_*.png
├── .env                       # NOT tracked. Local config (see §6)
├── env.example                # template for .env
├── README.md                  # setup, run, eval, deployment incl. IAM prerequisites
├── pyproject.toml             # deps + ruff/mypy/pytest config (ruff config inlined, see §7)
├── uv.lock
├── customization.md           # upstream doc, untouched
├── brand_search_optimization.webp
├── docs/
│   └── APPLICATION_AND_TEST_GUIDE.md  # full app / feature / change / manual-test guide (37 KB)
├── brand_search_optimization/
│   ├── __init__.py            # load_dotenv() FIRST, then env setdefaults, then imports root_agent
│   ├── agent.py               # root_agent: 3 AgentTools + 1 sub_agent (comparison)
│   ├── prompt.py              # ROOT_PROMPT: <Steps>, <Choosing a search tool>, <Key Constraints>
│   ├── shared_libraries/constants.py  # env-derived constants + GENERATE_CONTENT_CONFIG + DISABLE_WEB_DRIVER
│   ├── tools/bq_connector.py  # get_product_details_for_brand(brand: str) -> str  (BigQuery)
│   └── sub_agents/
│       ├── __init__.py
│       ├── keyword_finding/{agent,prompt}.py  # calls the BQ tool, ranks keywords
│       ├── search_results/{agent,prompt}.py   # tools=[google_search] only
│       ├── site_browsing/{agent,prompt}.py    # NEW: Selenium tools for named sites
│       └── comparison/{agent,prompt}.py       # comparison_root_agent → generator + critic
├── deployment/
│   ├── deploy.py              # --create / --delete on Agent Engine
│   ├── test_deployment.py     # BROKEN upstream script (see §8), unused
│   ├── bq_populate_data.py    # DANGEROUS: deletes the dataset first (see §8)
│   ├── bq_data_setup.sql, eval.sh, run.sh, test.sh
├── eval/
│   ├── test_eval.py           # AgentEvaluator on the evalset FILE (not the directory)
│   └── data/
│       ├── eval_data1.evalset.json  # modern EvalSet schema, 2-turn recorded conversation
│       └── test_config.json         # thresholds: trajectory 1.0, response_match 0.3
└── tests/
    ├── unit/test_tools.py     # 3 tests for bq_connector
    └── example_interaction.md
```

**Other copy (not canonical):** `/Users/vineet/Downloads/ADK/adk-samples/python/agents/brand-search-optimization`, inside the monorepo on branch `on-brand-genmedia-production`.

- It holds the same app changes, **uncommitted**: about 19 modified files plus an untracked `site_browsing/`. Later fixes were mirrored into it.
- Its `pyproject.toml` still does `extend = "../../../pyproject.toml"`, which is correct inside the monorepo.
- It has no `docs/` folder.
- The user was told they can revert it with `git checkout -- python/agents/brand-search-optimization`. They haven't decided.

---

## 3. What's been built (in order)

1. **Made it start.** Removed a stdlib monkeypatch from `__init__.py`:
   ```python
   typing._UnionGenericAlias = builtin_types.UnionType   # REMOVED
   ```
   On Python 3.12.12+/3.13 it broke every `typing.Union[...]`, and `import pydantic_core` crashed with `TypeError: cannot create 'types.UnionType' instances`.
2. **`.env` is respected.** Moved `dotenv.load_dotenv()` above the `os.environ.setdefault(...)` calls in `__init__.py`. Previously `setdefault("GOOGLE_GENAI_USE_VERTEXAI","True")` ran first, and `load_dotenv` won't override existing variables.
3. **BigQuery sample data.** Created dataset `rasayan.products_data_agent` and table `shoe_items` with 3 rows for brand `BSOAgentTestBrand`: `Kids' Joggers`, `Light-Up Sneakers`, `School Shoes`.
4. **Replaced the Selenium scraper with `google_search`** in `search_results_agent`. Google served a CAPTCHA to Selenium, so stage 3 always failed.
5. **Converted data-gathering agents to `AgentTool`** (`keyword_finding_agent`, `search_results_agent`). Reasons:
   - Gemini rejects `google_search` alongside the auto-injected `transfer_to_agent` (`"Multiple tools are supported only when they are all search tools"`).
   - As sub-agents they caused transfer ping-pong.
   - As tools, the root agent keeps control and passes the brand and keyword as real arguments.
6. **`get_product_details_for_brand(brand: str)`.** It was previously `(tool_context: ToolContext)`: it read the brand from `user_content.parts[0].text`, and its docstring was misleading.
7. **Fixed the eval harness.** `eval/test_eval.py` passed a directory, which `AgentEvaluator` silently treats as zero files, so the test passed in 0.0s without running anything. It now passes the file path. The evalset was migrated to the `EvalSet` schema and re-recorded.
8. **Determinism.** Added `GENERATE_CONTENT_CONFIG = types.GenerateContentConfig(temperature=0.0, seed=42)` on all 6 agents, plus a mechanical rank-1 keyword rule. The trajectory threshold was raised to 1.0 and verified 4/4 runs.
9. **Restored browser search as opt-in** (`site_browsing_agent`, used only when the user names a site). Three bugs fixed while restoring it:
   - The PNG artifact was built from `Image.tobytes()` (raw pixels); it now reads the file bytes.
   - The fixed `user-data-dir=/tmp/selenium` caused `SessionNotCreatedException` on the second run; removed.
   - Deleted the dead tools `click_at_coordinates` and `analyze_webpage_and_determine_action`.
10. **Routing rule** moved into a conversation-wide `<Choosing a search tool>` block. A follow-up like "now check amazon.in" had been going to `search_results_agent` with an invented `domain` argument.
11. **Documentation.** A Claude Doc at `https://claude.ai/code/artifact/c1c5fa6a-bb96-4fda-8143-c599911a924f`, mirrored to `docs/APPLICATION_AND_TEST_GUIDE.md`, covering:
    - overview,
    - features F1–F10,
    - changes N1–N10,
    - a file-change map,
    - improvements and trade-offs,
    - manual tests TC-01 to TC-15,
    - a checklist.
12. **Extracted a standalone repo:** inlined the ruff config, added `.gitignore`, fixed the README clone instructions.
13. **Driver-failure crash fix.** With `DISABLE_WEB_DRIVER=1`, the browser tools used to *raise*, which killed the request. `_get_driver()` now returns `(driver, problem)` and never raises.
14. **BigQuery-failure crash fix.** A `GoogleAPICallError` (e.g. 403) escaped the tool and killed the request with no answer. The tool now returns `"Could not read the product catalog: ..."`, and a unit test covers it.
15. **Deploy script corrections.** Remote requirement pinned to `google-adk>=1.32.0,<2.0.0` (was `>=1.0.0`). `DATASET_ID`, `TABLE_ID` and `MODEL` are now forwarded to the deployed agent.
16. **Deployed to Agent Engine and verified.**
    - Created the staging bucket.
    - Granted the IAM roles listed in §6.
    - Verified the full remote pipeline and the named-site → fallback path.
    - Deleted both engines afterwards (the user deleted the working one). **No engine is currently deployed.**
17. **Pushed to GitHub.** Created under `vineetyad` first, then again under **`aiagencyindia-lab`** (now `origin`). Added a repo-local credential helper so a plain `git push` from this folder signs in as `aiagencyindia-lab`.

---

## 4. Key decisions & conventions

**Architecture** (`brand_search_optimization/agent.py`):

```python
root_agent = Agent(
    model=constants.MODEL,
    name=constants.AGENT_NAME,            # "brand_search_optimization"
    description=constants.DESCRIPTION,
    generate_content_config=constants.GENERATE_CONTENT_CONFIG,
    instruction=prompt.ROOT_PROMPT,
    sub_agents=[comparison_root_agent],
    tools=[
        AgentTool(agent=keyword_finding_agent),
        AgentTool(agent=search_results_agent),
        AgentTool(agent=site_browsing_agent),
    ],
)
```

- **Tools vs. sub-agent:** data-gathering agents are `AgentTool`s, so the root keeps control and passes explicit arguments. Only `comparison_root_agent` is a sub-agent; it runs a generator/critic loop (`comparison_generator_agent`, `comparison_critic_agent`).
- **Expected trajectory for `BSOAgentTestBrand`** (deterministic):
  ```
  keyword_finding_agent({'request': 'BSOAgentTestBrand'})
  search_results_agent({'request': 'kids shoes'})
  transfer_to_agent({'agent_name': 'comparison_root_agent'})
  transfer_to_agent({'agent_name': 'comparison_generator_agent'})
  ```
  Inside `keyword_finding_agent`, the BigQuery tool is called as `get_product_details_for_brand({'brand': 'BSOAgentTestBrand'})`.
- **Named site:** a message like `"BSOAgentTestBrand, and search amazon.in for the keyword"` → `site_browsing_agent({'request': 'amazon.in | kids shoes'})`. The request format is `"<site> | <keyword>"`.
- **Tools never raise.** They return error strings so the agent can explain and fall back. This convention exists because a raising tool terminates the whole request, with no answer and nothing in the stream. Both instances:
  ```python
  # site_browsing/agent.py
  def _get_driver():   # returns (driver, None) or (None, "reason...")
      if constants.DISABLE_WEB_DRIVER:
          return None, _DISABLED
      ...
      try: _driver_state["driver"] = selenium.webdriver.Chrome(options=options)
      except WebDriverException as e: return None, ("Could not start Chrome ... Use search_results_agent instead.")
      return _driver_state["driver"], None
  # each tool:
      driver, problem = _get_driver()
      if problem: return problem
  ```
  ```python
  # tools/bq_connector.py
  try:
      results = bq_client.query(query, job_config=query_job_config).result()
  except GoogleAPICallError as e:
      return f"Could not read the product catalog: {e.code} {type(e).__name__}: {e.message}"
  ```
- **BigQuery query** uses a bound parameter, so it's injection-safe:
  `WHERE Brand LIKE CONCAT('%', @parameter1, '%') LIMIT 3`, where `parameter1` is the brand.
- **Determinism:** `GENERATE_CONTENT_CONFIG` is applied to every `Agent(...)`. The keyword prompt's `<Keyword Ranking>` says:
  - drop brand-name keywords;
  - rank 1 is the shortest audience + category phrase, lowercase (e.g. `kids shoes`);
  - one keyword per row.
- **Root prompt** (`prompt.py`) has a conversation-wide `<Choosing a search tool>` block:
  - a named site → `site_browsing_agent` with `"<site> | <keyword>"`;
  - otherwise → `search_results_agent` with the keyword only;
  - it explicitly says to never invent extra arguments such as `domain`, and to fall back to `search_results_agent` once if the site is blocked.
- **Style:**
  - Every agent/prompt module keeps the Apache license header.
  - Prompt constants are UPPER_SNAKE (`SEARCH_RESULT_AGENT_PROMPT`, `SITE_BROWSING_AGENT_PROMPT`).
  - Ruff line-length is 80 with double quotes.
  - Comments explain *why*, only where the reason isn't obvious.
- **Commits:** conventional-style subjects (`fix(site_browsing): ...`, `docs: ...`), a body explaining why, ending with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

## 5. Current state

**Working and verified (live BigQuery + live search):**
- Local web UI and CLI; full pipeline in one turn.
- Named-site browser path: Chrome opens amazon.in and returns real listings.
- `DISABLE_WEB_DRIVER=1` falls back gracefully and still produces the report.
- Unknown brand returns 0 rows with nothing fabricated; empty brand returns `No brand provided.`
- `ruff` clean, `mypy` clean (17 files), `pytest tests` 3 passed, `pytest eval` passes at trajectory 1.0 (runs about 60–135s).
- Agent Engine deployment worked end to end, including the fallback path. It's currently deleted by choice.
- The GitHub push through `aiagencyindia-lab` works (`git push` → "Everything up-to-date").

**Not verified:**
- TC-14: a screenshot artifact actually rendering in the ADK web UI. The encoding fix is in place, but nobody has opened one in the UI.

**Known broken (left alone deliberately):**
- `deployment/test_deployment.py` reads `GOOGLE_CLOUD_STORAGE_BUCKET` instead of `STAGING_BUCKET`, overwrites its own flags with env values, and is an interactive loop. The README now documents a working snippet instead.

**Limits by design:**
- `LIMIT 3` products per run.
- Search results change daily, which is why `response_match_score` sits at 0.3.
- Sites can CAPTCHA the browser path.
- Rapid runs can hit Vertex `429 RESOURCE_EXHAUSTED`.

**Nothing is half-finished.** The last task (push via `aiagencyindia-lab`) is complete.

---

## 6. Environment & setup

**`.env`** (not tracked; the current values are below and contain no secrets):
```
GOOGLE_GENAI_USE_VERTEXAI=1
GOOGLE_API_KEY=                      # empty; only needed for the AI Studio backend (=0)
GOOGLE_CLOUD_PROJECT=rasayan
GOOGLE_CLOUD_LOCATION=us-central1
MODEL="gemini-2.5-flash"
DISABLE_WEB_DRIVER=0
DATASET_ID="products_data_agent"
TABLE_ID="shoe_items"
STAGING_BUCKET=rasayan-bso-agent-staging
```

**Google Cloud:**
- **Project `rasayan`:**
  - number `210024532027`, billing enabled, owner `aiagencyindia@gmail.com`;
  - BigQuery `rasayan.products_data_agent.shoe_items` (schema `Title, Description, Attributes, Brand`, all STRING, 3 rows).
- **ADC (used by the app and SDKs):** `aiagencyindia@gmail.com`, quota project `rasayan`.
- **gcloud CLI active account:** `aixaitools@gmail.com`. This account has **no access to `rasayan`**, so do rasayan operations through the Python SDKs (ADC), not `gcloud`/`bq`.
- **Staging bucket:** `gs://rasayan-bso-agent-staging` (us-central1). It still exists.
- **IAM still in place:** service account `service-210024532027@gcp-sa-aiplatform-re.iam.gserviceaccount.com` has:
  - `roles/bigquery.jobUser` on project `rasayan`;
  - `READER` on dataset `products_data_agent` only.
- **Leftover:** dataset `products_data_agent.shoe_items` (3 rows) also exists in `project-cb9934aa-2b3a-4bd4-9ac` (the `aixaitools` project, no billing), from the first attempt. Unused.

**Run locally:**
```bash
cd /Users/vineet/Downloads/ADK/brand-search-optimization
uv sync --dev
uv run adk web --port 8765      # UI at http://127.0.0.1:8765 → pick brand_search_optimization → type BSOAgentTestBrand
uv run adk run brand_search_optimization
uv run pytest tests -q          # unit tests
uv run pytest eval -q           # real eval, ~1–2 min
uv run ruff check . && uv run mypy .
```

**Deploy / delete:**
```bash
uv sync --group deployment
uv run python deployment/deploy.py --create          # ~6 min, prints the resource name
uv run python deployment/deploy.py --delete --resource_id=<resource-name>
```
`--create` always makes a new engine; there's no update mode.

**Scratch scripts** (they lived in a temp scratchpad and may be gone; recreate if needed).

Local driver (`drive.py`), run with `uv run python drive.py "hello" "BSOAgentTestBrand"`:
```python
import asyncio, sys
from google.adk.runners import InMemoryRunner
from google.genai import types
from brand_search_optimization.agent import root_agent
async def main():
    runner = InMemoryRunner(agent=root_agent, app_name="bso")
    s = await runner.session_service.create_session(app_name="bso", user_id="u")
    for turn in sys.argv[1:]:
        print(f"\n=== USER: {turn}")
        async for ev in runner.run_async(user_id="u", session_id=s.id,
                new_message=types.Content(role="user", parts=[types.Part(text=turn)])):
            for p in (ev.content.parts if ev.content and ev.content.parts else []):
                if p.function_call: print(f"  [tool call] {p.function_call.name}({dict(p.function_call.args or {})})")
                elif p.function_response: print(f"  [tool resp] {p.function_response.name} -> {str(p.function_response.response)[:400]}")
                elif p.text: print(f"  [{ev.author}] {p.text.strip()[:900]}")
asyncio.run(main())
```

Remote query (`remote.py`); set `RES` to the resource name printed by `deploy.py`:
```python
import sys, vertexai
from vertexai import agent_engines
RES = "projects/210024532027/locations/us-central1/reasoningEngines/<id>"
vertexai.init(project="rasayan", location="us-central1")
agent = agent_engines.get(RES)
sid = agent.create_session(user_id="tester")["id"]
for msg in sys.argv[1:]:
    for ev in agent.stream_query(user_id="tester", session_id=sid, message=msg):
        for p in (ev.get("content") or {}).get("parts") or []:
            if p.get("function_call"): print("[tool call]", p["function_call"]["name"], p["function_call"].get("args"))
            elif p.get("text"): print(f"[{ev.get('author')}]", p["text"][:600])
```

**GitHub:**
- `origin` = `aiagencyindia-lab/brand-search-optimization` (private).
- A repo-local credential helper, scoped to `https://github.com/aiagencyindia-lab`, gets the token from `gh auth token -u aiagencyindia-lab` at push time. No token is stored.
- The `gh` CLI has two logins: `vineetyad` (active) and `aiagencyindia-lab`.
- Commits are *authored* as `vineetyad` (from the git config).

---

## 7. Next steps

**No task is in progress.** Open offers the user hasn't accepted yet:

1. **Batch mode:** loop over the whole catalog instead of `LIMIT 3`, and write `current_title`, `suggested_title`, `missing_keywords` to a BigQuery table or CSV. The user hasn't said which. It will need rate-limit handling (429s were seen).
2. **Fill the empty `Source` column** in `search_results_agent` output using the grounding metadata URLs.
3. **Fix `deployment/test_deployment.py`**, or add an `--update` mode to `deploy.py`.
4. **Rewrite commit authorship** to `aiagencyindia-lab` and force-push. Safe right now because nobody else has cloned the repo.
5. **Delete the old `vineetyad/brand-search-optimization` repo.** It must be done via GitHub Settings, because the `vineetyad` token lacks the `delete_repo` scope. Then remove the `vineetyad` remote.
6. **If Agent Engine is abandoned:** delete `gs://rasayan-bso-agent-staging` and remove the two IAM grants.
7. **Decide on the `adk-samples` copy:** revert its uncommitted changes, or keep them.
8. **Test TC-14** (screenshot artifact in the UI).
9. **Optional:** remove the leftover dataset in `project-cb9934aa-2b3a-4bd4-9ac`, and remove the `rasayan` project ID mentions from the test guide (lines ~287–288) before making the repo public.

---

## 8. Gotchas

- **Tool exceptions kill the whole request.** In ADK, an exception raised inside a tool (including one inside an `AgentTool`) ends the request with no answer, and the stream just stops. Always return error strings. This bit us twice (driver disabled, BigQuery 403).
- **`AgentEvaluator.evaluate(dir)` silently passes.** Pass the `.evalset.json` file path. The legacy `[{name, data}]` evalset format throws `ValueError` when loaded by file path; use the `EvalSet` schema. To migrate, use `convert_eval_set_to_pydantic_schema` from `google.adk.evaluation.local_eval_sets_manager`, then dump **without** `by_alias` (camelCase keys won't load).
- **The trajectory metric matches arguments exactly.** Any change to prompts, temperature or ranking can change the keyword (`kids shoes` vs `kids sneakers`) and fail the eval at 1.0. Re-verify with several eval runs after prompt edits.
- **`google_search` can't share an agent with `transfer_to_agent`.** Keep `search_results_agent` as an `AgentTool` with `tools=[google_search]` only.
- **Routing rules belong in the conversation-wide `<Choosing a search tool>` block**, not inside `<Steps>`, or follow-up requests get mis-routed.
- **Two Google identities:** ADC is `aiagencyindia@gmail.com` (owns `rasayan`); the gcloud CLI is `aixaitools@gmail.com` (no access). A mismatch shows up as `403 bigquery.jobs.create`.
- **The Cloud Resource Manager API is disabled in `rasayan`.** For IAM policy calls, use `creds.with_quota_project(None)` with `AuthorizedSession` rather than enabling the API.
- **Agent Engine runs as `service-<num>@gcp-sa-aiplatform-re.iam.gserviceaccount.com`**, which needs its own BigQuery grants. Without them, every remote request gets a 403.
- **Remote log tracebacks are split across log entries.** To find the real exception, scan all entries in the time window for lines matching `google.api_core.exceptions...`.
- **`deployment/bq_populate_data.py` calls `delete_dataset(delete_contents=True)` before recreating.** Don't run it against real data. Load data with `bq load` or `load_table_from_json` instead; that also works on free-tier projects, where DML is blocked.
- **The browser path opens a visible Chrome window.** Kill stale drivers between runs (`pkill -f chromedriver`). Never reintroduce a fixed `user-data-dir`.
- **Agent Engine has no Chrome.** `deploy.py` sets `DISABLE_WEB_DRIVER=1` remotely.
- **Vertex `429 RESOURCE_EXHAUSTED`** appears after many rapid runs. It's quota, not a bug; wait and retry.
- **Wrong folder:** the user's terminal pane and the assistant's shell both default to the **`adk-samples/...` path**, not the standalone repo. Always `cd /Users/vineet/Downloads/ADK/brand-search-optimization` (or use `git -C`) first. The user once ran a credential command in the wrong repo, and it was undone.
- **Exporting the Claude Doc:** the full markdown export is too large to return inline; it gets saved to a tool-results file as base64. Decode `data.bytes_b64` from that JSON into `docs/APPLICATION_AND_TEST_GUIDE.md`.
- **The Python 3.12.12+ `typing` monkeypatch** must never come back into `__init__.py`.
