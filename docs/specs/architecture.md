# Architecture Specification — Supercrew Dynamic Orchestration

**Version:** 1.1
**Date:** 2026-03-13
**Author:** Architect Agent
**Status:** Draft — awaiting owner review

---

## 1. Problem Statement

The current system is config-driven but static: every crew is hand-authored YAML.
Keyword-based routing (`task_router.py`) picks from a fixed set of templates.
This works for known task shapes but fails when the user's task doesn't match
any pre-built crew, and it can't evolve crews based on experience.

The goal is a **dynamic planner layer** that:

1. Accepts a free-form task (CLI arg or `input.md`)
2. Uses a cloud LLM via LiteLLM to analyze the task and decide the crew shape
3. Either **reuses** an existing crew, **adapts** one, or **generates** a new one
4. Persists generated crews for future reuse by name
5. Still supports the fast path: `start.sh --crew deep_research "my topic"`

---

## 2. Model Inventory

Three models are exposed through a single LiteLLM proxy. Their capabilities
determine how the system assigns work.

| Profile | Route | Size | Key traits | Typical role |
|---------|-------|------|-----------|--------------|
| `cloud_fast` | `openai/cloud-fast` | Cloud | **Most capable model.** Fast, high quality. Best reasoning. | **Planner**, synthesis, analysis, complex decisions |
| `clever` | `openai/local-clever` | 27B local | Strong reasoning, good for sustained analytical work. | Analysis, auditing, evidence normalization, synthesis |
| `swarm` | `openai/local-swarm` | 9B local + vision | Small, fast. **16 parallel agents** on this route. Vision-capable. | Parallel research workers, first-pass extraction, image analysis |

**Critical facts for the planner:**

- `cloud_fast` is the smartest model and must be used for **crew planning** (the
  planner call itself). It can also be assigned to crew agents when quality matters
  more than cost.
- `swarm` can serve **up to 16 concurrent agents**. This is the key advantage of
  the swarm route — it's not just cheap, it's massively parallel. The planner
  should exploit this by creating async research branches when the task benefits
  from breadth.
- `clever` is the local workhorse for tasks that need more reasoning than `swarm`
  can provide but don't justify cloud cost.
- Vision tasks (image analysis, screenshot reading) **must** use `swarm` — it's
  the only model with vision capability.

---

## 3. Design Principles

1. **Planner generates structure, not raw YAML.** The LLM emits a structured
   JSON crew spec. Python validates it and renders YAML. This prevents
   invalid task graphs and bad agent/task name references.

2. **Compose from known building blocks.** The planner picks from registered
   role archetypes, tool names, model profiles, and task patterns — it does
   not invent arbitrary CrewAI syntax.

3. **Two-tier crew storage.** Hand-authored crews in `config/crews/` are never
   overwritten by the planner. Generated crews live in `config/generated_crews/`.
   A registry tracks both.

4. **Reuse before generation.** The planner checks existing crews first.
   Generation only fires when nothing fits.

5. **Deterministic path stays fast.** If the user names a crew explicitly
   (`--crew research`), the planner is skipped entirely. No LLM call, no
   latency.

6. **Planner handbook, not full docs.** The planner prompt includes a compact
   handbook (~2K tokens) distilled from CrewAI docs — not the full 100K+ corpus.

7. **Effort is a first-class concept.** Every crew run has an effort level that
   controls how much iteration, time, and parallelism agents get. This lets the
   same crew shape serve both quick lookups and deep investigations.

---

## 4. Effort System

Effort is a user-facing knob that controls how much work agents put in.
It maps to concrete CrewAI parameters under the hood.

### 4.1 Effort Levels

| Level | Name | `max_iter` | `max_execution_time` | Swarm parallelism | Planning | Typical use |
|-------|------|-----------|---------------------|-------------------|----------|------------|
| 1 | `quick` | 5 | 60s | 1–2 agents | off | Fast lookup, simple question |
| 2 | `standard` | 15 | 180s | 2–4 agents | off | Normal research, analysis |
| 3 | `thorough` | 25 | 300s | 4–8 agents | on | Deep research, verification |
| 4 | `exhaustive` | 40 | 600s | 8–16 agents | on | Maximum coverage, multi-source |

**How effort is specified:**

```bash
# CLI flag
./start.sh --effort thorough "find jazz festivals in Berlin 2026"

# Environment variable
EFFORT=quick ./start.sh "what time is it in Tokyo"

# Default: standard (level 2)
```

**How effort maps to CrewAI parameters:**

The effort level is resolved at crew build time. `crew_builder.py` reads the
effort config and applies it:

- **Agent-level**: `max_iter` and `max_execution_time` are set per agent based
  on effort level. These are CrewAI's native execution control parameters.
- **Agent-level**: `max_retry_limit` scales with effort (1 for quick, 3 for exhaustive).
- **Crew-level**: `planning=True` and `planning_llm` are enabled at effort ≥3.
  CrewAI's built-in AgentPlanner pre-plans task execution before the crew runs.
  The `planning_llm` uses the `cloud_fast` model (smartest available).
- **Swarm parallelism**: At higher effort, the planner creates more async
  research branches assigned to `swarm` agents, exploiting the 16-agent capacity.
- **Agent-level**: `reasoning=True` and `max_reasoning_attempts` can be enabled
  for `clever`/`cloud_fast` agents at effort ≥3, giving them strategic planning
  ability before acting.

**Effort config file**: `config/effort.yaml`

```yaml
levels:
  quick:
    max_iter: 5
    max_execution_time: 60
    max_retry_limit: 1
    planning: false
    reasoning: false
    max_swarm_agents: 2

  standard:
    max_iter: 15
    max_execution_time: 180
    max_retry_limit: 2
    planning: false
    reasoning: false
    max_swarm_agents: 4

  thorough:
    max_iter: 25
    max_execution_time: 300
    max_retry_limit: 2
    planning: true
    reasoning: true
    max_reasoning_attempts: 2
    max_swarm_agents: 8

  exhaustive:
    max_iter: 40
    max_execution_time: 600
    max_retry_limit: 3
    planning: true
    reasoning: true
    max_reasoning_attempts: 3
    max_swarm_agents: 16

defaults:
  effort: standard
```

### 4.2 Effort and the Planner

The planner receives the effort level as input and uses it to decide:

- How many agents to create (quick → 2–3, exhaustive → up to 8)
- How many async research branches to fan out (scales with `max_swarm_agents`)
- Whether to include auditing/verification agents (effort ≥ thorough)
- Whether to include a coverage audit step (effort = exhaustive)

The planner does **not** set `max_iter` or `max_execution_time` directly —
those are applied by `crew_builder.py` at build time based on the effort level.
This keeps the planner's job simpler and the effort config centrally managed.

---

## 5. Swarm Concurrency Model

The `swarm` model route can serve **16 concurrent agents**. This is the
system's primary scaling advantage and the planner must be aware of it.

### 5.1 Concurrency in `models.yaml`

```yaml
models:
  swarm:
    provider_model: openai/local-swarm
    temperature: 0.2
    context_window: 6144
    max_concurrency: 16          # NEW — how many agents can run in parallel
    has_vision: true             # NEW — can process images
    strengths: [parallel_research, brainstorming, fanout, vision]
    default_role: worker

  clever:
    provider_model: openai/local-clever
    temperature: 0.2
    context_window: 32768
    max_concurrency: 2           # local, limited by GPU memory
    has_vision: false
    strengths: [reasoning, synthesis, critique, medium_context_verification]
    default_role: synthesizer

  cloud_fast:
    provider_model: openai/cloud-fast
    temperature: 0.2
    context_window: 32000
    max_concurrency: 4           # cloud rate limits
    has_vision: false
    strengths: [planning, reasoning, fast_routing, formatting, escalation_review]
    default_role: planner
```

### 5.2 How the Planner Uses Concurrency

The planner sees `max_concurrency` per model and uses it to decide how many
async agents to assign to each route:

- If a task benefits from breadth (research, comparison, multi-source), the
  planner creates N async tasks on `swarm`, where N ≤ `max_swarm_agents`
  from the effort config and N ≤ `max_concurrency` from models.yaml.
- A sync merge/synthesis task on `clever` or `cloud_fast` consumes all async
  branches via `context`.
- The planner never assigns more async agents to a model than its
  `max_concurrency` allows.

**Example: effort=thorough, research task**

```
swarm agent 1: search for facts         (async)
swarm agent 2: search for pricing       (async)
swarm agent 3: search for risks         (async)
swarm agent 4: search for alternatives  (async)
  ↓ all four complete
clever agent: merge + analyze           (sync, context=[1,2,3,4])
clever agent: audit coverage            (sync)
cloud_fast agent: final synthesis       (sync)
```

This saturates 4 of the 16 swarm slots. At effort=exhaustive, the planner
could use 8–16 swarm agents with more granular search facets.

### 5.3 Vision Tasks

When the task involves images (screenshots, documents as images, visual
analysis), the planner **must** assign those tasks to `swarm` agents
since it's the only model with vision capability. The planner detects
vision requirements from task text keywords (image, screenshot, photo,
visual, diagram, chart) and from tool requirements.

---

## 6. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  start.sh / CLI                                             │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Input resolution                                      │  │
│  │  • --crew NAME    → skip planner, use named crew       │  │
│  │  • --task "..."   → free-form task text                │  │
│  │  • --input FILE   → read task from file                │  │
│  │  • --save NAME    → save generated crew under this name│  │
│  │  • --effort LEVEL → quick|standard|thorough|exhaustive │  │
│  └──────────────┬─────────────────────────────────────────┘  │
│                 │                                             │
│                 ▼                                             │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Dispatcher (runner.py)                                │  │
│  │  • If --crew given → load & execute (existing path)    │  │
│  │  • Else → invoke Planner                               │  │
│  │  • Apply effort level to crew at build time            │  │
│  └──────────────┬─────────────────────────────────────────┘  │
│                 │                                             │
│                 ▼                                             │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Planner  (NEW — planner.py)                           │  │
│  │  Uses: cloud_fast (smartest model)                     │  │
│  │  1. Extract task features                              │  │
│  │  2. Query crew registry for candidates                 │  │
│  │  3. Call cloud_fast LLM with:                          │  │
│  │     • task text + effort level                         │  │
│  │     • candidate crews (summaries)                      │  │
│  │     • building-block catalog                           │  │
│  │     • planner handbook                                 │  │
│  │  4. LLM returns a CrewSpec (structured JSON)           │  │
│  │  5. Validate CrewSpec against schema                   │  │
│  │  6. Decide: reuse | adapt | generate                   │  │
│  │  7. If new/adapted → render YAML → save to             │  │
│  │     config/generated_crews/                            │  │
│  │  8. Update registry                                    │  │
│  │  9. Return crew config to dispatcher                   │  │
│  └──────────────┬─────────────────────────────────────────┘  │
│                 │                                             │
│                 ▼                                             │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Crew Builder (crew_builder.py)                        │  │
│  │  • Instantiate agents + tasks from config              │  │
│  │  • Apply effort overrides (max_iter, max_exec_time,    │  │
│  │    planning, reasoning)                                │  │
│  │  • Build Crew object                                   │  │
│  └──────────────┬─────────────────────────────────────────┘  │
│                 │                                             │
│                 ▼                                             │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Execution                                             │  │
│  │  Crew.kickoff() → agents work → result                 │  │
│  └────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 7. Data Model

### 7.1 CrewSpec — Planner Output Schema

This is the structured object the LLM returns. Python validates it
before any YAML is rendered.

```json
{
  "decision": "reuse | adapt | generate",
  "reuse_crew": "deep_research",
  "base_crew": "research",
  "crew_spec": {
    "name": "event_deep_dive",
    "description": "Multi-source event research with pricing verification",
    "process": "sequential",
    "tags": ["events", "research", "pricing"],
    "query_archetypes": [
      "find events in {location}",
      "list {category} with prices"
    ],
    "agents": [
      {
        "name": "coverage_researcher",
        "role_archetype": "researcher",
        "role": "Coverage Researcher",
        "goal": "Build a broad candidate list covering the query space.",
        "backstory": "Search widely, use source hints, return compact tables.",
        "model_profile": "swarm",
        "tools": ["searxng_search", "pdf_extract"],
        "allow_delegation": false
      },
      {
        "name": "pricing_researcher",
        "role_archetype": "researcher",
        "role": "Pricing Researcher",
        "goal": "Verify pricing and availability from official sources.",
        "backstory": "Check ticket pages and official calendars. Never estimate.",
        "model_profile": "swarm",
        "tools": ["searxng_search", "webpage_fetch"],
        "allow_delegation": false
      },
      {
        "name": "analyst",
        "role_archetype": "analyst",
        "role": "Senior Analyst",
        "goal": "Merge research into an evidence-backed answer.",
        "backstory": "Separate confirmed facts from unconfirmed claims.",
        "model_profile": "clever",
        "tools": [],
        "allow_delegation": false
      }
    ],
    "tasks": [
      {
        "name": "map_candidates",
        "description": "Build a candidate list for: {topic}\n...",
        "expected_output": "A compact candidate table.",
        "agent": "coverage_researcher",
        "context": [],
        "async_execution": true
      },
      {
        "name": "verify_pricing",
        "description": "Verify pricing details for: {topic}\n...",
        "expected_output": "A pricing verification table.",
        "agent": "pricing_researcher",
        "context": [],
        "async_execution": true
      },
      {
        "name": "synthesize",
        "description": "Merge research into a final answer for: {topic}",
        "expected_output": "Evidence-backed answer with tables and sources.",
        "agent": "analyst",
        "context": ["map_candidates", "verify_pricing"],
        "async_execution": false
      }
    ]
  }
}
```

**Validation rules (enforced in Python, not by the LLM):**

| Rule | Constraint |
|------|-----------|
| Agent count | 2–8 per crew |
| Task count | 1–12 per crew |
| Agent names | Must be unique, snake_case, ≤40 chars |
| Task names | Must be unique, snake_case, ≤40 chars |
| Task.agent | Must reference a defined agent name |
| Task.context | Must reference defined task names; no cycles |
| Tools | Must exist in `config/tools.yaml` (registered tools only) |
| Model profiles | Must exist in `config/models.yaml` |
| Process | `sequential` or `hierarchical` only |
| Async tasks | If async, must not be the final task; must have a sync consumer |
| Async agent count per model | Must not exceed that model's `max_concurrency` |
| `{topic}` placeholder | At least one task description must contain `{topic}` |
| Vision tasks | Tasks requiring vision must use a model with `has_vision: true` |

### 7.2 Crew Registry — `config/crew_registry.yaml`

```yaml
crews:
  deep_research:
    source: manual            # manual | generated
    description: "Multi-agent deep research with coverage audit and evidence normalization"
    tags: [research, events, pricing, verification]
    query_archetypes:
      - "list all {category} in {location}"
      - "find {category} with dates and prices"
    required_tools: [searxng_search, webpage_fetch, pdf_fetch, pdf_extract]
    required_capabilities: [web, pdf, parallel]
    agent_count: 7
    process: sequential
    created_at: "2026-03-10"
    last_used_at: "2026-03-13"
    use_count: 14
    success_count: 12
    failure_count: 2
    human_reviewed: true
    supersedes: null
    superseded_by: null

  auto_event_scout:
    source: generated
    base_crew: research       # adapted from this crew
    description: "Lightweight event scouting for quick overviews"
    tags: [events, research]
    query_archetypes:
      - "what events are happening in {location}"
    required_tools: [searxng_search]
    required_capabilities: [web]
    agent_count: 3
    process: sequential
    created_at: "2026-03-13"
    last_used_at: "2026-03-13"
    use_count: 1
    success_count: 1
    failure_count: 0
    human_reviewed: false
    supersedes: null
    superseded_by: null
```

### 7.3 Building-Block Catalogs

These are static reference files the planner uses to compose crews
from known, tested components.

#### `config/catalogs/role_archetypes.yaml`

```yaml
archetypes:
  researcher:
    description: "Gathers information from web sources"
    typical_tools: [searxng_search, webpage_fetch]
    typical_model: swarm

  deep_researcher:
    description: "Gathers and verifies from official sources, PDFs, primary documents"
    typical_tools: [searxng_search, webpage_fetch, pdf_fetch, pdf_extract]
    typical_model: swarm

  analyst:
    description: "Reasons over gathered material, builds structured recommendations"
    typical_tools: []
    typical_model: clever

  auditor:
    description: "Checks completeness, finds gaps, validates coverage"
    typical_tools: [searxng_search, webpage_fetch]
    typical_model: clever

  writer:
    description: "Polishes output for readability and conciseness"
    typical_tools: []
    typical_model: cloud_fast

  normalizer:
    description: "Merges conflicting sources into strict evidence tables"
    typical_tools: []
    typical_model: clever

  briefer:
    description: "Collapses multiple outputs into one compact summary"
    typical_tools: []
    typical_model: clever
```

#### `config/catalogs/task_patterns.yaml`

```yaml
patterns:
  web_search:
    description: "Search the web for information about {topic}"
    typical_agent_archetype: researcher
    supports_async: true

  source_verification:
    description: "Verify claims from official/primary sources"
    typical_agent_archetype: deep_researcher
    supports_async: true

  pricing_verification:
    description: "Verify pricing and availability details"
    typical_agent_archetype: deep_researcher
    supports_async: true

  coverage_audit:
    description: "Check for missing candidates and weak coverage"
    typical_agent_archetype: auditor
    supports_async: false

  evidence_merge:
    description: "Merge verified facts into a strict evidence table"
    typical_agent_archetype: normalizer
    supports_async: false

  synthesis:
    description: "Produce a structured recommendation from gathered material"
    typical_agent_archetype: analyst
    supports_async: false

  final_write:
    description: "Polish the final output for the target audience"
    typical_agent_archetype: writer
    supports_async: false

  briefing:
    description: "Collapse multiple research outputs into one compact brief"
    typical_agent_archetype: briefer
    supports_async: false
```

---

## 8. Planner Design

### 8.1 Planner Prompt Structure

The planner receives a single LLM call with these sections:

1. **System prompt** — planner handbook (rules, constraints, archetypes)
2. **User message** containing:
   - The task text
   - The effort level
   - Candidate crews from registry (name, description, tags, archetypes — not full YAML)
   - The building-block catalogs (role archetypes + task patterns)
   - Available tools list (from `config/tools.yaml`)
   - Available model profiles (from `config/models.yaml` — name, strengths,
     `max_concurrency`, `has_vision`)
   - Effort constraints (`max_swarm_agents` for the selected effort level)

The planner handbook is a static file: `config/planner_handbook.md` (~2K tokens).
It distills the key CrewAI rules the planner must follow:

- Prefer sequential process; use hierarchical only for >5 agents with delegation
- Keep tool access minimal per agent
- Use task `context` only where needed — avoid long chains
- Async tasks must have a downstream sync consumer that lists them in `context`
- Keep roles specialized and concrete
- Use `{topic}` as the interpolation variable
- Prefer compact structured outputs
- 2–8 agents, 1–12 tasks per crew
- Assign `swarm` to parallel research workers — exploit its 16-agent concurrency
- Assign `clever` to analytical/synthesis tasks that need sustained reasoning
- Assign `cloud_fast` to tasks that need the highest quality (complex synthesis,
  final answers for important queries) — use sparingly since it's cloud
- Use `swarm` for any task that needs vision (image/screenshot analysis)
- Scale the number of async `swarm` branches with effort level
- Never exceed a model's `max_concurrency` with simultaneous async agents

### 8.2 Planner Model Selection

The planner always uses **`cloud_fast`** — the most capable model — for the
planning call itself. Rationale:

- Crew design is a high-stakes decision that affects the entire run
- `cloud_fast` has the best reasoning and structured output capability
- One planning call is cheap; the execution phase is where cost matters
- Local models (`clever`, `swarm`) are reserved for crew execution

Override: `config/models.yaml` can define a `planner` profile. If present,
it takes precedence over `cloud_fast`.

### 8.3 Matching Algorithm

Before calling the LLM, the planner applies deterministic pre-filtering:

```
1. Extract required capabilities from task text:
   - mentions of PDF/documents → requires pdf tools
   - mentions of web/search/find → requires web tools
   - mentions of compare/parallel → prefers parallel process
   - mentions of verify/official → prefers audit/verification agents

2. Filter registry to crews whose required_capabilities are satisfied

3. Score remaining candidates:
   - tag overlap with extracted task features
   - query_archetype similarity (simple token overlap)
   - recency bonus (last_used_at)
   - success rate bonus (success_count / use_count)

4. Pass top 5 candidates to LLM with their summaries

5. LLM decides: reuse | adapt | generate
```

### 8.4 Planner LLM Response Format

The planner is called with `output_json` pointing to a Pydantic model
(`CrewSpec`), so the response is structured JSON. The LLM never writes
raw YAML.

If the LLM returns `decision: "reuse"`, no new YAML is generated.
If `decision: "adapt"`, the base crew YAML is loaded, the spec's
modifications are applied (add/remove agents, modify tasks), and a new
YAML is saved.
If `decision: "generate"`, a fresh YAML is rendered from the spec.

---

## 9. CLI Interface

### 9.1 `start.sh` — Updated

```bash
# Existing: explicit crew (no planner call)
./start.sh --crew deep_research "find jazz festivals in Berlin 2026"

# New: dynamic planning (planner picks or generates the crew)
./start.sh "find jazz festivals in Berlin 2026"

# New: with effort level
./start.sh --effort thorough "find jazz festivals in Berlin 2026"

# New: dynamic planning + save the generated crew for reuse
./start.sh --save jazz_events "find jazz festivals in Berlin 2026"

# New: read task from input.md
./start.sh --input input.md

# New: read task from input.md + explicit crew + effort
./start.sh --crew deep_research --effort exhaustive --input input.md

# Existing: scenario mode (unchanged)
SCENARIO=deep_research ./start.sh
```

### 9.2 Environment Variables (additive — existing ones stay)

| Variable | Purpose | Default |
|----------|---------|---------|
| `PLANNER_MODEL` | Override planner model profile | `cloud_fast` |
| `PLANNER_DISABLED` | Set to `1` to skip planner, fall back to keyword routing | `0` |
| `CREW_SAVE_NAME` | Save the generated crew under this name | (none) |
| `INPUT_FILE` | Read task text from this file | (none) |
| `EFFORT` | Effort level: `quick`, `standard`, `thorough`, `exhaustive` | `standard` |

---

## 10. File System Layout — Changes

```
config/
  models.yaml                    # MODIFY — add max_concurrency, has_vision
  model_policy.yaml              # NEW — model assignment guidelines for planner
  tools.yaml                     # existing — unchanged
  effort.yaml                    # NEW — effort level definitions
  routing.yaml                   # existing — kept as fallback
  crew_registry.yaml             # NEW — crew metadata index
  planner_handbook.md            # NEW — compact planner rules (~2K tokens)
  catalogs/                      # NEW
    role_archetypes.yaml         # NEW — known agent role templates
    task_patterns.yaml           # NEW — known task shape templates
  crews/                         # existing — hand-authored crews
    research.yaml
    analysis.yaml
    synthesis.yaml
    parallel_research.yaml
    deep_research.yaml
    deep_research_cloud_review.yaml
  generated_crews/               # NEW — planner-created crews
    (auto-generated YAMLs here)
  scenarios/                     # existing — unchanged

src/agent_mesh/
  __init__.py                    # existing
  config_loader.py               # MODIFY — add loaders for registry, catalogs, handbook, effort, model_policy
  llm_registry.py                # existing — unchanged
  agent_factory.py               # MODIFY — accept effort overrides
  crew_builder.py                # MODIFY — apply effort level (max_iter, planning, reasoning)
  task_router.py                 # existing — kept as fallback
  tools.py                       # existing — unchanged
  compat.py                      # existing — unchanged
  runner.py                      # MODIFY — add planner dispatch path + effort
  experiment_runner.py           # existing — unchanged
  planner.py                     # NEW — planner logic
  crew_spec.py                   # NEW — CrewSpec Pydantic model + validation
  crew_renderer.py               # NEW — render CrewSpec → YAML
  registry.py                    # NEW — crew registry read/write/match
```

---

## 11. Model Policy — External Config

The model assignment guidelines live in `config/model_policy.yaml`. This file
is read by the planner at runtime and included in the planner prompt. You can
edit it anytime to change how the planner assigns models to agents — no code
changes needed.

### 11.1 `config/model_policy.yaml`

```yaml
# Model assignment policy for the planner.
# This file is injected into the planner prompt so the LLM knows
# how to assign models. Edit this to tune behavior.

models:
  cloud_fast:
    description: >
      Cloud-hosted, most capable model. Best reasoning, fastest for its
      quality tier. Use for crew planning itself, complex synthesis,
      final answers on important queries, and any task where quality
      is critical.
    when_to_use:
      - Crew planning (the planner call itself)
      - Final synthesis on high-stakes or complex queries
      - Tasks requiring the strongest reasoning
      - Tie-breaking or adjudication between conflicting sources
    when_not_to_use:
      - Simple research or data gathering (overkill)
      - Parallel worker tasks (wastes cloud budget)
    cost_note: "Cloud — use judiciously for execution agents"

  clever:
    description: >
      Local 27B model. Strong reasoning, good sustained analytical work.
      Runs locally with limited concurrency (2 simultaneous).
    when_to_use:
      - Analysis and synthesis tasks
      - Evidence normalization and auditing
      - Coverage audits and completeness checks
      - Briefing and summarization
      - Any reasoning task that doesn't justify cloud cost
    when_not_to_use:
      - Parallel research branches (only 2 concurrent — use swarm)
      - Vision/image tasks (no vision capability)
      - Tasks needing the absolute best quality (use cloud_fast)
    cost_note: "Free (local) — preferred for analytical work"

  swarm:
    description: >
      Local 9B model with vision. Small but fast. The key advantage is
      massive parallelism: up to 16 concurrent agents. Also the only
      model with vision capability.
    when_to_use:
      - Parallel research branches (exploit 16-agent concurrency)
      - First-pass data gathering and extraction
      - Web search tasks
      - Image/screenshot/visual analysis (only model with vision)
      - Any task that benefits from breadth over depth
    when_not_to_use:
      - Complex reasoning or synthesis (too small)
      - Final answers (quality insufficient)
      - Tasks requiring deep analytical thinking
    cost_note: "Free (local) — use liberally for parallel workers"

assignment_rules:
  - "Maximize swarm parallelism for research: create multiple async tasks on swarm"
  - "Use clever for merge/synthesis after swarm branches complete"
  - "Reserve cloud_fast for the planner call and high-value final synthesis"
  - "Never assign vision tasks to clever or cloud_fast — only swarm has vision"
  - "At effort=quick, use only swarm+clever (skip cloud_fast for execution)"
  - "At effort=exhaustive, cloud_fast can be used for final synthesis"
  - "The number of simultaneous async agents on a model must not exceed its max_concurrency"
```

This file serves two purposes:

1. **Planner input**: The planner reads it and includes it in the prompt context,
   so `cloud_fast` (the planner model) knows how to assign models to agents.
2. **Human tuning**: You edit this file to change assignment strategy without
   touching code. For example, if you add a new model to LiteLLM, you add it
   here and the planner immediately knows about it.

---

## 12. Module Specifications

### 12.1 `crew_spec.py` — Data Model + Validation

```python
# Pydantic models
class AgentSpec(BaseModel):
    name: str               # snake_case, unique within crew
    role_archetype: str     # must exist in role_archetypes catalog
    role: str               # display name
    goal: str
    backstory: str
    model_profile: str      # must exist in models.yaml
    tools: list[str]        # must exist in tools.yaml
    allow_delegation: bool = False

class TaskSpec(BaseModel):
    name: str               # snake_case, unique within crew
    description: str        # must contain {topic} in at least one task
    expected_output: str
    agent: str              # must reference an AgentSpec.name
    context: list[str] = [] # must reference other TaskSpec.names; no cycles
    async_execution: bool = False

class CrewSpecPayload(BaseModel):
    name: str
    description: str
    process: Literal["sequential", "hierarchical"]
    tags: list[str]
    query_archetypes: list[str]
    agents: list[AgentSpec]
    tasks: list[TaskSpec]

class PlannerResponse(BaseModel):
    decision: Literal["reuse", "adapt", "generate"]
    reuse_crew: str | None = None
    base_crew: str | None = None
    crew_spec: CrewSpecPayload | None = None

# Validation function
def validate_crew_spec(
    spec: CrewSpecPayload,
    available_tools: set[str],
    available_models: set[str],
    model_concurrency: dict[str, int],
) -> list[str]:
    """Returns list of error strings. Empty = valid.
    Checks async agent counts against model concurrency limits."""
```

### 12.2 `planner.py` — Core Planner

```python
def plan_crew(
    task_text: str,
    effort: str,             # NEW — effort level name
    llms: LLMRegistry,
    registry: CrewRegistry,
    catalogs: dict,
    handbook: str,
    model_policy: str,       # NEW — contents of model_policy.yaml
    effort_config: dict,     # NEW — parsed effort.yaml
    available_tools: set[str],
    available_models: set[str],
    model_concurrency: dict[str, int],  # NEW — max_concurrency per model
) -> PlannerResult:
    """
    1. Extract task features (deterministic)
    2. Query registry for candidate crews
    3. Build planner prompt (includes model_policy + effort constraints)
    4. Call cloud_fast LLM → get PlannerResponse
    5. Validate (including concurrency limits)
    6. Return PlannerResult with crew config dict + metadata
    """

class PlannerResult:
    decision: str               # reuse | adapt | generate
    crew_name: str              # name of the crew to execute
    crew_config: dict           # loadable by crew_builder.build_crew()
    is_new: bool                # True if YAML was generated
    save_path: Path | None      # path to saved YAML (if new)
```

### 12.3 `crew_renderer.py` — Spec to YAML

```python
def render_crew_yaml(spec: CrewSpecPayload) -> str:
    """Convert a validated CrewSpecPayload into a crew YAML string."""

def save_generated_crew(spec: CrewSpecPayload, name: str | None = None) -> Path:
    """Render and write to config/generated_crews/{name}.yaml.
    Returns the path."""
```

### 12.4 `registry.py` — Crew Registry

```python
class CrewRegistry:
    def load(self) -> None
    def save(self) -> None
    def list_crews(self) -> list[CrewEntry]
    def get(self, name: str) -> CrewEntry | None
    def find_candidates(self, features: TaskFeatures, limit: int = 5) -> list[CrewEntry]
    def register(self, entry: CrewEntry) -> None
    def record_usage(self, name: str, success: bool) -> None
```

### 12.5 `runner.py` — Modified Dispatch

The existing `run_task()` gains a new path:

```python
def run_task(task_text, *, crew_template=None, save_name=None,
             effort="standard", ...):
    if crew_template:
        # Existing fast path — load named crew, skip planner
        ...
    else:
        # New dynamic path — invoke planner
        planner_result = plan_crew(task_text, effort=effort, ...)
        if planner_result.is_new and save_name:
            save_generated_crew(planner_result.spec, save_name)
        crew_config = planner_result.crew_config

    # Build crew with effort overrides applied
    effort_config = load_effort_config()
    crew = build_crew(
        config=crew_config, llms=llms, tools=tools,
        effort=effort, effort_config=effort_config,
    )
    return crew.kickoff(inputs=final_inputs)
```

### 12.6 `crew_builder.py` — Effort Application

```python
def build_crew(config, llms, tools, effort="standard", effort_config=None):
    """
    Build a Crew from config. If effort_config is provided, override:
    - Agent max_iter, max_execution_time, max_retry_limit
    - Agent reasoning + max_reasoning_attempts (effort >= thorough)
    - Crew planning + planning_llm (effort >= thorough)
    """
```

### 12.7 `config_loader.py` — New Loaders

```python
def load_crew_config(template_name: str) -> dict:
    """Try config/crews/ first, then config/generated_crews/."""

def load_registry() -> dict:
    """Load config/crew_registry.yaml."""

def load_catalogs() -> dict:
    """Load role_archetypes.yaml + task_patterns.yaml."""

def load_planner_handbook() -> str:
    """Load config/planner_handbook.md as string."""

def load_model_policy() -> str:
    """Load config/model_policy.yaml as raw string (for planner prompt)."""

def load_effort_config() -> dict:
    """Load config/effort.yaml."""
```

---

## 13. Planner Handbook — Key Rules

This will live at `config/planner_handbook.md`. Summary of what it contains:

1. **Process selection**: Default to `sequential`. Use `hierarchical` only
   when >5 agents need coordinated delegation.

2. **Agent design**: Keep roles specialized. One clear goal per agent.
   Minimize tool access — only give tools the agent actually needs.

3. **Task design**: Use `context` to pass upstream output. Async tasks
   must have a downstream sync task that consumes them. At least one
   task must contain `{topic}` in its description.

4. **Model assignment**: Follow `config/model_policy.yaml` — that file
   has the detailed rules. Summary:
   - `swarm` → parallel research workers, vision tasks, breadth
   - `clever` → analysis, synthesis, auditing, reasoning
   - `cloud_fast` → highest-quality synthesis, complex decisions (sparingly)

5. **Crew sizing**: Scale with effort level:
   - `quick` → 2–3 agents, no async branches
   - `standard` → 3–4 agents, 1–2 async branches
   - `thorough` → 4–6 agents, 2–4 async branches
   - `exhaustive` → 5–8 agents, 4–8+ async branches

6. **Swarm parallelism**: Exploit the 16-agent swarm capacity. When the
   task benefits from breadth, create multiple async tasks on `swarm` agents.
   The effort level's `max_swarm_agents` is the ceiling.

7. **Reuse preference**: If an existing crew scores >0.7 match, reuse it.
   If >0.4, adapt it. Below 0.4, generate new.

8. **Output format**: The planner must return valid JSON matching the
   `PlannerResponse` schema. No markdown, no YAML, no commentary.

---

## 14. Crew Lifecycle

```
  Task arrives
       │
       ▼
  ┌─ --crew given? ──── YES ──→ Load named crew → Execute → Record usage
  │       │
  │      NO
  │       │
  │       ▼
  │  Planner: extract features
  │       │
  │       ▼
  │  Registry: find candidates
  │       │
  │       ▼
  │  LLM: decide reuse/adapt/generate
  │       │
  │  ┌────┼────────────┐
  │  │    │             │
  │ reuse adapt     generate
  │  │    │             │
  │  │  load base     render new YAML
  │  │  apply mods    save to generated_crews/
  │  │  save new      register in registry
  │  │    │             │
  │  └────┴──────┬──────┘
  │              │
  │              ▼
  │         Execute crew
  │              │
  │              ▼
  │         Record usage (success/failure)
  │              │
  │              ▼
  └──────── Return result
```

### Crew Promotion Path

```
generated_crews/auto_event_scout.yaml
  ↓ (user reviews, refines)
crews/event_scout.yaml  (human_reviewed: true)
  ↓ (registry updated: supersedes auto_event_scout)
```

The planner will prefer human-reviewed crews over generated ones
when both match.

---

## 15. Sprint Plan

### Phase 1 — Foundation (p1-s01 through p1-s03)

**p1-s01: CrewSpec model + validation**
- `src/agent_mesh/crew_spec.py` — Pydantic models, validation function
- Validation includes concurrency checks against `max_concurrency`
- Unit tests for validation rules (cycles, missing refs, tool/model/concurrency checks)
- No LLM calls yet

**p1-s02: External config files**
- `config/model_policy.yaml` — model assignment guidelines (see §11)
- `config/effort.yaml` — effort level definitions (see §4)
- `config/crew_registry.yaml` — initial registry from existing crews
- `config/catalogs/role_archetypes.yaml`
- `config/catalogs/task_patterns.yaml`
- `config/models.yaml` — add `max_concurrency`, `has_vision` fields
- `config_loader.py` — new loaders for all above
- Unit tests

**p1-s03: Registry + crew renderer**
- `src/agent_mesh/registry.py` — load, save, find_candidates, record_usage
- `src/agent_mesh/crew_renderer.py` — render CrewSpec → YAML, save to disk
- Round-trip test: render a spec, load it with `config_loader`, build crew
- Verify generated YAML passes `crew_builder.build_crew()` without errors

### Phase 2 — Planner + Effort (p2-s01 through p2-s03)

**p2-s01: Effort system + crew_builder changes**
- Modify `crew_builder.py` — apply effort overrides (max_iter, planning, reasoning)
- Modify `agent_factory.py` — accept effort-driven parameter overrides
- Test: same crew YAML produces different behavior at quick vs exhaustive
- Verify `planning=True` + `planning_llm` work with `cloud_fast` at effort ≥ thorough

**p2-s02: Planner core**
- `config/planner_handbook.md` — distilled rules (~2K tokens)
- `src/agent_mesh/planner.py` — `plan_crew()` function
- Planner prompt includes: handbook + model_policy + catalogs + effort constraints
- Integration with LLMRegistry for the `cloud_fast` planning call
- Structured output via Pydantic (`PlannerResponse`)
- Fallback: if planner call fails, fall back to keyword routing

**p2-s03: Runner + CLI integration**
- Modify `runner.py` — add planner dispatch path + effort parameter
- Modify `start.sh` — add `--crew`, `--save`, `--input`, `--effort` flags
- Modify `config_loader.py` — search generated_crews/ as fallback
- End-to-end smoke test: free-form task → planner → crew → result

### Phase 3 — Polish (p3-s01 through p3-s02)

**p3-s01: Usage tracking + crew promotion**
- Registry records success/failure after each run
- `--promote NAME` CLI flag to copy generated crew to `crews/` and mark
  `human_reviewed: true`
- Registry `supersedes`/`superseded_by` bookkeeping

**p3-s02: Adapt path**
- Implement the `adapt` decision path: load base crew, apply spec diffs
- Test: adapt `research` crew by adding an auditor agent
- Verify adapted crew executes correctly

---

## 16. Constraints

### Hard constraints (must not violate)

1. **No source code generation by the LLM.** The planner outputs JSON structure.
   Python renders YAML. The LLM never writes Python code at runtime.

2. **Hand-authored crews are immutable.** Files in `config/crews/` are never
   modified by the planner. Only `config/generated_crews/` and the registry
   are machine-writable.

3. **All tools must be pre-registered.** The planner cannot reference tools
   that don't exist in `config/tools.yaml` and `tools.py`.

4. **All model profiles must be pre-registered.** The planner cannot reference
   models that don't exist in `config/models.yaml`.

5. **Validation before execution.** No generated crew config reaches
   `crew_builder.build_crew()` without passing `validate_crew_spec()`.

6. **Graceful degradation.** If the planner LLM call fails (timeout, bad JSON,
   validation errors), fall back to keyword-based routing via
   `task_router.route_task()`. Never crash on planner failure.

### Soft constraints (preferred)

7. Planner prompt should stay under 4K tokens total to keep latency low.
8. Generated crew names should be human-readable slugs (e.g., `event_scout_v2`).
9. The planner should prefer smaller crews (fewer agents) when the task is simple.
10. Async task patterns should only be used when the planner identifies
    genuinely independent research branches.

---

## 17. Open Questions for Owner

1. **Auto-save default**: Should dynamically generated crews be auto-saved
   to `generated_crews/` by default, or only when `--save` is explicit?
   Auto-save builds the registry faster. Explicit save keeps the filesystem
   cleaner.

2. **Crew expiry**: Should generated crews expire after N days of non-use?
   Or keep them forever and let the registry sort by recency?

3. **input.md format**: Plain text task description, or structured YAML/JSON
   with optional hints (preferred tools, output format, effort, etc.)?

4. **Execution feedback loop**: After a run, should we prompt the user for
   a quick quality rating (1–5) to feed back into registry success/failure
   tracking? Or rely on implicit signals only (completion vs. crash)?

5. **Default effort**: Is `standard` the right default, or would you prefer
   `thorough` as the baseline for your daily work?

6. **Cloud budget guard**: Should we add a flag or config to prevent
   `cloud_fast` from being used for execution agents (only for the planner
   call)? Or is it fine to let the planner assign `cloud_fast` to high-value
   synthesis tasks when effort warrants it?
