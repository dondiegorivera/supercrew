# Dynamic CrewAI Orchestration Plan

## Current Baseline

The current setup in `smoke_test.py` proves the end-to-end path works:

- one custom search tool
- three configured models:
  - `local-swarm`
  - `local-clever`
  - `cloud-fast`
- three hard-coded agents
- three hard-coded tasks
- one sequential `Crew`

That is good for smoke testing, but it couples:

- model selection
- agent definitions
- task definitions
- orchestration strategy
- experiment setup

into one file.

## Target

Build a config-driven system where:

1. agent/task/model settings live in config files
2. a wrapper inspects the incoming task
3. the wrapper selects or generates the right crew shape
4. parallelizable work is pushed into swarm-style execution
5. all three configured models can be orchestrated and compared
6. the smoke test evolves into a reusable experiment harness

## Recommended Architecture

Use two layers:

1. `CrewBase` + YAML for reusable agent/task definitions
2. `Flow` or a plain Python orchestrator for dynamic routing and parallel execution

Reason:

- CrewAI YAML is the cleanest place for stable role/task definitions
- Flow is the right place for routing, state, branching, and async fan-out
- this keeps static configuration separate from runtime decision-making

## Proposed Repository Shape

```text
.
├── smoke_test.py
├── docs/
│   └── dynamic-orchestration-plan.md
├── config/
│   ├── models.yaml
│   ├── tools.yaml
│   ├── routing.yaml
│   ├── crews/
│   │   ├── research.yaml
│   │   ├── analysis.yaml
│   │   ├── compare.yaml
│   │   └── synthesis.yaml
│   └── scenarios/
│       ├── smoke.yaml
│       ├── parallel_research.yaml
│       └── model_bakeoff.yaml
└── src/
    └── agent_mesh/
        ├── __init__.py
        ├── tools.py
        ├── llm_registry.py
        ├── config_loader.py
        ├── agent_factory.py
        ├── task_router.py
        ├── crew_builder.py
        ├── flow_runner.py
        └── experiment_runner.py
```

## Config Design

### `config/models.yaml`

Define model capabilities and intended usage, not just names.

Suggested fields:

```yaml
models:
  swarm:
    provider_model: openai/local-swarm
    temperature: 0.2
    strengths: [parallel_research, brainstorming, fanout]
    max_concurrency: 4
    default_role: worker

  clever:
    provider_model: openai/local-clever
    temperature: 0.2
    strengths: [reasoning, synthesis, critique]
    default_role: synthesizer

  cloud_fast:
    provider_model: openai/cloud-fast
    temperature: 0.2
    strengths: [fast_routing, formatting, fallback]
    default_role: router
```

### `config/tools.yaml`

Map logical tool names to Python implementations.

```yaml
tools:
  searxng_search:
    class_name: SearxngSearchTool
    enabled: true
```

### `config/routing.yaml`

Keep routing policy editable without code changes.

Suggested fields:

```yaml
task_types:
  research:
    keywords: [find, research, list, compare, latest]
    crew_template: research
  analysis:
    keywords: [analyze, evaluate, tradeoff, decide]
    crew_template: analysis
  synthesis:
    keywords: [summarize, rewrite, present]
    crew_template: synthesis

defaults:
  router_model: cloud_fast
  planner_model: clever
  worker_model: swarm
  final_model: clever
```

### `config/crews/*.yaml`

Each crew template describes:

- which agents exist
- which model profile each agent should use
- which tools each agent may access
- which tasks are required
- whether tasks can execute asynchronously

Example sketch:

```yaml
name: research
process: sequential
agents:
  researcher:
    role: Researcher
    goal: Find reliable information and extract concrete facts.
    model_profile: swarm
    tools: [searxng_search]

  synthesizer:
    role: Synthesizer
    goal: Merge findings into a clean recommendation.
    model_profile: clever
    tools: []

tasks:
  gather_sources:
    description: Search the web for {topic} and extract facts, dates, caveats.
    agent: researcher
    expected_output: Concise research notes.
    async_execution: true

  synthesize:
    description: Turn the collected notes into a recommendation.
    agent: synthesizer
    expected_output: Structured recommendation.
```

## Runtime Components

### `llm_registry.py`

Responsibilities:

- read `models.yaml`
- construct `LLM(...)` instances
- expose profiles like `get_model("swarm")`

This replaces the hard-coded `make_llm(...)` block in `smoke_test.py`.

### `agent_factory.py`

Responsibilities:

- load agent spec from crew template
- attach the configured LLM
- attach tools by logical name
- optionally override fields at runtime

Runtime overrides are important for:

- task-specific system prompts
- switching the synthesizer model
- adding a reviewer only for high-risk tasks

### `task_router.py`

Start simple and deterministic first.

Routing order:

1. explicit scenario override
2. keyword/rule-based classification from `routing.yaml`
3. planner-model classification if rules are ambiguous

Do not start with fully generative routing. Deterministic routing is easier to debug and benchmark.

### `crew_builder.py`

Responsibilities:

- load one crew template
- instantiate agents
- instantiate tasks
- build a `Crew`

This should support:

- standard sequential crews
- optional hierarchical crews later
- conditional insertion of reviewer/fallback agents

### `flow_runner.py`

Use this when the orchestration itself becomes dynamic.

The flow should own:

- task intake
- routing decision
- branch selection
- parallel kickoff of independent crews
- result aggregation
- final synthesis

This is the best place to test swarm-like fan-out patterns.

## Parallel / Swarm Strategy

There are two useful kinds of parallelism to test.

### 1. Parallel tasks inside one crew

Use `async_execution=True` on independent tasks when one crew contains multiple workers that can run without waiting on each other.

Good for:

- collecting sources from multiple angles
- researching several entities at once
- drafting alternative outputs

### 2. Parallel crews at the wrapper level

Use a Flow or async orchestrator with `akickoff()` or `kickoff_async()` plus `asyncio.gather(...)`.

Good for:

- one crew for web research
- one crew for structured analysis
- one crew for counterargument/risk review

This is the stronger fit for your "agentic mesh" idea because it lets you compare specialized sub-crews and then merge outputs.

## Recommended Model Roles

Treat the three models as a coordinated system instead of giving each a random agent.

### `local-swarm`

Best candidate for:

- worker agents
- parallel research branches
- idea generation
- first-pass extraction

### `local-clever`

Best candidate for:

- planner
- analyst
- synthesis
- critique / adjudication

### `cloud-fast`

Best candidate for:

- lightweight router
- fast formatter
- fallback writer
- cheap tie-breaker or sanity check

## Concrete Orchestration Patterns To Test

### Pattern A: Research -> Synthesis

- `swarm` gathers parallel evidence
- `clever` synthesizes
- `cloud-fast` rewrites for concise output

This is the direct evolution of your current smoke test.

### Pattern B: Multi-branch debate

- branch 1: `swarm` researches supporting evidence
- branch 2: `swarm` researches counterpoints and risks
- branch 3: `cloud-fast` extracts structured facts quickly
- aggregator: `clever` resolves conflicts and writes the final answer

This is a strong orchestration test because it exercises disagreement and merge quality.

### Pattern C: Model bake-off

Run the same task through three single-agent or small-crew pipelines:

- swarm-first pipeline
- clever-first pipeline
- cloud-fast-first pipeline

Then use a judge step to compare:

- latency
- completeness
- factual grounding
- structure quality

This gives you measurable results for model assignment policy.

## Suggested First Implementation Phases

### Phase 1: Externalize config

Keep behavior almost identical to `smoke_test.py`, but move:

- models
- agent prompts
- task prompts
- tool selection

into config files.

Deliverable:

- current smoke test rebuilt from config with no major orchestration changes

### Phase 2: Add dynamic wrapper

Add a wrapper entrypoint like:

```python
run_task(task_text: str, scenario: str | None = None)
```

The wrapper should:

- classify the task
- select a crew template
- instantiate the crew
- run it

Deliverable:

- one input task can choose between at least `research`, `analysis`, and `synthesis`

### Phase 3: Add parallel fan-out

Introduce a Flow or async orchestrator that launches multiple crews in parallel.

Deliverable:

- one task can spawn multiple research branches and one synthesis branch

### Phase 4: Add experiment harness

Add a repeatable runner for comparing model orchestration strategies.

Suggested outputs:

- console summary
- JSON result file with latency and outputs

## Minimal Test Matrix

Use a small but useful matrix first.

### Task classes

- factual research
- compare-and-recommend
- rewrite/summarization

### Orchestration modes

- sequential baseline
- parallel research branches
- full three-model orchestration

### Metrics

- total runtime
- branch runtime
- final output length
- citation density or source count
- judge score from a fixed evaluation prompt

## Important Design Choices

### Prefer generated crews over generated agent prompts at first

Use a fixed set of agent templates and let the wrapper choose among them.

Why:

- easier debugging
- more stable experiments
- simpler regression testing

Only later add prompt generation or agent generation for edge cases.

### Keep tools centrally registered

Do not let YAML contain arbitrary Python import paths at first.

Use a controlled mapping from config key to tool class in code.

Why:

- safer
- easier to test
- less fragile

### Start with deterministic routing

If every routing decision is LLM-made, it will be hard to explain failures.

Use rules first, then an LLM planner only when confidence is low.

## Recommended Next Build Order

1. create `config/models.yaml`
2. create `config/tools.yaml`
3. create one `config/crews/research.yaml`
4. implement `llm_registry.py`
5. implement `agent_factory.py`
6. implement `crew_builder.py`
7. rebuild the existing smoke test through the builder
8. add `task_router.py`
9. add async multi-crew orchestration
10. add experiment runner

## What Not To Do Yet

- do not start with fully autonomous agent generation
- do not mix config parsing, tool creation, routing, and execution in one file again
- do not benchmark many scenarios before the baseline config-driven path is stable

## Practical Recommendation

For this repo, the best first concrete milestone is:

> Refactor the current smoke test into a config-driven single wrapper that supports three named crew templates and one parallel research mode.

That gives you:

- cleaner config separation
- a stable baseline
- a direct path to testing swarm-style parallelism
- a place to compare all three models under controlled orchestration
