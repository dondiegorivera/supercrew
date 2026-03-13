# Feature Sprints — Dynamic Orchestration

Reference: `docs/specs/architecture.md` v1.1

---

## Phase 1 — Foundation

### p1-s01 — CrewSpec Model + Validation

**Branch:** `sprint/p1-s01-crew-spec-model`
**Depends on:** nothing (first sprint)

#### Goal

Create the Pydantic data model that represents a planner-generated crew
specification, and a validation function that catches invalid specs before
they reach `crew_builder.py`.

#### Files to Create

**`src/agent_mesh/crew_spec.py`**

```python
"""Pydantic models for planner-generated crew specifications."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentSpec(BaseModel):
    name: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,39}$")
    role_archetype: str
    role: str
    goal: str
    backstory: str
    model_profile: str
    tools: list[str] = Field(default_factory=list)
    allow_delegation: bool = False


class TaskSpec(BaseModel):
    name: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,39}$")
    description: str
    expected_output: str
    agent: str
    context: list[str] = Field(default_factory=list)
    async_execution: bool = False


class CrewSpecPayload(BaseModel):
    name: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,59}$")
    description: str
    process: Literal["sequential", "hierarchical"] = "sequential"
    tags: list[str] = Field(default_factory=list)
    query_archetypes: list[str] = Field(default_factory=list)
    agents: list[AgentSpec]
    tasks: list[TaskSpec]


class PlannerResponse(BaseModel):
    decision: Literal["reuse", "adapt", "generate"]
    reuse_crew: str | None = None
    base_crew: str | None = None
    crew_spec: CrewSpecPayload | None = None


def validate_crew_spec(
    spec: CrewSpecPayload,
    available_tools: set[str],
    available_models: set[str],
    model_concurrency: dict[str, int] | None = None,
) -> list[str]:
    """Validate a CrewSpecPayload against project constraints.

    Returns a list of error strings. Empty list means valid.
    """
    errors: list[str] = []

    # --- Agent count ---
    if len(spec.agents) < 2:
        errors.append(f"Too few agents: {len(spec.agents)} (min 2)")
    if len(spec.agents) > 8:
        errors.append(f"Too many agents: {len(spec.agents)} (max 8)")

    # --- Task count ---
    if len(spec.tasks) < 1:
        errors.append("No tasks defined (min 1)")
    if len(spec.tasks) > 12:
        errors.append(f"Too many tasks: {len(spec.tasks)} (max 12)")

    # --- Unique agent names ---
    agent_names: set[str] = set()
    for agent in spec.agents:
        if agent.name in agent_names:
            errors.append(f"Duplicate agent name: {agent.name}")
        agent_names.add(agent.name)

    # --- Unique task names ---
    task_names: set[str] = set()
    for task in spec.tasks:
        if task.name in task_names:
            errors.append(f"Duplicate task name: {task.name}")
        task_names.add(task.name)

    # --- Task.agent references valid agent ---
    for task in spec.tasks:
        if task.agent not in agent_names:
            errors.append(
                f"Task '{task.name}' references unknown agent '{task.agent}'"
            )

    # --- Task.context references valid tasks, no self-ref ---
    for task in spec.tasks:
        for ctx in task.context:
            if ctx not in task_names:
                errors.append(
                    f"Task '{task.name}' context references unknown task '{ctx}'"
                )
            if ctx == task.name:
                errors.append(
                    f"Task '{task.name}' references itself in context"
                )

    # --- Cycle detection in task context graph ---
    task_deps: dict[str, list[str]] = {
        t.name: list(t.context) for t in spec.tasks
    }
    visited: set[str] = set()
    in_stack: set[str] = set()

    def _has_cycle(node: str) -> bool:
        if node in in_stack:
            return True
        if node in visited:
            return False
        visited.add(node)
        in_stack.add(node)
        for dep in task_deps.get(node, []):
            if _has_cycle(dep):
                return True
        in_stack.discard(node)
        return False

    for t_name in task_deps:
        if _has_cycle(t_name):
            errors.append(f"Cycle detected in task context graph involving '{t_name}'")
            break

    # --- Tools must be registered ---
    for agent in spec.agents:
        for tool in agent.tools:
            if tool not in available_tools:
                errors.append(
                    f"Agent '{agent.name}' uses unregistered tool '{tool}'"
                )

    # --- Model profiles must be registered ---
    for agent in spec.agents:
        if agent.model_profile not in available_models:
            errors.append(
                f"Agent '{agent.name}' uses unknown model profile "
                f"'{agent.model_profile}'"
            )

    # --- Async tasks: not final, must have sync consumer ---
    if spec.tasks:
        last_task = spec.tasks[-1]
        if last_task.async_execution:
            errors.append(
                f"Last task '{last_task.name}' cannot be async"
            )

    async_task_names = {t.name for t in spec.tasks if t.async_execution}
    consumed_by_sync = set()
    for task in spec.tasks:
        if not task.async_execution:
            consumed_by_sync.update(
                ctx for ctx in task.context if ctx in async_task_names
            )
    unconsumed = async_task_names - consumed_by_sync
    for name in unconsumed:
        errors.append(
            f"Async task '{name}' has no downstream sync consumer"
        )

    # --- Concurrency limits ---
    if model_concurrency:
        # Count async agents per model
        async_agents_per_model: dict[str, int] = {}
        for task in spec.tasks:
            if task.async_execution:
                agent_spec = next(
                    (a for a in spec.agents if a.name == task.agent), None
                )
                if agent_spec:
                    model = agent_spec.model_profile
                    async_agents_per_model[model] = (
                        async_agents_per_model.get(model, 0) + 1
                    )
        for model, count in async_agents_per_model.items():
            limit = model_concurrency.get(model)
            if limit is not None and count > limit:
                errors.append(
                    f"Model '{model}' has {count} async agents but "
                    f"max_concurrency is {limit}"
                )

    # --- At least one task must contain {topic} ---
    has_topic = any("{topic}" in t.description for t in spec.tasks)
    if not has_topic:
        errors.append(
            "No task description contains the '{topic}' placeholder"
        )

    return errors
```

**`tests/__init__.py`** — empty file

**`tests/test_crew_spec.py`**

```python
"""Unit tests for crew_spec validation."""
from __future__ import annotations

import sys
from pathlib import Path

# Allow imports from src/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_mesh.crew_spec import (
    AgentSpec,
    CrewSpecPayload,
    PlannerResponse,
    TaskSpec,
    validate_crew_spec,
)

TOOLS = {"searxng_search", "webpage_fetch", "pdf_fetch", "pdf_extract"}
MODELS = {"swarm", "clever", "cloud_fast"}
CONCURRENCY = {"swarm": 16, "clever": 2, "cloud_fast": 4}


def _minimal_spec(**overrides) -> CrewSpecPayload:
    defaults = dict(
        name="test_crew",
        description="A test crew",
        process="sequential",
        tags=["test"],
        query_archetypes=["test {topic}"],
        agents=[
            AgentSpec(
                name="researcher",
                role_archetype="researcher",
                role="Researcher",
                goal="Find info",
                backstory="Good at research",
                model_profile="swarm",
                tools=["searxng_search"],
            ),
            AgentSpec(
                name="analyst",
                role_archetype="analyst",
                role="Analyst",
                goal="Analyze",
                backstory="Good at analysis",
                model_profile="clever",
            ),
        ],
        tasks=[
            TaskSpec(
                name="search",
                description="Search for {topic}",
                expected_output="Results",
                agent="researcher",
            ),
            TaskSpec(
                name="analyze",
                description="Analyze the results",
                expected_output="Analysis",
                agent="analyst",
                context=["search"],
            ),
        ],
    )
    defaults.update(overrides)
    return CrewSpecPayload(**defaults)


def test_valid_spec_passes():
    spec = _minimal_spec()
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert errors == [], f"Unexpected errors: {errors}"


def test_too_few_agents():
    spec = _minimal_spec(
        agents=[
            AgentSpec(
                name="solo",
                role_archetype="researcher",
                role="Solo",
                goal="Do it all",
                backstory="Alone",
                model_profile="swarm",
            ),
        ],
        tasks=[
            TaskSpec(
                name="work",
                description="Do {topic}",
                expected_output="Done",
                agent="solo",
            ),
        ],
    )
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("Too few agents" in e for e in errors)


def test_unknown_tool():
    spec = _minimal_spec()
    spec.agents[0].tools = ["nonexistent_tool"]
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("unregistered tool" in e for e in errors)


def test_unknown_model():
    spec = _minimal_spec()
    spec.agents[0].model_profile = "nonexistent_model"
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("unknown model profile" in e for e in errors)


def test_task_references_unknown_agent():
    spec = _minimal_spec()
    spec.tasks[0].agent = "ghost"
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("unknown agent" in e for e in errors)


def test_context_cycle_detected():
    spec = _minimal_spec(
        tasks=[
            TaskSpec(
                name="task_a",
                description="Do {topic}",
                expected_output="A",
                agent="researcher",
                context=["task_b"],
            ),
            TaskSpec(
                name="task_b",
                description="Do more",
                expected_output="B",
                agent="analyst",
                context=["task_a"],
            ),
        ],
    )
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("Cycle" in e for e in errors)


def test_async_last_task_rejected():
    spec = _minimal_spec(
        tasks=[
            TaskSpec(
                name="search",
                description="Search {topic}",
                expected_output="Results",
                agent="researcher",
            ),
            TaskSpec(
                name="final",
                description="Finalize",
                expected_output="Done",
                agent="analyst",
                async_execution=True,
            ),
        ],
    )
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("cannot be async" in e for e in errors)


def test_async_without_sync_consumer():
    spec = _minimal_spec(
        tasks=[
            TaskSpec(
                name="async_search",
                description="Search {topic}",
                expected_output="Results",
                agent="researcher",
                async_execution=True,
            ),
            TaskSpec(
                name="other",
                description="Something else",
                expected_output="Done",
                agent="analyst",
                # context does NOT include async_search
            ),
        ],
    )
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("no downstream sync consumer" in e for e in errors)


def test_concurrency_exceeded():
    agents = [
        AgentSpec(
            name=f"worker_{i}",
            role_archetype="researcher",
            role=f"Worker {i}",
            goal="Search",
            backstory="Fast",
            model_profile="clever",  # max_concurrency=2
        )
        for i in range(4)
    ] + [
        AgentSpec(
            name="analyst",
            role_archetype="analyst",
            role="Analyst",
            goal="Merge",
            backstory="Smart",
            model_profile="clever",
        ),
    ]
    tasks = [
        TaskSpec(
            name=f"search_{i}",
            description="Search {topic}" if i == 0 else "Search more",
            expected_output="Results",
            agent=f"worker_{i}",
            async_execution=True,
        )
        for i in range(4)
    ] + [
        TaskSpec(
            name="merge",
            description="Merge results",
            expected_output="Merged",
            agent="analyst",
            context=[f"search_{i}" for i in range(4)],
        ),
    ]
    spec = _minimal_spec(agents=agents, tasks=tasks)
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("max_concurrency" in e for e in errors)


def test_no_topic_placeholder():
    spec = _minimal_spec(
        tasks=[
            TaskSpec(
                name="search",
                description="Search for stuff",  # no {topic}
                expected_output="Results",
                agent="researcher",
            ),
            TaskSpec(
                name="analyze",
                description="Analyze the results",
                expected_output="Analysis",
                agent="analyst",
                context=["search"],
            ),
        ],
    )
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("{topic}" in e for e in errors)


def test_planner_response_reuse():
    resp = PlannerResponse(decision="reuse", reuse_crew="deep_research")
    assert resp.decision == "reuse"
    assert resp.crew_spec is None


def test_planner_response_generate():
    spec = _minimal_spec()
    resp = PlannerResponse(decision="generate", crew_spec=spec)
    assert resp.decision == "generate"
    assert resp.crew_spec is not None


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
```

#### Verification

```bash
# From the repo root — install pytest if not present, then run
pip install pytest pydantic 2>/dev/null
python -m pytest tests/test_crew_spec.py -v
```

All tests must pass. Zero failures.

#### Acceptance Criteria

- [ ] `crew_spec.py` exists at `src/agent_mesh/crew_spec.py`
- [ ] All Pydantic models parse valid JSON without error
- [ ] `validate_crew_spec()` returns empty list for a valid spec
- [ ] `validate_crew_spec()` catches: too few/many agents, unknown tools,
      unknown models, unknown agent refs, context cycles, async-last-task,
      async-without-consumer, concurrency exceeded, missing `{topic}`
- [ ] All tests in `tests/test_crew_spec.py` pass
- [ ] No changes to any existing file

---

### p1-s02 — External Config Files

**Branch:** `sprint/p1-s02-external-configs`
**Depends on:** p1-s01 (uses model names and tool names for consistency)

#### Goal

Create the new config files the planner and effort system need, update
`models.yaml` with new fields, and add loaders to `config_loader.py`.

#### Files to Create

**`config/effort.yaml`**

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

**`config/model_policy.yaml`**

Copy the full contents from architecture spec §11.1 verbatim.

**`config/catalogs/role_archetypes.yaml`**

Copy the full contents from architecture spec §7.3 (`archetypes:` block).

**`config/catalogs/task_patterns.yaml`**

Copy the full contents from architecture spec §7.3 (`patterns:` block).

**`config/crew_registry.yaml`**

Build the initial registry by reading the existing crew YAML files in
`config/crews/` and extracting metadata. One entry per crew:

```yaml
crews:
  research:
    source: manual
    description: "Web research with analyst synthesis and final writing"
    tags: [research, web, synthesis]
    query_archetypes:
      - "find information about {topic}"
      - "research {topic}"
    required_tools: [searxng_search]
    required_capabilities: [web]
    agent_count: 3
    process: sequential
    created_at: "2026-03-13"
    last_used_at: null
    use_count: 0
    success_count: 0
    failure_count: 0
    human_reviewed: true
    supersedes: null
    superseded_by: null

  analysis:
    source: manual
    description: "Analysis and reasoning over provided material"
    tags: [analysis, reasoning]
    query_archetypes:
      - "analyze {topic}"
      - "evaluate {topic}"
    required_tools: []
    required_capabilities: []
    agent_count: 2
    process: sequential
    created_at: "2026-03-13"
    last_used_at: null
    use_count: 0
    success_count: 0
    failure_count: 0
    human_reviewed: true
    supersedes: null
    superseded_by: null

  synthesis:
    source: manual
    description: "Merge and polish scattered input into concise output"
    tags: [synthesis, writing]
    query_archetypes:
      - "summarize {topic}"
      - "rewrite {topic}"
    required_tools: []
    required_capabilities: []
    agent_count: 2
    process: sequential
    created_at: "2026-03-13"
    last_used_at: null
    use_count: 0
    success_count: 0
    failure_count: 0
    human_reviewed: true
    supersedes: null
    superseded_by: null

  parallel_research:
    source: manual
    description: "Parallel fact/pricing/risk branches merged by analyst"
    tags: [research, parallel, pricing, risk]
    query_archetypes:
      - "compare {topic}"
      - "find prices for {topic}"
    required_tools: [searxng_search]
    required_capabilities: [web, parallel]
    agent_count: 5
    process: sequential
    created_at: "2026-03-13"
    last_used_at: null
    use_count: 0
    success_count: 0
    failure_count: 0
    human_reviewed: true
    supersedes: null
    superseded_by: null

  deep_research:
    source: manual
    description: "Multi-agent deep research with coverage audit and evidence normalization"
    tags: [research, deep, events, pricing, verification, pdf]
    query_archetypes:
      - "list all {category} in {location}"
      - "find {category} with dates and prices"
      - "deep research {topic}"
    required_tools: [searxng_search, webpage_fetch, pdf_fetch, pdf_extract]
    required_capabilities: [web, pdf, parallel]
    agent_count: 7
    process: sequential
    created_at: "2026-03-13"
    last_used_at: null
    use_count: 0
    success_count: 0
    failure_count: 0
    human_reviewed: true
    supersedes: null
    superseded_by: null

  deep_research_cloud_review:
    source: manual
    description: "Deep research with cloud-powered final review"
    tags: [research, deep, verification, cloud]
    query_archetypes:
      - "thoroughly research {topic}"
    required_tools: [searxng_search, webpage_fetch, pdf_fetch, pdf_extract]
    required_capabilities: [web, pdf, parallel, cloud_review]
    agent_count: 7
    process: sequential
    created_at: "2026-03-13"
    last_used_at: null
    use_count: 0
    success_count: 0
    failure_count: 0
    human_reviewed: true
    supersedes: null
    superseded_by: null
```

#### Files to Modify

**`config/models.yaml`** — Add `max_concurrency` and `has_vision` to each model:

```yaml
# Add these fields to each model entry (do not change existing fields):

models:
  swarm:
    # ... existing fields stay ...
    max_concurrency: 16
    has_vision: true

  clever:
    # ... existing fields stay ...
    max_concurrency: 2
    has_vision: false

  cloud_fast:
    # ... existing fields stay ...
    max_concurrency: 4
    has_vision: false
```

**`src/agent_mesh/config_loader.py`** — Add these new functions (do not
modify existing functions):

```python
def load_effort_config() -> dict[str, Any]:
    return load_yaml(config_path("effort.yaml"))


def load_model_policy() -> str:
    path = config_path("model_policy.yaml")
    return path.read_text(encoding="utf-8")


def load_registry_config() -> dict[str, Any]:
    path = config_path("crew_registry.yaml")
    if not path.exists():
        return {"crews": {}}
    return load_yaml(path)


def save_registry_config(data: dict[str, Any]) -> None:
    import yaml as _yaml

    path = config_path("crew_registry.yaml")
    with path.open("w", encoding="utf-8") as handle:
        _yaml.dump(data, handle, default_flow_style=False, sort_keys=False)


def load_catalogs() -> dict[str, Any]:
    catalogs_dir = CONFIG_DIR / "catalogs"
    return {
        "role_archetypes": load_yaml(catalogs_dir / "role_archetypes.yaml"),
        "task_patterns": load_yaml(catalogs_dir / "task_patterns.yaml"),
    }


def load_planner_handbook() -> str:
    path = config_path("planner_handbook.md")
    return path.read_text(encoding="utf-8")


def load_crew_config(template_name: str) -> dict[str, Any]:
    """Try config/crews/ first, then config/generated_crews/."""
    primary = config_path("crews", f"{template_name}.yaml")
    if primary.exists():
        return load_yaml(primary)
    generated = config_path("generated_crews", f"{template_name}.yaml")
    if generated.exists():
        return load_yaml(generated)
    raise FileNotFoundError(
        f"No crew config found for '{template_name}' in crews/ or generated_crews/"
    )
```

**Important:** The existing `load_crew_config` function must be **replaced**
by the new version above (which adds the generated_crews fallback). The
existing version is:

```python
def load_crew_config(template_name: str) -> dict[str, Any]:
    return load_yaml(config_path("crews", f"{template_name}.yaml"))
```

Also create the empty directory: `config/generated_crews/` (add a `.gitkeep`
file so git tracks the empty dir).

#### Files to Create (additional)

**`config/generated_crews/.gitkeep`** — empty file

**`tests/test_config_loader.py`**

```python
"""Tests for config_loader new functions."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_mesh.config_loader import (
    load_catalogs,
    load_effort_config,
    load_model_policy,
    load_models_config,
    load_registry_config,
)


def test_effort_config_loads():
    config = load_effort_config()
    assert "levels" in config
    assert "standard" in config["levels"]
    assert "max_iter" in config["levels"]["standard"]


def test_effort_levels_complete():
    config = load_effort_config()
    for level in ("quick", "standard", "thorough", "exhaustive"):
        assert level in config["levels"], f"Missing effort level: {level}"
        entry = config["levels"][level]
        assert "max_iter" in entry
        assert "max_execution_time" in entry
        assert "max_swarm_agents" in entry


def test_model_policy_loads_as_string():
    policy = load_model_policy()
    assert isinstance(policy, str)
    assert "cloud_fast" in policy
    assert "swarm" in policy


def test_models_have_concurrency():
    config = load_models_config()
    for name, model in config["models"].items():
        assert "max_concurrency" in model, (
            f"Model '{name}' missing max_concurrency"
        )
        assert "has_vision" in model, f"Model '{name}' missing has_vision"


def test_registry_loads():
    config = load_registry_config()
    assert "crews" in config
    assert "deep_research" in config["crews"]


def test_catalogs_load():
    catalogs = load_catalogs()
    assert "role_archetypes" in catalogs
    assert "task_patterns" in catalogs
    assert "archetypes" in catalogs["role_archetypes"]
    assert "patterns" in catalogs["task_patterns"]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
```

#### Verification

```bash
python -m pytest tests/test_config_loader.py -v
```

All tests must pass.

#### Acceptance Criteria

- [ ] `config/effort.yaml` exists with all 4 levels
- [ ] `config/model_policy.yaml` exists with all 3 models
- [ ] `config/catalogs/role_archetypes.yaml` exists with archetypes
- [ ] `config/catalogs/task_patterns.yaml` exists with patterns
- [ ] `config/crew_registry.yaml` exists with entries for all existing crews
- [ ] `config/generated_crews/.gitkeep` exists
- [ ] `config/models.yaml` has `max_concurrency` and `has_vision` on all models
- [ ] `config_loader.py` has new loaders, `load_crew_config` searches generated_crews/
- [ ] All tests pass
- [ ] Existing functionality unchanged (existing `runner.py` path still works)

---

### p1-s03 — Registry + Crew Renderer

**Branch:** `sprint/p1-s03-registry-renderer`
**Depends on:** p1-s01 (crew_spec.py), p1-s02 (config files + loaders)

#### Goal

Build the crew registry module (load/save/match/record) and the renderer
that converts a `CrewSpecPayload` into a YAML file that `crew_builder.py`
can load.

#### Files to Create

**`src/agent_mesh/registry.py`**

```python
"""Crew registry — tracks all crews (manual and generated) with metadata."""
from __future__ import annotations

from datetime import date
from typing import Any

from .config_loader import load_registry_config, save_registry_config


class CrewEntry:
    """In-memory representation of one registry entry."""

    def __init__(self, name: str, data: dict[str, Any]) -> None:
        self.name = name
        self.source: str = data.get("source", "manual")
        self.description: str = data.get("description", "")
        self.tags: list[str] = data.get("tags", [])
        self.query_archetypes: list[str] = data.get("query_archetypes", [])
        self.required_tools: list[str] = data.get("required_tools", [])
        self.required_capabilities: list[str] = data.get(
            "required_capabilities", []
        )
        self.agent_count: int = data.get("agent_count", 0)
        self.process: str = data.get("process", "sequential")
        self.use_count: int = data.get("use_count", 0)
        self.success_count: int = data.get("success_count", 0)
        self.failure_count: int = data.get("failure_count", 0)
        self.human_reviewed: bool = data.get("human_reviewed", False)
        self.created_at: str = data.get("created_at", "")
        self.last_used_at: str | None = data.get("last_used_at")
        self.supersedes: str | None = data.get("supersedes")
        self.superseded_by: str | None = data.get("superseded_by")
        self.base_crew: str | None = data.get("base_crew")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "description": self.description,
            "tags": self.tags,
            "query_archetypes": self.query_archetypes,
            "required_tools": self.required_tools,
            "required_capabilities": self.required_capabilities,
            "agent_count": self.agent_count,
            "process": self.process,
            "use_count": self.use_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "human_reviewed": self.human_reviewed,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
            "base_crew": self.base_crew,
        }

    def summary_for_planner(self) -> str:
        """Short text summary suitable for inclusion in a planner prompt."""
        return (
            f"- {self.name}: {self.description} "
            f"[tags: {', '.join(self.tags)}] "
            f"[agents: {self.agent_count}, process: {self.process}] "
            f"[tools: {', '.join(self.required_tools) or 'none'}] "
            f"[uses: {self.use_count}, success_rate: "
            f"{self.success_count}/{self.use_count if self.use_count else '?'}] "
            f"[reviewed: {self.human_reviewed}]"
        )


class CrewRegistry:
    """Load, query, and persist the crew registry."""

    def __init__(self) -> None:
        self._crews: dict[str, CrewEntry] = {}

    def load(self) -> None:
        raw = load_registry_config()
        self._crews = {
            name: CrewEntry(name, data)
            for name, data in raw.get("crews", {}).items()
        }

    def save(self) -> None:
        data = {"crews": {n: e.to_dict() for n, e in self._crews.items()}}
        save_registry_config(data)

    def list_crews(self) -> list[CrewEntry]:
        return list(self._crews.values())

    def get(self, name: str) -> CrewEntry | None:
        return self._crews.get(name)

    def register(self, entry: CrewEntry) -> None:
        self._crews[entry.name] = entry

    def record_usage(self, name: str, success: bool) -> None:
        entry = self._crews.get(name)
        if not entry:
            return
        entry.use_count += 1
        if success:
            entry.success_count += 1
        else:
            entry.failure_count += 1
        entry.last_used_at = date.today().isoformat()

    def find_candidates(
        self,
        task_text: str,
        limit: int = 5,
    ) -> list[CrewEntry]:
        """Score and rank crews by simple tag/keyword overlap with task text.

        Returns the top `limit` matches sorted by score descending.
        Prefers human_reviewed crews over generated ones.
        """
        lowered = task_text.lower()
        scored: list[tuple[float, CrewEntry]] = []

        for entry in self._crews.values():
            # Skip superseded crews
            if entry.superseded_by:
                continue

            score = 0.0
            # Tag overlap
            for tag in entry.tags:
                if tag.lower() in lowered:
                    score += 1.0

            # Archetype token overlap
            for archetype in entry.query_archetypes:
                tokens = archetype.lower().replace("{", "").replace("}", "").split()
                matches = sum(1 for t in tokens if t in lowered)
                score += matches * 0.5

            # Human-reviewed bonus
            if entry.human_reviewed:
                score += 0.5

            # Success rate bonus
            if entry.use_count > 0:
                score += (entry.success_count / entry.use_count) * 0.5

            scored.append((score, entry))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for _, entry in scored[:limit]]
```

**`src/agent_mesh/crew_renderer.py`**

```python
"""Render a CrewSpecPayload into a crew YAML file for crew_builder."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .config_loader import CONFIG_DIR
from .crew_spec import CrewSpecPayload


def render_crew_dict(spec: CrewSpecPayload) -> dict[str, Any]:
    """Convert a CrewSpecPayload into the dict format crew_builder expects."""
    agents: dict[str, Any] = {}
    for agent in spec.agents:
        agents[agent.name] = {
            "role": agent.role,
            "goal": agent.goal,
            "backstory": agent.backstory,
            "model_profile": agent.model_profile,
            "tools": agent.tools,
            "allow_delegation": agent.allow_delegation,
            "verbose": True,
        }

    tasks: dict[str, Any] = {}
    for task in spec.tasks:
        task_dict: dict[str, Any] = {
            "description": task.description,
            "expected_output": task.expected_output,
            "agent": task.agent,
        }
        if task.context:
            task_dict["context"] = task.context
        if task.async_execution:
            task_dict["async_execution"] = True
        tasks[task.name] = task_dict

    return {
        "name": spec.name,
        "process": spec.process,
        "verbose": True,
        "agents": agents,
        "tasks": tasks,
    }


def render_crew_yaml(spec: CrewSpecPayload) -> str:
    """Convert a CrewSpecPayload into a YAML string."""
    data = render_crew_dict(spec)
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


def save_generated_crew(spec: CrewSpecPayload, name: str | None = None) -> Path:
    """Save a rendered crew YAML to config/generated_crews/.

    Returns the path to the written file.
    """
    crew_name = name or spec.name
    generated_dir = CONFIG_DIR / "generated_crews"
    generated_dir.mkdir(parents=True, exist_ok=True)
    path = generated_dir / f"{crew_name}.yaml"
    path.write_text(render_crew_yaml(spec), encoding="utf-8")
    return path
```

**`tests/test_registry.py`**

```python
"""Tests for registry and crew_renderer."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_mesh.crew_spec import AgentSpec, CrewSpecPayload, TaskSpec
from agent_mesh.crew_renderer import render_crew_dict, render_crew_yaml
from agent_mesh.registry import CrewRegistry


def _sample_spec() -> CrewSpecPayload:
    return CrewSpecPayload(
        name="test_crew",
        description="A test crew",
        process="sequential",
        tags=["test"],
        query_archetypes=["test {topic}"],
        agents=[
            AgentSpec(
                name="researcher",
                role_archetype="researcher",
                role="Researcher",
                goal="Find info",
                backstory="Good at research",
                model_profile="swarm",
                tools=["searxng_search"],
            ),
            AgentSpec(
                name="analyst",
                role_archetype="analyst",
                role="Analyst",
                goal="Analyze",
                backstory="Good at analysis",
                model_profile="clever",
            ),
        ],
        tasks=[
            TaskSpec(
                name="search",
                description="Search for {topic}",
                expected_output="Results",
                agent="researcher",
            ),
            TaskSpec(
                name="analyze",
                description="Analyze the results",
                expected_output="Analysis",
                agent="analyst",
                context=["search"],
            ),
        ],
    )


def test_render_crew_dict_structure():
    spec = _sample_spec()
    result = render_crew_dict(spec)
    assert result["name"] == "test_crew"
    assert result["process"] == "sequential"
    assert "researcher" in result["agents"]
    assert "search" in result["tasks"]
    assert result["tasks"]["analyze"]["context"] == ["search"]


def test_render_crew_yaml_is_valid():
    import yaml

    spec = _sample_spec()
    yaml_str = render_crew_yaml(spec)
    parsed = yaml.safe_load(yaml_str)
    assert parsed["name"] == "test_crew"
    assert "agents" in parsed
    assert "tasks" in parsed


def test_registry_load_and_find():
    registry = CrewRegistry()
    registry.load()
    crews = registry.list_crews()
    assert len(crews) > 0, "Registry should have existing crews"

    # Find candidates for a research task
    candidates = registry.find_candidates("research about jazz festivals")
    assert len(candidates) > 0


def test_registry_record_usage():
    registry = CrewRegistry()
    registry.load()
    name = registry.list_crews()[0].name
    entry = registry.get(name)
    old_count = entry.use_count
    registry.record_usage(name, success=True)
    assert entry.use_count == old_count + 1
    assert entry.success_count > 0


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
```

#### Verification

```bash
python -m pytest tests/test_registry.py -v
```

Also verify the **round-trip**: render a spec to YAML, load it back through
`config_loader.load_crew_config()`, and confirm it has the expected structure:

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from agent_mesh.crew_spec import AgentSpec, CrewSpecPayload, TaskSpec
from agent_mesh.crew_renderer import save_generated_crew, render_crew_dict
from agent_mesh.config_loader import load_crew_config

spec = CrewSpecPayload(
    name='roundtrip_test',
    description='test',
    process='sequential',
    tags=[],
    query_archetypes=[],
    agents=[
        AgentSpec(name='a1', role_archetype='researcher', role='R', goal='G',
                  backstory='B', model_profile='swarm', tools=['searxng_search']),
        AgentSpec(name='a2', role_archetype='analyst', role='A', goal='G',
                  backstory='B', model_profile='clever'),
    ],
    tasks=[
        TaskSpec(name='t1', description='Do {topic}', expected_output='X', agent='a1'),
        TaskSpec(name='t2', description='Finish', expected_output='Y', agent='a2', context=['t1']),
    ],
)
path = save_generated_crew(spec)
loaded = load_crew_config('roundtrip_test')
assert loaded['name'] == 'roundtrip_test'
assert 'a1' in loaded['agents']
assert 't1' in loaded['tasks']
print('Round-trip OK:', path)

# Clean up
import os; os.remove(path)
"
```

#### Acceptance Criteria

- [ ] `src/agent_mesh/registry.py` exists with `CrewRegistry` class
- [ ] `src/agent_mesh/crew_renderer.py` exists with `render_crew_yaml` and `save_generated_crew`
- [ ] Registry loads the existing `crew_registry.yaml` and finds candidates
- [ ] Rendered YAML round-trips through `load_crew_config` successfully
- [ ] All tests pass
- [ ] No changes to `crew_builder.py`, `agent_factory.py`, or `runner.py`

---

## Phase 2 — Planner + Effort

### p2-s01 — Effort System + Crew Builder Changes

**Branch:** `sprint/p2-s01-effort-system`
**Depends on:** p1-s02 (effort.yaml, config_loader)

#### Goal

Modify `crew_builder.py` and `agent_factory.py` so that an `effort` parameter
controls agent iteration limits, planning, and reasoning. The same crew YAML
should produce different execution behavior at different effort levels.

#### Files to Modify

**`src/agent_mesh/agent_factory.py`** — Add `effort_overrides` parameter:

The `build_agents` function gains an optional `effort_overrides: dict | None`
parameter. When provided, it sets `max_iter`, `max_execution_time`,
`max_retry_limit`, `reasoning`, and `max_reasoning_attempts` on each agent.

```python
def build_agents(
    config: dict[str, Any],
    llms: LLMRegistry,
    tools: dict[str, BaseTool],
    effort_overrides: dict[str, Any] | None = None,
) -> dict[str, Agent]:
    agents: dict[str, Agent] = {}

    for name, agent_spec in config.get("agents", {}).items():
        tool_names = agent_spec.get("tools", [])
        agent_tools = [tools[tool_name] for tool_name in tool_names]

        kwargs: dict[str, Any] = {
            "role": agent_spec["role"],
            "goal": agent_spec["goal"],
            "backstory": agent_spec.get("backstory", ""),
            "llm": llms.get(agent_spec["model_profile"]),
            "tools": agent_tools,
            "verbose": agent_spec.get("verbose", True),
            "allow_delegation": agent_spec.get("allow_delegation", False),
        }

        # Apply effort overrides
        if effort_overrides:
            if "max_iter" in effort_overrides:
                kwargs["max_iter"] = effort_overrides["max_iter"]
            if "max_execution_time" in effort_overrides:
                kwargs["max_execution_time"] = effort_overrides[
                    "max_execution_time"
                ]
            if "max_retry_limit" in effort_overrides:
                kwargs["max_retry_limit"] = effort_overrides["max_retry_limit"]
            if effort_overrides.get("reasoning"):
                kwargs["reasoning"] = True
                if "max_reasoning_attempts" in effort_overrides:
                    kwargs["max_reasoning_attempts"] = effort_overrides[
                        "max_reasoning_attempts"
                    ]

        agents[name] = Agent(**kwargs)

    return agents
```

**`src/agent_mesh/crew_builder.py`** — Add `effort` + `effort_config` params:

```python
from .config_loader import load_effort_config

def _resolve_effort_overrides(
    effort: str,
    effort_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if effort_config is None:
        effort_config = load_effort_config()
    levels = effort_config.get("levels", {})
    return levels.get(effort)


def build_crew(
    config: dict[str, Any],
    llms: LLMRegistry,
    tools: dict[str, Any],
    effort: str = "standard",
    effort_config: dict[str, Any] | None = None,
) -> Crew:
    effort_overrides = _resolve_effort_overrides(effort, effort_config)
    agents = build_agents(
        config=config, llms=llms, tools=tools,
        effort_overrides=effort_overrides,
    )
    tasks = _build_tasks(config=config, agents=agents)

    process_name = config.get("process", "sequential")
    if process_name not in PROCESS_MAP:
        raise ValueError(f"Unsupported process: {process_name}")

    crew_kwargs: dict[str, Any] = {
        "agents": list(agents.values()),
        "tasks": tasks,
        "process": PROCESS_MAP[process_name],
        "verbose": config.get("verbose", True),
    }

    manager_model = config.get("manager_model")
    if process_name == "hierarchical" and manager_model:
        crew_kwargs["manager_llm"] = llms.get(manager_model)

    # Effort-driven planning
    if effort_overrides and effort_overrides.get("planning"):
        crew_kwargs["planning"] = True
        crew_kwargs["planning_llm"] = llms.get("cloud_fast")

    return Crew(**crew_kwargs)
```

#### Verification

```bash
# Verify existing smoke test still works (uses default effort=standard)
# This is a quick structural check, not a full LLM run:
python -c "
import sys; sys.path.insert(0, 'src')
from agent_mesh.config_loader import load_crew_config, load_effort_config

effort = load_effort_config()
assert 'levels' in effort
assert 'standard' in effort['levels']

crew_config = load_crew_config('research')
assert 'agents' in crew_config
print('Config loads OK with effort system in place')
"
```

Also verify that the effort overrides are actually passed through:

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from agent_mesh.crew_builder import _resolve_effort_overrides

quick = _resolve_effort_overrides('quick')
exhaustive = _resolve_effort_overrides('exhaustive')
assert quick['max_iter'] == 5
assert exhaustive['max_iter'] == 40
assert exhaustive['planning'] == True
assert quick['planning'] == False
print('Effort overrides resolve correctly')
"
```

#### Acceptance Criteria

- [ ] `agent_factory.py` accepts `effort_overrides` and applies them to agents
- [ ] `crew_builder.py` accepts `effort` param and enables `planning` at ≥ thorough
- [ ] `_resolve_effort_overrides` returns correct values for all 4 levels
- [ ] Existing `runner.py` still works (effort defaults to "standard")
- [ ] No new files created (only modifications to existing modules)

---

### p2-s02 — Planner Core

**Branch:** `sprint/p2-s02-planner-core`
**Depends on:** p1-s01 (crew_spec), p1-s02 (configs, loaders), p1-s03 (registry, renderer), p2-s01 (effort)

#### Goal

Build the planner module: the LLM call that takes a free-form task + effort
level and returns a `PlannerResponse` (reuse/adapt/generate). Also create the
planner handbook.

#### Files to Create

**`config/planner_handbook.md`**

```markdown
# Planner Handbook

You are the crew planner for a CrewAI orchestration system. Your job is to
decide whether to reuse an existing crew, adapt one, or generate a new one.

## Rules

1. Return ONLY valid JSON matching the PlannerResponse schema.
2. Prefer reusing existing crews when they fit (decision: "reuse").
3. Adapt an existing crew when it's close but needs minor changes (decision: "adapt").
4. Generate a new crew only when nothing fits (decision: "generate").

## Crew Design Rules

- Process: default "sequential". Use "hierarchical" only for >5 agents with delegation.
- Agents: 2-8 per crew. Keep roles specialized. One goal per agent.
- Tasks: 1-12 per crew. At least one must contain {topic} in description.
- Tools: only use tools from the available tools list.
- Models: only use model profiles from the available models list.
- Context: use task context to pass upstream output. No cycles.
- Async: async tasks must have a downstream sync consumer. Last task cannot be async.

## Model Assignment

Follow the model policy provided. Key points:
- Assign swarm to parallel research workers — exploit its concurrency.
- Assign clever to analytical/synthesis tasks.
- Assign cloud_fast only for highest-value synthesis (sparingly).
- Only swarm has vision capability.

## Effort Scaling

- quick: 2-3 agents, no async branches
- standard: 3-4 agents, 1-2 async branches
- thorough: 4-6 agents, 2-4 async branches, include verification
- exhaustive: 5-8 agents, 4-8+ async branches, include audit steps

## Naming

- Agent names: snake_case, max 40 chars
- Task names: snake_case, max 40 chars
- Crew names: snake_case, descriptive, max 60 chars
```

**`src/agent_mesh/planner.py`**

```python
"""Planner — uses cloud LLM to select or generate crew configurations."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config_loader import (
    load_catalogs,
    load_crew_config,
    load_effort_config,
    load_model_policy,
    load_planner_handbook,
)
from .crew_renderer import render_crew_dict, save_generated_crew
from .crew_spec import (
    CrewSpecPayload,
    PlannerResponse,
    validate_crew_spec,
)
from .llm_registry import LLMRegistry
from .registry import CrewRegistry

logger = logging.getLogger(__name__)

PLANNER_MODEL_PROFILE = "cloud_fast"


@dataclass
class PlannerResult:
    decision: str
    crew_name: str
    crew_config: dict[str, Any]
    is_new: bool = False
    save_path: Path | None = None
    spec: CrewSpecPayload | None = None


def _build_planner_prompt(
    task_text: str,
    effort: str,
    handbook: str,
    model_policy: str,
    catalogs: dict[str, Any],
    candidates: list[str],
    available_tools: list[str],
    available_models: list[dict[str, Any]],
    effort_config: dict[str, Any],
) -> list[dict[str, str]]:
    """Build the messages list for the planner LLM call."""
    effort_level = effort_config.get("levels", {}).get(effort, {})

    user_content = f"""## Task
{task_text}

## Effort Level
{effort}
Max swarm agents: {effort_level.get('max_swarm_agents', 4)}

## Existing Crews
{chr(10).join(candidates) if candidates else 'No existing crews registered.'}

## Available Tools
{', '.join(available_tools)}

## Available Models
{json.dumps(available_models, indent=2)}

## Role Archetypes
{json.dumps(catalogs.get('role_archetypes', {}), indent=2)}

## Task Patterns
{json.dumps(catalogs.get('task_patterns', {}), indent=2)}

## Model Assignment Policy
{model_policy}

## Response Schema
Return JSON matching this schema exactly:
{{
  "decision": "reuse" | "adapt" | "generate",
  "reuse_crew": "crew_name (only if decision=reuse)",
  "base_crew": "crew_name (only if decision=adapt)",
  "crew_spec": {{ ... full CrewSpecPayload (only if decision=adapt or generate) }}
}}
"""

    return [
        {"role": "system", "content": handbook},
        {"role": "user", "content": user_content},
    ]


def plan_crew(
    task_text: str,
    effort: str,
    llms: LLMRegistry,
    registry: CrewRegistry,
    available_tools: set[str],
    available_models: set[str],
    model_concurrency: dict[str, int],
) -> PlannerResult:
    """Run the planner to decide crew selection/generation.

    Falls back to keyword routing on any failure.
    """
    handbook = load_planner_handbook()
    model_policy = load_model_policy()
    catalogs = load_catalogs()
    effort_config = load_effort_config()

    # Get candidate summaries from registry
    candidates_entries = registry.find_candidates(task_text, limit=5)
    candidates = [e.summary_for_planner() for e in candidates_entries]

    # Build model info for prompt (name + strengths + concurrency)
    from .config_loader import load_models_config
    models_config = load_models_config()
    models_info = []
    for name, m in models_config.get("models", {}).items():
        models_info.append({
            "name": name,
            "strengths": m.get("strengths", []),
            "max_concurrency": m.get("max_concurrency", 1),
            "has_vision": m.get("has_vision", False),
        })

    messages = _build_planner_prompt(
        task_text=task_text,
        effort=effort,
        handbook=handbook,
        model_policy=model_policy,
        catalogs=catalogs,
        candidates=candidates,
        available_tools=sorted(available_tools),
        available_models=models_info,
        effort_config=effort_config,
    )

    # Call the planner LLM
    planner_llm = llms.get(PLANNER_MODEL_PROFILE)
    try:
        response = planner_llm.call(messages=messages)
    except Exception:
        logger.exception("Planner LLM call failed")
        raise

    # Parse response
    raw_text = response if isinstance(response, str) else str(response)

    # Try to extract JSON from the response
    try:
        # Handle cases where LLM wraps JSON in markdown code blocks
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.strip().startswith("```") and not in_block:
                    in_block = True
                    continue
                if line.strip() == "```" and in_block:
                    break
                if in_block:
                    json_lines.append(line)
            cleaned = "\n".join(json_lines)

        parsed = json.loads(cleaned)
        planner_response = PlannerResponse(**parsed)
    except Exception:
        logger.exception("Failed to parse planner response")
        raise

    # Handle reuse
    if planner_response.decision == "reuse" and planner_response.reuse_crew:
        crew_config = load_crew_config(planner_response.reuse_crew)
        return PlannerResult(
            decision="reuse",
            crew_name=planner_response.reuse_crew,
            crew_config=crew_config,
        )

    # Handle adapt or generate
    if planner_response.crew_spec is None:
        raise ValueError(
            f"Planner returned decision='{planner_response.decision}' "
            f"but no crew_spec"
        )

    spec = planner_response.crew_spec

    # Validate
    errors = validate_crew_spec(
        spec, available_tools, available_models, model_concurrency
    )
    if errors:
        raise ValueError(
            f"Planner generated invalid crew spec: {'; '.join(errors)}"
        )

    crew_config = render_crew_dict(spec)
    return PlannerResult(
        decision=planner_response.decision,
        crew_name=spec.name,
        crew_config=crew_config,
        is_new=True,
        spec=spec,
    )
```

#### Verification

The planner depends on a live LLM call to `cloud_fast`, so a full end-to-end
test requires the LiteLLM proxy to be running. For this sprint, verify:

```bash
# 1. Structural imports work
python -c "
import sys; sys.path.insert(0, 'src')
from agent_mesh.planner import plan_crew, PlannerResult, _build_planner_prompt
from agent_mesh.registry import CrewRegistry
print('Planner module imports OK')
"

# 2. Prompt builds without error
python -c "
import sys, json; sys.path.insert(0, 'src')
from agent_mesh.planner import _build_planner_prompt
from agent_mesh.config_loader import load_catalogs, load_effort_config, load_model_policy, load_planner_handbook
messages = _build_planner_prompt(
    task_text='find jazz festivals in Berlin 2026',
    effort='standard',
    handbook=load_planner_handbook(),
    model_policy=load_model_policy(),
    catalogs=load_catalogs(),
    candidates=['- deep_research: Multi-agent deep research [tags: research]'],
    available_tools=['searxng_search', 'webpage_fetch'],
    available_models=[{'name': 'swarm', 'strengths': ['research'], 'max_concurrency': 16, 'has_vision': True}],
    effort_config=load_effort_config(),
)
assert len(messages) == 2
assert messages[0]['role'] == 'system'
total_chars = sum(len(m['content']) for m in messages)
print(f'Prompt built OK — {total_chars} chars ({total_chars // 4} est. tokens)')
"

# 3. Handbook file exists and is reasonable size
python -c "
with open('config/planner_handbook.md') as f:
    text = f.read()
assert len(text) > 200
assert 'PlannerResponse' in text or 'reuse' in text
print(f'Handbook OK — {len(text)} chars')
"
```

#### Acceptance Criteria

- [ ] `config/planner_handbook.md` exists with planner rules
- [ ] `src/agent_mesh/planner.py` exists with `plan_crew()` and `PlannerResult`
- [ ] `_build_planner_prompt()` builds a valid 2-message prompt
- [ ] Prompt total is under ~4K tokens (≈16K chars)
- [ ] `plan_crew()` handles reuse, adapt, and generate paths
- [ ] `plan_crew()` validates generated specs before returning
- [ ] Module imports cleanly without errors

---

### p2-s03 — Runner + CLI Integration

**Branch:** `sprint/p2-s03-runner-cli`
**Depends on:** p2-s01 (effort in crew_builder), p2-s02 (planner)

#### Goal

Wire the planner and effort system into `runner.py` and `start.sh`. After
this sprint, `./start.sh "my task"` goes through the planner, and
`./start.sh --crew research "my task"` uses the fast path.

#### Files to Modify

**`src/agent_mesh/runner.py`** — Add planner dispatch and effort:

The `run_task()` function gains:
- `effort` parameter (default from env or "standard")
- `save_name` parameter (for persisting generated crews)
- When no `crew_template` is given and planner is not disabled, invoke
  `plan_crew()`. On planner failure, fall back to `route_task()`.
- Pass `effort` to `build_crew()`.

The `run_from_env()` function reads `EFFORT`, `INPUT_FILE`, `CREW_SAVE_NAME`,
and `PLANNER_DISABLED` from environment.

Key changes to `run_task()`:

```python
def run_task(
    task_text: str | None = None,
    *,
    inputs: dict[str, Any] | None = None,
    scenario_name: str | None = None,
    crew_template: str | None = None,
    effort: str = "standard",
    save_name: str | None = None,
    planner_disabled: bool = False,
) -> Any:
    patch_litellm_message_sanitizer()
    models_config = load_models_config()
    tools_config = load_tools_config()
    llms = LLMRegistry(models_config)
    tools = build_tool_registry(tools_config)

    scenario_inputs: dict[str, Any] = {}
    if scenario_name:
        scenario_inputs = load_scenario_config(scenario_name).get("inputs", {})

    final_inputs = _merge_inputs(scenario_inputs, inputs)
    if task_text:
        final_inputs["task_text"] = task_text
    if task_text and (not inputs or "topic" not in inputs):
        final_inputs["topic"] = task_text

    # Resolve crew template
    template_name = _resolve_template(
        task_text=task_text,
        scenario_name=scenario_name,
        explicit_template=crew_template,
    )

    crew_config = None

    # If no explicit crew given, try planner
    if not crew_template and not scenario_name and task_text and not planner_disabled:
        try:
            from .planner import plan_crew
            from .registry import CrewRegistry

            registry = CrewRegistry()
            registry.load()

            available_tools = set(tools.keys())
            available_models = set(models_config.get("models", {}).keys())
            model_concurrency = {
                name: m.get("max_concurrency", 1)
                for name, m in models_config.get("models", {}).items()
            }

            planner_result = plan_crew(
                task_text=task_text,
                effort=effort,
                llms=llms,
                registry=registry,
                available_tools=available_tools,
                available_models=available_models,
                model_concurrency=model_concurrency,
            )

            crew_config = planner_result.crew_config
            template_name = planner_result.crew_name

            # Save generated crew if requested
            if planner_result.is_new and planner_result.spec:
                from .crew_renderer import save_generated_crew

                save_path = save_generated_crew(
                    planner_result.spec,
                    name=save_name or planner_result.spec.name,
                )
                # Update registry
                from .crew_spec import CrewSpecPayload
                from datetime import date

                registry.register(
                    CrewEntry(
                        name=save_name or planner_result.spec.name,
                        data={
                            "source": "generated",
                            "description": planner_result.spec.description,
                            "tags": planner_result.spec.tags,
                            "query_archetypes": planner_result.spec.query_archetypes,
                            "required_tools": sorted(
                                {t for a in planner_result.spec.agents for t in a.tools}
                            ),
                            "agent_count": len(planner_result.spec.agents),
                            "process": planner_result.spec.process,
                            "created_at": date.today().isoformat(),
                            "human_reviewed": False,
                            "base_crew": planner_result.base_crew
                            if hasattr(planner_result, "base_crew")
                            else None,
                        },
                    )
                )
                registry.save()

        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "Planner failed, falling back to keyword routing",
                exc_info=True,
            )
            crew_config = None

    if crew_config is None:
        crew_config = load_crew_config(template_name)

    crew = build_crew(
        config=crew_config, llms=llms, tools=tools, effort=effort,
    )
    return crew.kickoff(inputs=final_inputs)
```

Key changes to `run_from_env()`:

```python
def run_from_env() -> Any:
    task_text = os.getenv("TASK_TEXT")
    scenario_name = os.getenv("SCENARIO")
    crew_template = os.getenv("CREW_TEMPLATE")
    topic = os.getenv("TOPIC")
    effort = os.getenv("EFFORT", "standard")
    save_name = os.getenv("CREW_SAVE_NAME")
    planner_disabled = os.getenv("PLANNER_DISABLED", "0") in ("1", "true", "yes")
    input_file = os.getenv("INPUT_FILE")

    # Read task from file if specified
    if input_file and not task_text:
        from pathlib import Path

        input_path = Path(input_file)
        if input_path.exists():
            task_text = input_path.read_text(encoding="utf-8").strip()

    if not scenario_name and not crew_template and not task_text:
        scenario_name = "smoke"

    inputs = {}
    if topic:
        inputs["topic"] = topic

    return run_task(
        task_text=task_text,
        inputs=inputs or None,
        scenario_name=scenario_name,
        crew_template=crew_template,
        effort=effort,
        save_name=save_name,
        planner_disabled=planner_disabled,
    )
```

**`start.sh`** — Add CLI flag parsing:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Defaults
crew=""
effort=""
save_name=""
input_file=""
positional_args=()

# Parse flags
while [[ $# -gt 0 ]]; do
  case "$1" in
    --crew)
      crew="$2"
      shift 2
      ;;
    --effort)
      effort="$2"
      shift 2
      ;;
    --save)
      save_name="$2"
      shift 2
      ;;
    --input)
      input_file="$2"
      shift 2
      ;;
    *)
      positional_args+=("$1")
      shift
      ;;
  esac
done

# Remaining positional args become the task text
prompt="${positional_args[*]:-}"

if [[ -n "${prompt}" ]]; then
  export TASK_TEXT="${prompt}"
fi

docker compose run --rm --build \
  -e TASK_TEXT="${TASK_TEXT:-${prompt}}" \
  -e SCENARIO="${SCENARIO:-}" \
  -e CREW_TEMPLATE="${crew:-${CREW_TEMPLATE:-}}" \
  -e TOPIC="${TOPIC:-}" \
  -e EFFORT="${effort:-${EFFORT:-standard}}" \
  -e CREW_SAVE_NAME="${save_name:-${CREW_SAVE_NAME:-}}" \
  -e INPUT_FILE="${input_file:-${INPUT_FILE:-}}" \
  -e PLANNER_DISABLED="${PLANNER_DISABLED:-0}" \
  crewai
```

#### Verification

```bash
# 1. Verify start.sh parses flags
bash -x start.sh --crew research --effort quick "test topic" 2>&1 | head -20
# Should show CREW_TEMPLATE=research, EFFORT=quick, TASK_TEXT="test topic"

# 2. Verify runner.py imports and env reading work
python -c "
import os, sys
sys.path.insert(0, 'src')
os.environ['TASK_TEXT'] = 'find jazz festivals'
os.environ['EFFORT'] = 'thorough'
os.environ['PLANNER_DISABLED'] = '1'  # skip actual LLM call

from agent_mesh.runner import run_from_env
# This will fall back to keyword routing since planner is disabled
# It will fail at crew.kickoff() without LiteLLM, but the dispatch logic runs
try:
    run_from_env()
except Exception as e:
    print(f'Expected failure at execution stage: {type(e).__name__}')
    print('Dispatch logic executed successfully')
"
```

#### Acceptance Criteria

- [ ] `runner.py` has `effort`, `save_name`, `planner_disabled` parameters
- [ ] `runner.py` calls planner when no explicit crew is given
- [ ] `runner.py` falls back to keyword routing on planner failure
- [ ] `runner.py` reads `INPUT_FILE` and loads task text from file
- [ ] `runner.py` saves generated crews and updates registry
- [ ] `start.sh` accepts `--crew`, `--effort`, `--save`, `--input` flags
- [ ] Existing `SCENARIO=smoke` and `CREW_TEMPLATE=` env vars still work
- [ ] `build_crew` receives effort parameter

---

## Phase 3 — Polish

### p3-s01 — Usage Tracking + Crew Promotion

**Branch:** `sprint/p3-s01-usage-tracking`
**Depends on:** p2-s03

#### Goal

After each crew run, record success/failure in the registry. Add a
`--promote` CLI flag that copies a generated crew to `config/crews/` and
marks it `human_reviewed: true`.

#### Files to Modify

**`src/agent_mesh/runner.py`** — After `crew.kickoff()`, call
`registry.record_usage(template_name, success=True)` in a try/except.
On exception from kickoff, call `record_usage(..., success=False)` before
re-raising.

**`src/agent_mesh/registry.py`** — Add a `promote` method:

```python
def promote(self, name: str) -> Path | None:
    """Copy a generated crew to config/crews/ and mark human_reviewed."""
    import shutil

    entry = self._crews.get(name)
    if not entry or entry.source != "generated":
        return None

    src = CONFIG_DIR / "generated_crews" / f"{name}.yaml"
    dst = CONFIG_DIR / "crews" / f"{name}.yaml"
    if not src.exists():
        return None

    shutil.copy2(src, dst)
    entry.source = "manual"
    entry.human_reviewed = True
    return dst
```

**`start.sh`** — Add `--promote NAME` flag that runs a small Python script
to promote the crew and exit (does not run a crew).

#### Acceptance Criteria

- [ ] Registry records usage after every run (success and failure)
- [ ] `--promote NAME` copies YAML and updates registry
- [ ] Registry is saved to disk after each run

---

### p3-s02 — Adapt Path

**Branch:** `sprint/p3-s02-adapt-path`
**Depends on:** p3-s01

#### Goal

Implement the `adapt` decision path in the planner: load a base crew,
apply the spec's modifications (add/remove/modify agents and tasks),
render new YAML, and save.

#### Files to Modify

**`src/agent_mesh/planner.py`** — In `plan_crew()`, when
`decision == "adapt"` and `base_crew` is set, load the base crew config,
then override it with the fields from `crew_spec`. The adapt logic:

1. Load base crew config via `load_crew_config(base_crew)`
2. For each agent in `crew_spec.agents`: add or replace in base config
3. For each task in `crew_spec.tasks`: add or replace in base config
4. Update process if changed
5. Validate the merged result
6. Return merged config

**`tests/test_adapt.py`** — Test that adapting the `research` crew by adding
an auditor agent produces valid output.

#### Acceptance Criteria

- [ ] `plan_crew()` handles `decision="adapt"` correctly
- [ ] Adapted crew merges base + spec changes
- [ ] Adapted crew passes validation
- [ ] Adapted crew can be loaded by `crew_builder.build_crew()`
- [ ] Test covers adding an agent to an existing crew

---

## Sprint Dependency Graph

```
p1-s01 (CrewSpec model)
  │
  ├──→ p1-s02 (External configs)
  │       │
  │       ├──→ p1-s03 (Registry + renderer)
  │       │       │
  │       │       └──→ p2-s02 (Planner core)
  │       │               │
  │       └──→ p2-s01 (Effort system)
  │               │
  │               └──→ p2-s03 (Runner + CLI) ──→ p3-s01 (Usage tracking) ──→ p3-s02 (Adapt)
  │
  └──→ (p1-s03 also depends on p1-s01)
```

Sprints within the same phase can be parallelized where dependencies allow.
p1-s01 must complete first. Then p1-s02 can run. Then p1-s03 and p2-s01 can
run in parallel. Then p2-s02. Then p2-s03. Then p3-s01. Then p3-s02.
