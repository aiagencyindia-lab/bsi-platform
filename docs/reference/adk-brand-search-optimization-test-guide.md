# Brand Search Optimization — Application, Features & Test Guide

2026-09-18 · @Someone

ADK multi-agent sample that audits e-commerce product titles against what actually ranks in search. This document covers the application, its features, the code changes behind them, and how to verify each one by hand.

## 1. Application Overview

### What it does

Brand Search Optimization is an **Agent Development Kit (ADK) multi-agent application that audits e-commerce product titles**. You give it a brand name; it tells you which words your titles are missing and hands back rewritten titles.

The problem it solves: catalog titles are usually written in internal or brand vocabulary ("Kids' Joggers", "Air Flow Tech") while customers search in generic vocabulary ("kids shoes", "breathable running shoes"). When those two vocabularies don't overlap the product is effectively invisible — it never appears for the most obvious search a customer can make. The application finds that gap per product, grounds it in what is actually ranking today, and proposes concrete title fixes.

### Overall workflow

One brand name in, a full report out. All four stages run in a **single conversational turn** with no further input.

| Stage | Agent | Data source | Output |
| --- | --- | --- | --- |
| 1. Read the catalog | `keyword_finding_agent` → `get_product_details_for_brand` | **BigQuery** product table | Up to 3 products (Title, Description, Attributes, Brand) |
| 2. Infer shopper vocabulary | `keyword_finding_agent` | The LLM, reading stage 1 | Ranked keyword table, generic terms first |
| 3. Find who ranks | `search_results_agent` (default) or `site_browsing_agent` | **Google search grounding**, or a **real Chrome browser** | Top 3 competing product titles |
| 4. Compare and rewrite | `comparison_root_agent` → generator + critic | Stages 1 and 3 | Side-by-side report with missing keywords and suggested titles |

The keyword ranking in stage 2 deliberately pushes **brand-name keywords to the bottom**. Someone searching `kids shoes` does not yet know your brand, so branded keywords cannot win new traffic — only generic ones can.

Stage 4 is a **generator/critic loop**: one agent writes the comparison, a second critiques it, and they iterate until the critic is satisfied.

### Architecture

The root agent (`brand_search_optimization`) orchestrates. Two design shapes are in play, and the difference matters:

- **Tools** (`AgentTool`) — `keyword_finding_agent`, `search_results_agent`, `site_browsing_agent`. The root agent calls these like functions and **keeps control**, passing arguments explicitly (the brand, the keyword).
- **Sub-agent** (`transfer_to_agent`) — `comparison_root_agent`. Control transfers to it, and it runs its own generator and critic sub-agents.

### Stack

- **Python 3.13**, dependencies managed by `uv`
- **google-adk 1.32** for agent orchestration, tools and evaluation
- **Gemini 2.5 Flash** via **Vertex AI**, pinned to `temperature=0.0, seed=42`
- **BigQuery** for the product catalog
- **Selenium + Chrome** for the optional named-site browsing path

### Interfaces

```bash
uv run adk web    # browser UI at http://127.0.0.1:8765
uv run adk run brand_search_optimization    # terminal
```

Configuration lives entirely in `.env`: `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GOOGLE_GENAI_USE_VERTEXAI`, `MODEL`, `DATASET_ID`, `TABLE_ID`, `DISABLE_WEB_DRIVER`.

## 2. Application Features

### F1 — Brand catalog lookup (BigQuery)

**Purpose.** Pull the brand's own product titles out of the catalog. This is your side of the comparison.

**How it works.** `get_product_details_for_brand(brand: str)` in `tools/bq_connector.py` runs a parameterised query against `{PROJECT}.{DATASET_ID}.{TABLE_ID}`:

```sql
SELECT Title, Description, Attributes, Brand
FROM `project.dataset.table`
WHERE Brand LIKE CONCAT('%', @parameter1, '%')
LIMIT 3
```

The brand arrives as a **bound query parameter**, not string interpolation, so a brand name cannot inject SQL. The BigQuery client is created lazily on first call, and a failure to initialise is cached so the app does not retry on every invocation. Results come back as a markdown table.

**How to use it.** Type a brand name at the agent. To point it at your own catalog, create a table with columns `Title`, `Description`, `Attributes`, `Brand` and set `DATASET_ID` / `TABLE_ID` in `.env`.

### F2 — Keyword discovery and ranking

**Purpose.** Work out what a shopper would actually type to find these products, and rank those phrases by commercial value.

**How it works.** `keyword_finding_agent` calls F1, then reads each product's title, description and attributes to generate candidate search phrases. It then de-duplicates, groups synonyms, and ranks by an explicit rule set: brand-name keywords are dropped, and rank 1 is the shortest phrase naming audience plus product category (e.g. `kids shoes`). One keyword per row.

**How to use it.** Runs automatically as step 1. The ranked table is shown to you, and rank 1 feeds the next stage.

### F3 — Competitive search via Google grounding (default path)

**Purpose.** Find out which products already rank for your top keyword, so the comparison is against reality rather than guesswork.

**How it works.** `search_results_agent` holds a single tool, ADK's built-in `google_search` (Gemini search grounding). It searches the keyword biased toward shopping intent and extracts the top 3 distinct product titles. Its prompt forbids inventing titles and requires it to state which keyword it searched.

**How to use it.** Automatic. No API key or browser needed — grounding ships with `google-adk`.

### F4 — Competitive search via real browser, per named site

**Purpose.** Answer site-specific questions: *what am I competing against on amazon.in?* Google's view is not the same as a marketplace's internal ranking.

**How it works.** `site_browsing_agent` drives a real Chrome window through Selenium with seven tools — `go_to_url`, `take_screenshot`, `find_element_with_text`, `click_element_with_text`, `enter_text_into_element`, `scroll_down_screen`, `get_page_source` — plus `load_artifacts` so screenshots return as viewable artifacts. The driver initialises lazily, so importing the package never launches Chrome.

**How to use it.** Name a site in your request:

```text
BSOAgentTestBrand, and search amazon.in for the keyword
```

The root agent passes `"amazon.in | kids shoes"`. Set `DISABLE_WEB_DRIVER=1` to disable it entirely (deployment does this automatically).

### F5 — Comparison report with generator/critic review

**Purpose.** Turn the two title sets into an actionable diff, reviewed rather than first-draft.

**How it works.** `comparison_root_agent` routes to `comparison_generator_agent`, which writes a side-by-side table of your title vs. the ranking title, the missing keywords, and a suggested rewrite. `comparison_critic_agent` then critiques it, and the loop continues until the critic declares itself satisfied.

**How to use it.** Automatic, and it produces the final answer you read.

### F6 — Two front ends

`uv run adk web` serves a browser UI (app dropdown, session history, artifact viewer for screenshots). `uv run adk run brand_search_optimization` is the terminal equivalent. Both load the same `root_agent`.

### F7 — Evaluation suite

**Purpose.** Catch regressions in tool trajectory and answer quality.

**How it works.** `eval/data/eval_data1.evalset.json` holds a recorded two-turn conversation in ADK's `EvalSet` schema. Two metrics are scored against `eval/data/test_config.json`: `tool_trajectory_avg_score` (exact match on tool names *and* arguments, threshold **1.0**) and `response_match_score` (ROUGE against the recorded answer, threshold **0.3**).

**How to use it.**

```bash
uv run pytest eval -q
uv run adk eval brand_search_optimization eval/data/eval_data1.evalset.json \
  --config_file_path eval/data/test_config.json
```

### F8 — Unit tests, linting, type checking

`tests/unit/test_tools.py` covers the BigQuery tool with a mocked client, including the brand-filtering behaviour and the empty-brand guard. Ruff and mypy are configured in `pyproject.toml`.

### F9 — Deployment to Vertex AI Agent Engine

`deployment/deploy.py --create` packages the agent for Agent Engine, and sets `DISABLE_WEB_DRIVER=1` in the remote environment because Agent Engine has no Chrome. F3 keeps working there; F4 does not.

### F10 — Reproducible output

All six LLM agents share `GENERATE_CONTENT_CONFIG` (`temperature=0.0, seed=42`) from `shared_libraries/constants.py`, so the same brand and catalog produce the same keywords and the same tool trajectory run after run.

## 3. Recently Added Features

Ten changes, grouped by kind. **N1–N3 are blocking-bug fixes** — without them the application does not start, ignores its config, or reports test results that mean nothing.

### N1 — Removed a stdlib monkeypatch that prevented startup

**What it does.** Deletes two lines from `brand_search_optimization/__init__.py`:

```python
typing._UnionGenericAlias = builtin_types.UnionType    # removed
```

**Why.** On current CPython (3.12.12+/3.13.x) this breaks *every* `typing.Union[...]` evaluated afterwards in the process. `import pydantic_core` then died with `TypeError: cannot create 'types.UnionType' instances`, so the agent could not be imported at all.

**Improvement.** The application starts. This is not a preference — the previous version was unrunnable on a modern interpreter.

### N2 — `.env` is now actually read

**What it does.** Moves `dotenv.load_dotenv()` to the top of `__init__.py`, before the `os.environ.setdefault(...)` calls.

**Why.** `setdefault` ran first and pinned `GOOGLE_GENAI_USE_VERTEXAI`; `load_dotenv()` does not override variables that already exist. Every backend setting in `.env` was silently discarded.

**Improvement.** Configuration behaves as documented. You can switch between Vertex and AI Studio by editing one line.

### N3 — Evaluation harness now executes

**What it does.** `eval/test_eval.py` passes the evalset **file** instead of its parent directory.

**Why.** `AgentEvaluator.evaluate()` silently matches nothing when handed a directory and returns successfully. Proof: with a deliberately bogus expectation (`definitely_not_a_tool`) the old call still reported `PASSED in 0.0s`. The test had never run the agent.

**Improvement.** The eval now runs for real (\~60–135 s) and **fails** when the trajectory is wrong. A green test means something.

### N4 — Google search grounding replaces the Selenium scraper on the default path

**What it does.** `search_results_agent` now uses ADK's built-in `google_search` tool instead of \~198 lines of Selenium page-driving.

**Why.** Google served a **CAPTCHA** to the scraper, so stage 3 of 4 failed and no comparison report was ever produced. The agent correctly reported being blocked — and stopped.

**Improvement.** The pipeline completes unattended. No Chrome, no new dependency, no new API key.

### N5 — Browser search restored as an opt-in, per-site agent

**What it does.** New `sub_agents/site_browsing/` package (F4) with the Selenium toolset, invoked only when the user names a site.

**Why.** N4 alone removed a real capability: reading a *specific* retailer's search page. Grounding cannot tell you what ranks inside amazon.in's own search.

**Improvement.** Both paths available — reliable by default, browser on request — rather than one or the other. Three bugs were fixed during the restore rather than reinstated:

| Bug in original | Consequence | Fix |
| --- | --- | --- |
| `take_screenshot` saved `Image.tobytes()` as `image/png` | Raw pixel data mislabelled as PNG — artifacts were unopenable | Reads the encoded PNG back off disk |
| `user-data-dir=/tmp/selenium` hardcoded | Second run died with `SessionNotCreatedException: Chrome instance exited` (profile locked) | Removed; Selenium uses a throwaway profile |
| `click_at_coordinates`, `analyze_webpage_and_determine_action` | One scrolled then clicked `<body>` instead of the target; the other returned a prompt string as its result | Both deleted |

### N6 — `get_product_details_for_brand` takes a real `brand` argument

**What it does.** Signature changes from `(tool_context: ToolContext)` to `(brand: str)`.

**Why.** The old docstring described the parameter as *"tool\_context (str): The tool\_context to search for"* while the code read the brand from `tool_context.user_content.parts[0].text`. Two consequences: the model emitted inconsistent arguments (`{'tool_context': '...'}` on some runs, `{}` on others), and the tool only worked when your message *was* exactly the brand name — it broke on "look up BSOAgentTestBrand for me".

**Improvement.** Correct on any phrasing, deterministic in the trajectory, and honest about its own interface.

### N7 — Data-gathering agents converted from sub-agents to `AgentTool`

**What it does.** `keyword_finding_agent` and `search_results_agent` moved from `sub_agents=[...]` to `tools=[AgentTool(agent=...)]`.

**Why.** Two independent reasons. First, as sub-agents they kept control after their turn and **ping-ponged transfers** — one observed run wasted five round trips bouncing between `keyword_finding_agent` and `comparison_root_agent`. Second, Vertex rejects a built-in search tool alongside the auto-injected `transfer_to_agent`: `Multiple tools are supported only when they are all search tools`. `AgentTool` removes that tool, which is what made N4 possible.

**Improvement.** The root agent keeps control, arguments pass explicitly, the whole pipeline runs in **one turn**, and the wasted transfers are gone.

### N8 — Deterministic decoding

**What it does.** `GENERATE_CONTENT_CONFIG = types.GenerateContentConfig(temperature=0.0, seed=42)` applied to all six agents, plus a mechanical rank-1 rule in the keyword prompt (shortest audience + category phrase; one keyword per row).

**Why.** The old rule, *"Rank generic keywords higher"*, leaves the winner genuinely ambiguous between `kids shoes`, `running shoes` and `sneakers`. The keyword varied run to run, which changed the tool trajectory and made the eval flaky — it failed 1 run in 3 at threshold 1.0. Runs were also comma-jamming several keywords into one table cell, so "the top keyword" was ill-defined even when the table looked right.

**Improvement.** Five consecutive runs produced byte-identical trajectories; four consecutive evals scored `tool_trajectory_avg_score = 1.000`. The trade-off is less variety in keyword brainstorming.

### N9 — Evalset migrated, re-recorded, and thresholds raised

**What it does.** `eval_data1.evalset.json` converted from the legacy `[{name, data}]` format to ADK's `EvalSet` schema and re-recorded from live runs. Thresholds moved from `0.2 / 0.2` to `1.0 / 0.3`.

**Why.** The legacy format raises `ValueError` when loaded by file path (needed for N3). The old expectations referenced deleted tools (`go_to_url`, `click_element_with_text`). And `0.2` is close to meaningless — a bogus tool name still passed.

**Improvement.** Exact-match trajectory checking. A wrong tool or a wrong argument now fails the suite.

### N10 — Dependency and routing cleanup

Routing rules moved into a conversation-wide `<Choosing a search tool>` block in the root prompt, after a mid-conversation *"now check amazon.in"* was mis-routed to `search_results_agent` with an invented `domain` argument. `pillow` dropped as a direct dependency. README documents both search paths and explains why each eval threshold sits where it does.

**Net change: 19 files, +260 / −502 lines**, plus one new package.

## 4. Code / File Changes

### Added

| File | Lines | What it contains | Feature |
| --- | --- | --- | --- |
| `brand_search_optimization/sub_agents/site_browsing/agent.py` | \~150 new | `site_browsing_agent` plus 7 Selenium tools and the lazy `_get_driver()` | N5 / F4 |
| `brand_search_optimization/sub_agents/site_browsing/prompt.py` | \~50 new | `SITE_BROWSING_AGENT_PROMPT` — site+keyword parsing, CAPTCHA refusal rule | N5 / F4 |

No files were deleted. `sub_agents/search_results/agent.py` was rewritten in place (−198 lines), not removed.

### Modified

| File | Diff | What changed | Feature |
| --- | --- | --- | --- |
| `brand_search_optimization/__init__.py` | +4 −4 | Removed the `typing._UnionGenericAlias` monkeypatch and `import types`; moved `dotenv.load_dotenv()` above the `setdefault` block | N1, N2 |
| `brand_search_optimization/agent.py` | +12 −4 | `sub_agents` reduced to `[comparison_root_agent]`; `tools=[AgentTool(keyword_finding_agent), AgentTool(search_results_agent), AgentTool(site_browsing_agent)]`; added `generate_content_config` | N5, N7, N8 |
| `brand_search_optimization/prompt.py` | +26 −5 | `<Steps>` rewritten for tool calls with explicit arguments; new conversation-wide `<Choosing a search tool>` block routing named sites to the browser agent | N7, N10 |
| `brand_search_optimization/shared_libraries/constants.py` | +10 −1 | Added `GENERATE_CONTENT_CONFIG` (temperature 0, seed 42) and re-added `DISABLE_WEB_DRIVER` | N5, N8 |
| `brand_search_optimization/tools/bq_connector.py` | +9 −12 | Signature `(tool_context: ToolContext)` → `(brand: str)`; docstring corrected; empty-brand guard; dropped the `ToolContext` import | N6 |
| `brand_search_optimization/sub_agents/search_results/agent.py` | +9 −198 | Entire Selenium toolset removed; now a single-tool agent using `google_search` | N4 |
| `brand_search_optimization/sub_agents/search_results/prompt.py` | +12 −22 | Removed "which website?" opener; the request *is* the keyword; requires stating the keyword searched | N4, N7 |
| `brand_search_optimization/sub_agents/keyword_finding/agent.py` | +1 | Added `generate_content_config` | N8 |
| `brand_search_optimization/sub_agents/keyword_finding/prompt.py` | +10 −5 | Brand arrives as the request; mechanical rank-1 rule; one keyword per row; removed the "transfer to root\_agent" step | N6, N7, N8 |
| `brand_search_optimization/sub_agents/comparison/agent.py` | +3 | Added `generate_content_config` to generator, critic and root | N8 |
| `eval/test_eval.py` | +3 −1 | Points at the evalset **file**, with a comment explaining the silent-pass trap | N3 |
| `eval/data/eval_data1.evalset.json` | +82 −114 | Migrated to `EvalSet` schema; re-recorded two-turn conversation; expectations updated to the new tool names and arguments | N9 |
| `eval/data/test_config.json` | +3 −3 | Thresholds `0.2 / 0.2` → `1.0 / 0.3` | N8, N9 |
| `tests/unit/test_tools.py` | +7 −7 | Calls the tool with `"cymbal"` instead of a mocked `ToolContext`; removed the `ToolContext` import; added an empty-brand test | N6 |
| `pyproject.toml` | −1 | Dropped `pillow`; `selenium` and `webdriver-manager` retained for F4 | N4, N5, N10 |
| `env.example` | +3 −3 | `DISABLE_WEB_DRIVER` re-documented against the browser agent | N5 |
| `deployment/deploy.py` | +4 −5 | Sets `env_vars = {"DISABLE_WEB_DRIVER": "1"}`; requirements list reconciled with the new dependencies | N5, F9 |
| `README.md` | +19 −3 | Documents both search paths, `DISABLE_WEB_DRIVER`, and the reasoning behind each eval threshold | N5, N9, N10 |
| `uv.lock` | regenerated | Dependency changes | N4, N5 |

### Feature → code map

| Feature | Primary files |
| --- | --- |
| N1 startup fix | `__init__.py` |
| N2 `.env` honoured | `__init__.py` |
| N3 eval harness runs | `eval/test_eval.py` |
| N4 grounded search | `sub_agents/search_results/{agent,prompt}.py`, `pyproject.toml` |
| N5 browser agent | `sub_agents/site_browsing/*` (new), `agent.py`, `prompt.py`, `constants.py`, `env.example`, `deployment/deploy.py`, `README.md` |
| N6 real `brand` arg | `tools/bq_connector.py`, `tests/unit/test_tools.py`, `keyword_finding/prompt.py` |
| N7 `AgentTool` conversion | `agent.py`, `prompt.py`, `search_results/prompt.py`, `keyword_finding/prompt.py` |
| N8 determinism | `constants.py`, all 4 agent modules, `keyword_finding/prompt.py`, `test_config.json` |
| N9 evalset | `eval/data/eval_data1.evalset.json`, `eval/data/test_config.json` |
| N10 routing + docs | `prompt.py`, `README.md`, `pyproject.toml` |

### Environment setup performed outside the repo

Not code, but required to run:

- BigQuery dataset `products_data_agent` and table `shoe_items` created in project `rasayan`, loaded with 3 `BSOAgentTestBrand` rows via `bq load` (a load job, not DML — DML is blocked without billing).
- ADC authenticated and quota project set to `rasayan`.
- `.env` created from `env.example` with `GOOGLE_GENAI_USE_VERTEXAI=1`.

## 5. Improvements Over the Previous Version

### Functionality

|  | Before | After |
| --- | --- | --- |
| Startup | `TypeError: cannot create 'types.UnionType' instances` on import | Imports and runs |
| Config | `.env` backend settings silently ignored | `.env` authoritative |
| Stage 3 (search) | CAPTCHA — pipeline stopped 2 of 4 stages in | Completes unattended |
| Turns to a full report | 3 user turns, with mid-flow questions | **1 turn** |
| Catalog lookup | Only worked if your message *was* the brand name | Works on any phrasing |
| Site-specific search | Selenium only, CAPTCHA-prone, the default path | Opt-in second path, with grounding as the reliable default |

### Reliability

- **Wasted transfers eliminated.** An observed run burned five round trips ping-ponging between `keyword_finding_agent` and `comparison_root_agent` before recovering. The root agent now retains control throughout.
- **Trajectory is reproducible.** Five consecutive runs produced byte-identical tool trajectories; four consecutive eval runs scored 1.000.
- **Chrome no longer self-collides.** The hardcoded shared profile made every second browser run fail with `SessionNotCreatedException`.
- **Screenshots actually open.** Artifacts were previously raw pixel bytes labelled `image/png`.
- **Bot-detection handling is explicit.** The browser agent reports a CAPTCHA and falls back to grounding rather than looping or fabricating titles.

### Test integrity

This is the largest single improvement and the least visible. The previous eval suite **passed without running the agent** — verified by feeding it a nonexistent tool name and watching it report `PASSED in 0.0s`. Combined with `0.2` thresholds, a green build carried close to zero information. Now the suite executes the agent (\~60–135 s), matches tool names and arguments exactly, and fails on a mismatch. Demonstrated failure mode:

```text
AssertionError: tool_trajectory_avg_score for None Failed.
  Expected 1.0, but got 0.6666666666666666.
```

### Maintainability

- **−502 / +260 lines.** Around 198 lines of browser-driving code on the critical path replaced by one built-in tool; the same capability now lives in an isolated, optional package.
- **Two dead tools removed** — `click_at_coordinates` (clicked `<body>`, never the target) and `analyze_webpage_and_determine_action` (returned a prompt string as a tool result).
- **Honest interfaces.** `get_product_details_for_brand(brand: str)` matches its docstring; the previous signature actively misled both the model and any reader.
- **Comments explain the non-obvious.** Each counter-intuitive decision carries its reason inline — why the search agent is a tool rather than a sub-agent, why there is no fixed Chrome profile, why decoding is pinned.

### Usability

- One word in, full report out — no "which website?" / "which keyword?" interrogation.
- Naming a site is plain language: *"and search amazon.in for the keyword"*.
- `DISABLE_WEB_DRIVER=1` runs the whole app without Chrome, and deployment sets it automatically.
- README documents both search paths and justifies each eval threshold.

### Performance and cost

Fewer LLM round trips per report, since eliminated transfers were each a model call. No Chrome process on the default path, so lower memory and no driver startup. Three fewer packages resolved at install time.

### What was given up — honestly

1. **Arbitrary-site browsing is no longer the default.** You must name the site. If you want every run to go through a real browser against a fixed retailer, that is now an extra instruction.
2. **Less of a pure sub-agent-transfer showcase.** Two of three agents are `AgentTool`s. If you read this repo to learn ADK's agent-to-agent transfer patterns, there is less of it on display — that was traded for reliability and for making the built-in search tool usable at all.
3. **`temperature=0` reduces variety.** Keyword brainstorming may surface fewer novel ideas than sampling would. This was chosen to make the eval trustworthy; raise it if you value diversity over reproducibility, and expect the strict trajectory threshold to start flaking.
4. **No cookie persistence in the browser agent.** A throwaway Chrome profile means cookie banners and logins are not remembered between runs.
5. **Still 3 products per run.** `LIMIT 3` is unchanged — this remains a diagnostic tool, not a bulk catalog processor.

## 6. Manual Testing

### Prerequisites

```bash
cd python/agents/brand-search-optimization
cp env.example .env          # then fill in project + location
uv sync --dev
gcloud auth application-default login
gcloud auth application-default set-quota-project <your-project>
```

Confirm the ADC account is the one that owns the project. A mismatch produces `403 User does not have bigquery.jobs.create permission` even though the `bq` CLI works — the CLI and ADC can be different identities.

Seed the catalog (load job, works without billing):

```bash
bq --project_id=<project> mk --location=US --dataset products_data_agent
bq --project_id=<project> query --nouse_legacy_sql \
  "CREATE TABLE IF NOT EXISTS \`<project>.products_data_agent.shoe_items\`
   (Title STRING, Description STRING, Attributes STRING, Brand STRING)"
bq --project_id=<project> load --source_format=NEWLINE_DELIMITED_JSON \
  products_data_agent.shoe_items shoes.json
```

Start the UI:

```bash
uv run adk web --port 8765
```

---

### TC-01 — Application starts (N1)

1. `uv run python -c "from brand_search_optimization.agent import root_agent; print(root_agent.name)"`

**Expected:** prints `brand_search_optimization`. **Fail signal:** `TypeError: cannot create 'types.UnionType' instances` — the monkeypatch is back.

---

### TC-02 — `.env` is honoured (N2)

1. Set `GOOGLE_GENAI_USE_VERTEXAI=0` in `.env`.
2. `uv run python -c "import brand_search_optimization, os; print(os.environ['GOOGLE_GENAI_USE_VERTEXAI'])"`

**Expected:** `0`. **Fail signal:** `True` — `load_dotenv()` has moved back below the `setdefault` calls. Restore `=1` afterwards.

---

### TC-03 — Happy path, default search (F1–F3, F5, N4, N7)

1. Open `http://127.0.0.1:8765`, select `brand_search_optimization`.
2. Type `BSOAgentTestBrand`.

**Expected, in one turn:** the 3-product table from BigQuery → ranked keyword table with `kids shoes` at rank 1 → 3 competing product titles → comparison report with missing keywords and suggested titles.

**How to verify:** open the Events/trace panel. The tool calls should be exactly:

```text
keyword_finding_agent({'request': 'BSOAgentTestBrand'})
search_results_agent({'request': 'kids shoes'})
transfer_to_agent({'agent_name': 'comparison_root_agent'})
transfer_to_agent({'agent_name': 'comparison_generator_agent'})
```

**Fail signals:** more than \~6 tool calls (transfer ping-pong has returned); the brand name passed as the keyword; any request to choose a website.

---

### TC-04 — Named-site browser path (F4, N5)

1. Ensure `DISABLE_WEB_DRIVER=0` and Chrome is installed.
2. Type: `BSOAgentTestBrand, and search amazon.in for the keyword`

**Expected:** a Chrome window opens; console shows `🌐 Navigating to URL: https://www.amazon.in/s?k=kids+shoes` and `📄 Getting page source...`; the trace shows `site_browsing_agent({'request': 'amazon.in | kids shoes'})`; titles are real Amazon listings.

**Fail signals:** `search_results_agent` called with an invented `domain` argument (routing regression); Google searched instead of Amazon.

**Acceptable outcome:** the agent reports a CAPTCHA/bot check and falls back to grounded search. That is correct behaviour, not a bug.

---

### TC-05 — Named site as a follow-up (N10)

1. Run TC-03 to completion.
2. In the same session, type: `now check amazon.in for the top keyword instead`

**Expected:** `site_browsing_agent` is called. This specific case regressed once because the routing rule lived inside the numbered steps instead of a conversation-wide block, so it is worth re-checking after any prompt edit.

---

### TC-06 — Browser disabled (negative, N5)

1. Set `DISABLE_WEB_DRIVER=1`, restart.
2. Type: `BSOAgentTestBrand, and search amazon.in for the keyword`

**Expected:** no Chrome window. The tool raises `RuntimeError: Web driver is disabled...` and the agent reports it in plain language. **Fail signal:** Chrome launches anyway, or the process crashes with an unhandled traceback.

---

### TC-07 — Brand argument passing (N6)

1. Type a padded phrasing: `please look up the brand BSOAgentTestBrand for me`

**Expected:** `keyword_finding_agent` receives the brand, and the BigQuery tool is called as `get_product_details_for_brand({'brand': 'BSOAgentTestBrand'})` — not `{'brand': 'please look up the brand...'}`. Under the old signature this path returned nothing, because the brand was read from the raw message text.

---

### TC-08 — Unknown brand (negative)

1. Type `ThisBrandDoesNotExist`

**Expected:** the query returns no rows; the agent says it found no products rather than inventing any. **Fail signal:** fabricated products or keywords.

---

### TC-09 — Empty brand guard (negative, edge case)

```bash
uv run python -c "
from brand_search_optimization.tools import bq_connector as b
print(b.get_product_details_for_brand(''))"
```

**Expected:** `No brand provided.` — no BigQuery call attempted.

---

### TC-10 — BigQuery unavailable (negative)

1. `mv ~/.config/gcloud/application_default_credentials.json{,.bak}`
2. Type `BSOAgentTestBrand`

**Expected:** `BigQuery client initialization failed. Cannot execute query.` surfaced as a message, not a crash. Restore the file afterwards.

---

### TC-11 — Determinism (N8)

```bash
for i in 1 2 3; do
  uv run adk eval brand_search_optimization eval/data/eval_data1.evalset.json \
    --config_file_path eval/data/test_config.json 2>&1 | grep 'Tests passed'
done
```

**Expected:** `Tests passed: 1` all three times, with `tool_trajectory_avg_score = 1.000` in `.adk/eval_history/`. **Fail signal:** a varying keyword — check `temperature`/`seed` are still set on every agent.

---

### TC-12 — Eval harness genuinely asserts (N3, N9)

This is the meta-test. It proves the suite is not silently passing.

1. Copy `eval/data/*` to a temp directory.
2. In the copy, change one `intermediate_data.tool_uses[].name` to `definitely_not_a_tool`.
3. Run `AgentEvaluator.evaluate` against the **copied file**.

**Expected:** takes 60 s or more and raises `AssertionError: tool_trajectory_avg_score ... Expected 1.0, but got 0.666...`.

**Fail signal:** `PASSED in 0.0s` — the directory-vs-file bug is back and every eval result is meaningless.

---

### TC-13 — Unit tests, lint, types

```bash
uv run pytest tests -q      # expect: 2 passed
uv run ruff check .         # expect: All checks passed!
uv run mypy .               # expect: Success: no issues found in 17 source files
```

---

### TC-14 — Screenshot artifact (N5, edge case)

1. With the browser path active, ask for a screenshot of the results page.

**Expected:** the artifact opens as a viewable PNG in the UI. **Fail signal:** a corrupt or unopenable image — the `Image.tobytes()` bug has returned.

---

### TC-15 — Two browser runs in a row (edge case, N5)

1. Run TC-04.
2. Run TC-04 again without restarting anything.

**Expected:** the second run also opens Chrome successfully. **Fail signal:** `SessionNotCreatedException: Chrome instance exited` — a fixed `user-data-dir` has been reintroduced and the profile is locked.

---

### Other edge cases worth a pass

| Case | What to watch for |
| --- | --- |
| Brand substring collisions | `LIKE '%brand%'` means brand `Nike` also matches `NikeKids`. Expected, but verify the report is not misleading. |
| Brand with an apostrophe or `%` | Should be safe — the brand is a bound query parameter, not interpolated. |
| More than 3 matching products | Only 3 returned, by design (`LIMIT 3`). |
| Rapid repeated runs | Vertex may return `429 RESOURCE_EXHAUSTED`. This is quota, not a defect; wait and retry. |
| Non-English brand or catalog | Untested. Keyword inference quality is unverified for non-English text. |
| Empty `Description`/`Attributes` | Rendered as `N/A`; keyword quality degrades but should not error. |

## 7. Feature Checklist

Status values: **Verified** = confirmed by a run during development · **Pending** = needs a tester pass.

| # | Feature | Description | Files changed | Improvement over previous | Test | Expected result | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| N1 | Startup fix | Removed `typing._UnionGenericAlias` monkeypatch | `__init__.py` | App was unrunnable on Python 3.12.12+/3.13 | TC-01 | Agent imports, prints its name | Verified |
| N2 | `.env` honoured | `load_dotenv()` before `setdefault` | `__init__.py` | Backend config was silently discarded | TC-02 | `.env` value wins | Verified |
| N3 | Eval harness runs | Points at the evalset file, not its directory | `eval/test_eval.py` | Test passed in 0.0s without running the agent | TC-12 | Bogus expectation raises AssertionError after 60s+ | Verified |
| N4 | Grounded search | `google_search` replaces Selenium on the default path | `search_results/agent.py`, `search_results/prompt.py`, `pyproject.toml` | CAPTCHA no longer halts the pipeline | TC-03 | 3 real competing titles, no browser | Verified |
| N5 | Browser agent (per site) | Opt-in Selenium agent for a named site | `sub_agents/site_browsing/*` (new), `agent.py`, `prompt.py`, `constants.py`, `env.example`, `deploy.py`, `README.md` | Restores site-specific search that N4 removed; fixes 3 latent bugs | TC-04, TC-06, TC-14, TC-15 | Chrome opens the named site; disabled flag respected; screenshots open; 2nd run works | Verified |
| N6 | Real `brand` argument | `(tool_context)` → `(brand: str)` | `tools/bq_connector.py`, `tests/unit/test_tools.py`, `keyword_finding/prompt.py` | Worked only when the message *was* the brand | TC-07, TC-09 | Brand extracted from any phrasing; empty brand guarded | Verified |
| N7 | `AgentTool` conversion | Data-gathering agents become tools | `agent.py`, `prompt.py`, `search_results/prompt.py`, `keyword_finding/prompt.py` | Eliminates transfer ping-pong; enables N4 | TC-03 | Exactly 4 tool calls, pipeline in 1 turn | Verified |
| N8 | Determinism | `temperature=0.0, seed=42` + mechanical rank-1 rule | `constants.py`, 4 agent modules, `keyword_finding/prompt.py`, `test_config.json` | Eval flaked 1 run in 3 at threshold 1.0 | TC-11 | 3 runs, trajectory 1.000 each | Verified |
| N9 | Evalset migrated | `EvalSet` schema, re-recorded, thresholds `1.0 / 0.3` | `eval/data/eval_data1.evalset.json`, `eval/data/test_config.json` | Referenced deleted tools; `0.2` thresholds were meaningless | TC-11, TC-12 | Passes at 1.0; fails on a wrong tool/argument | Verified |
| N10 | Routing + docs | Conversation-wide `<Choosing a search tool>` block | `prompt.py`, `README.md`, `pyproject.toml` | Mid-conversation site requests were mis-routed | TC-05 | Follow-up "check amazon.in" reaches the browser agent | Verified |

### Pre-existing features to regression-check

| # | Feature | Test | Expected result | Status |
| --- | --- | --- | --- | --- |
| F1 | BigQuery catalog lookup | TC-03, TC-08, TC-10 | 3 products returned; unknown brand handled; client failure surfaced as a message | Pending |
| F2 | Keyword discovery + ranking | TC-03 | Ranked table, generic first, brand-name keywords dropped, one per row | Pending |
| F5 | Comparison generator/critic | TC-03 | Side-by-side report with missing keywords and suggested titles | Pending |
| F6 | Web UI and CLI front ends | TC-03 via both `adk web` and `adk run` | Identical behaviour on both | Pending |
| F8 | Unit tests, lint, types | TC-13 | 2 passed; ruff clean; mypy clean on 17 files | Verified |
| F9 | Agent Engine deployment | `uv run python deployment/deploy.py --create` | Deploys with `DISABLE_WEB_DRIVER=1`; F3 works remotely, F4 does not | **Not tested** |

### Sign-off

| Item | Value |
| --- | --- |
| Tested by |  |
| Date |  |
| Environment (project / region / model) |  |
| Overall result |  |
| Defects raised |  |

### Known limitations to record, not retest

- `LIMIT 3` — three products per run by design.
- Vertex may return `429 RESOURCE_EXHAUSTED` under rapid repeated runs; quota, not a defect.
- `response_match_score` stays at `0.3` because grounded search results change daily; it cannot be pinned the way the trajectory can.
- Non-English catalogs are unverified.
- Deployment to Agent Engine has not been exercised in this cycle.
