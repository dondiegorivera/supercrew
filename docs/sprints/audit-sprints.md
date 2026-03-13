# Audit Sprints — CrewAI Compatibility & Robustness

Reference: `docs/specs/architecture.md` v1.1, CrewAI v1.10.0 source

These sprints address the gap between our specification/validator and CrewAI's
actual runtime validation. Findings are based on reading CrewAI 1.10.0 source
code (`crew.py`, `task.py`) from the `sageil/crewai:1.10.0` Docker image.

---

## Discrepancy Summary

Cross-referencing our `validate_crew_spec()` in `crew_spec.py` against CrewAI's
`Crew` Pydantic model validators revealed these gaps:

### Rules we enforce that CrewAI also enforces (OK)
- Last task cannot be async (our check) vs. CrewAI's
  `validate_end_with_at_most_one_async_task` (stricter — see below)

### Rules CrewAI enforces that we DO NOT
| # | CrewAI Validator | What it checks | Our status |
|---|-----------------|----------------|------------|
| 1 | `validate_end_with_at_most_one_async_task` | The **trailing block** of async tasks can have at most 1 task. We only check the last task. CrewAI walks backward from the end: if the last 2+ tasks are all async, it rejects. | **Missing** — we only check `tasks[-1]` |
| 2 | `validate_async_task_cannot_include_sequential_async_tasks_in_context` | An async task cannot list another async task in its `context` if they are **sequentially adjacent** (no sync task between them). This is the exact error the user hit. | **Missing** |
| 3 | `validate_context_no_future_tasks` | A task's `context` cannot reference a task that appears **later** in the task list (by index). | **Missing** |
| 4 | `validate_tasks` (sequential process) | Every task in a sequential crew **must** have an agent assigned. | **Missing** (we check agent name exists, but not that it's non-null) |
| 5 | `check_manager_llm` | Hierarchical process requires `manager_llm` or `manager_agent`. Manager agent must NOT be in the agents list. | **Missing** — our spec has no `manager_model` field |
| 6 | `validate_first_task` | First task cannot be a `ConditionalTask`. | N/A — we don't generate ConditionalTasks |
| 7 | `validate_must_have_non_conditional_task` | At least one non-conditional task. | N/A |

### Rules we enforce that CrewAI does NOT
| # | Our rule | Notes |
|---|----------|-------|
| 1 | Agent count 2–8 | Soft design choice, not a CrewAI constraint |
| 2 | Task count 1–12 | Soft design choice |
| 3 | `{topic}` placeholder required | Our convention, not CrewAI |
| 4 | Model concurrency limit | Our resource management, not CrewAI |
| 5 | Async task must have sync consumer | CrewAI doesn't enforce this explicitly — it's a design best practice |

### Other spec/implementation discrepancies found

| # | Issue | Detail |
|---|-------|--------|
| A | Planner handbook async rule too vague | Says "async tasks must have a downstream sync consumer" but doesn't mention the sequential-adjacency constraint or the trailing-block constraint |
| B | No `manager_model` in CrewSpecPayload | Architecture spec §7.1 doesn't include a field for hierarchical manager LLM, yet we support `process: "hierarchical"` |
| C | `crew_builder.py` reads `manager_model` from config | Line 80-82 in crew_builder.py reads `config.get("manager_model")`, but `crew_renderer.py` never writes this field |
| D | Planner output normalization only in handbook | No code-level repair for common LLM mistakes (missing fields, wrong field names, non-ASCII identifiers) |
| E | Runtime state in tracked paths | `config/crew_registry.yaml` and `config/generated_crews/` are written at runtime but live alongside tracked config |
| F | Docker entrypoint writes to `/workspace` | Registry save, generated crew save, and output writes all target bind-mounted paths — requires the UID/GID fix to be in place |

---

## Phase A — Validator Alignment (highest priority)

### a-s01 — Align validate_crew_spec with CrewAI Runtime

**Branch:** `sprint/a-s01-validator-alignment`
**Depends on:** nothing
**Priority:** Critical — this is the #1 source of runtime failures

#### Goal

Make `validate_crew_spec()` reject every crew that CrewAI's `Crew(**kwargs)`
would reject, so failures happen at validation time with clear messages instead
of at runtime with CrewAI stack traces.

#### Changes to `src/agent_mesh/crew_spec.py`

Add the following validation rules to `validate_crew_spec()`:

**Rule 1: Trailing async block limit**

CrewAI's `validate_end_with_at_most_one_async_task` walks the task list
backward from the end. If it encounters 2+ consecutive async tasks before
hitting a sync task, it rejects.

```python
# Walk tasks backward — count consecutive trailing async tasks
trailing_async = 0
for task in reversed(spec.tasks):
    if task.async_execution:
        trailing_async += 1
    else:
        break
if trailing_async > 1:
    errors.append(
        f"Crew ends with {trailing_async} consecutive async tasks "
        f"(max 1 trailing async task allowed by CrewAI)"
    )
```

Also **update** the existing last-task-async check: the current check
(`if last_task.async_execution`) is subsumed by this new rule, so replace it.

**Rule 2: Async task cannot have sequential async tasks in context**

CrewAI's `validate_async_task_cannot_include_sequential_async_tasks_in_context`:
for each async task, check its context entries. If a context entry is also async
AND there is no sync task between them (walking backward from the current task),
reject.

```python
task_list = spec.tasks
task_index = {t.name: i for i, t in enumerate(task_list)}
async_set = {t.name for t in task_list if t.async_execution}

for i, task in enumerate(task_list):
    if not task.async_execution:
        continue
    for ctx_name in task.context:
        if ctx_name not in async_set:
            continue
        # ctx_name is async — check if there's a sync task between them
        ctx_idx = task_index.get(ctx_name)
        if ctx_idx is None:
            continue
        # Walk backward from i-1 to find the context task
        has_sync_separator = False
        for j in range(i - 1, -1, -1):
            if task_list[j].name == ctx_name:
                break  # found it without a sync separator
            if not task_list[j].async_execution:
                has_sync_separator = True
                break
        if not has_sync_separator:
            errors.append(
                f"Async task '{task.name}' cannot include sequentially adjacent "
                f"async task '{ctx_name}' in its context (CrewAI constraint)"
            )
```

**Rule 3: Context cannot reference future tasks**

CrewAI's `validate_context_no_future_tasks`: a task's context entries must
appear earlier in the task list (lower index).

```python
for i, task in enumerate(task_list):
    for ctx_name in task.context:
        ctx_idx = task_index.get(ctx_name)
        if ctx_idx is not None and ctx_idx > i:
            errors.append(
                f"Task '{task.name}' references future task '{ctx_name}' "
                f"in context (context tasks must appear earlier in the task list)"
            )
```

**Rule 4: Hierarchical process requires manager_model**

Add a `manager_model` field to `CrewSpecPayload` (optional, `str | None`).
Validate that if `process == "hierarchical"`, `manager_model` is set and
references a valid model profile.

```python
if spec.process == "hierarchical":
    if not spec.manager_model:
        errors.append(
            "Hierarchical process requires 'manager_model' to be set"
        )
    elif spec.manager_model not in available_models:
        errors.append(
            f"manager_model '{spec.manager_model}' is not a valid model profile"
        )
```

#### Changes to `src/agent_mesh/crew_renderer.py`

Update `render_crew_dict()` to include `manager_model` in the output when
`spec.process == "hierarchical"` and `spec.manager_model` is set.

#### Changes to `src/agent_mesh/crew_builder.py`

No changes needed — it already reads `config.get("manager_model")` on line 80.

#### Tests to add/update in `tests/test_crew_spec.py`

1. `test_trailing_async_block_rejected` — 2 async tasks at the end, no sync after
2. `test_single_trailing_async_allowed` — 1 async task at end is OK
3. `test_async_context_sequential_adjacent_rejected` — async task lists adjacent async in context
4. `test_async_context_with_sync_separator_allowed` — async task lists async in context but sync task between them
5. `test_context_references_future_task_rejected` — task lists a later task in context
6. `test_context_references_earlier_task_allowed` — normal forward context
7. `test_hierarchical_without_manager_rejected` — hierarchical + no manager_model
8. `test_hierarchical_with_manager_passes` — hierarchical + valid manager_model

Update existing `test_async_last_task_rejected` to align with the new trailing-block logic.

#### Verification

```bash
.venv/bin/python -m pytest tests/test_crew_spec.py -v
```

All existing tests must still pass. New tests must cover the 4 new rules.

---

## Phase B — Planner Output Normalization

### a-s02 — Planner Response Repair Layer

**Branch:** `sprint/a-s02-planner-normalization`
**Depends on:** a-s01

#### Goal

Add a normalization/repair layer between the raw LLM JSON response and Pydantic
parsing, so common LLM mistakes are auto-corrected instead of causing failures.

#### File to create: `src/agent_mesh/planner_repair.py`

```python
"""Normalize and repair planner LLM output before validation."""
from __future__ import annotations

import re
from typing import Any


def repair_planner_output(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply normalization rules to raw parsed JSON from the planner LLM.

    Fixes common LLM mistakes:
    1. Field aliases: 'model' -> 'model_profile', 'archetype' -> 'role_archetype'
    2. Missing defaults: add empty 'description', 'tags', 'query_archetypes' if absent
    3. Non-ASCII identifiers: sanitize names to ASCII snake_case
    4. Boolean coercion: "true"/"false" strings -> bool for async_execution
    5. Missing role_archetype: default to agent name
    6. Missing backstory: default to goal
    """
```

**Specific repair rules:**

1. **Field aliases** in agent specs:
   - `model` → `model_profile`
   - `archetype` → `role_archetype`
   - `delegation` → `allow_delegation`

2. **Field aliases** in task specs:
   - `output` → `expected_output`
   - `async` → `async_execution`

3. **Missing optional fields** in crew spec:
   - `description` → default to `name` value
   - `tags` → default to `[]`
   - `query_archetypes` → default to `[]`

4. **Name sanitization**:
   - Replace non-ASCII characters with ASCII equivalents (ö→o, ü→u, etc.)
   - Replace spaces/hyphens with underscores
   - Strip characters outside `[a-z0-9_]`
   - Truncate to field length limits (40 for agent/task, 60 for crew)
   - Deduplicate names by appending `_2`, `_3`, etc.

5. **Boolean coercion**:
   - String `"true"`/`"false"` → `True`/`False` for `async_execution`, `allow_delegation`

6. **Default backstory**: If `backstory` is missing or empty, copy from `goal`.

7. **Default role_archetype**: If missing, use the agent's `name`.

#### Changes to `src/agent_mesh/planner.py`

Insert the repair call between JSON parsing and `PlannerResponse(**parsed)`:

```python
from .planner_repair import repair_planner_output

# ... after json.loads(cleaned):
parsed = repair_planner_output(parsed)
planner_response = PlannerResponse(**parsed)
```

#### Tests: `tests/test_planner_repair.py`

1. `test_model_alias_fixed` — `{"model": "swarm"}` → `{"model_profile": "swarm"}`
2. `test_non_ascii_name_sanitized` — `"search_trödelmarkts"` → `"search_trodelmarkts"`
3. `test_missing_description_defaulted` — crew_spec without description gets one
4. `test_boolean_coercion` — `"true"` → `True`
5. `test_missing_backstory_defaults_to_goal`
6. `test_missing_role_archetype_defaults_to_name`
7. `test_duplicate_names_deduplicated`
8. `test_already_valid_input_unchanged` — valid input passes through untouched

#### Verification

```bash
.venv/bin/python -m pytest tests/test_planner_repair.py -v
```

---

## Phase C — Planner Handbook & Prompt Hardening

### a-s03 — Update Planner Handbook with CrewAI Constraints

**Branch:** `sprint/a-s03-handbook-update`
**Depends on:** a-s01

#### Goal

Update `config/planner_handbook.md` to include the specific CrewAI constraints
we discovered, so the LLM is less likely to generate invalid crews in the first
place. Also update the prompt in `_build_planner_prompt()` to include the
response schema inline.

#### Changes to `config/planner_handbook.md`

Replace the current "Async" rule (line 24) with a more detailed section:

```markdown
## Async Execution Rules (CrewAI constraints — must follow exactly)

1. The task list is ordered. Context can only reference tasks that appear
   EARLIER in the list (lower index). Never reference a task that comes later.
2. An async task CANNOT list another async task in its context if they are
   sequentially adjacent (no sync task between them in the task list).
3. The crew can end with at most ONE async task. If the last 2+ tasks are
   all async, CrewAI will reject the crew.
4. Every async task should have a downstream sync task that lists it in
   context (design best practice — ensures results are consumed).
5. In sequential process, every task MUST have an agent assigned.

Correct async fan-out pattern:
  task_a (async, agent=swarm_1)
  task_b (async, agent=swarm_2)
  task_c (sync, agent=analyst, context=[task_a, task_b])  ← collects both

Wrong patterns:
  task_a (async) → task_b (async, context=[task_a]) ← REJECTED: adjacent async in context
  task_a (async) → task_b (async) ← REJECTED: 2 trailing async tasks
  task_a (sync) → task_b (sync, context=[task_a, task_c]) where task_c is later ← REJECTED
```

Add hierarchical process section:

```markdown
## Hierarchical Process

- Only use when >5 agents with complex delegation needs.
- MUST include "manager_model" field set to a valid model profile.
- Manager model should be the most capable available (typically cloud_fast).
- Do NOT include the manager as an agent in the agents list.
```

#### Changes to `src/agent_mesh/planner.py` `_build_planner_prompt()`

Add explicit field name listing in the response schema section to reduce
alias mistakes:

```
## Required Field Names (use EXACTLY these)
Agent fields: name, role_archetype, role, goal, backstory, model_profile, tools, allow_delegation
Task fields: name, description, expected_output, agent, context, async_execution
Crew fields: name, description, process, tags, query_archetypes, agents, tasks
```

#### Verification

```bash
wc -c config/planner_handbook.md  # should stay under 3KB
```

Review the handbook manually for accuracy against the CrewAI constraints.

---

## Phase D — Runtime State Separation

### a-s04 — Move Runtime State Out of Config

**Branch:** `sprint/a-s04-runtime-state`
**Depends on:** nothing (parallel with a-s01)

#### Goal

Separate runtime-mutable state from tracked configuration files so that:
1. Git status stays clean during crew runs
2. Runtime writes don't conflict with code commits
3. The container can write state without touching tracked files

#### Design

```
config/                          # TRACKED — immutable at runtime
  crews/                         # hand-authored crews (read-only)
  catalogs/                      # role archetypes, task patterns (read-only)
  effort.yaml                    # (read-only)
  models.yaml                    # (read-only)
  model_policy.yaml              # (read-only)
  planner_handbook.md            # (read-only)
  routing.yaml                   # (read-only)
  tools.yaml                     # (read-only)

data/                            # GITIGNORED — runtime-mutable state
  crew_registry.yaml             # moved from config/
  generated_crews/               # moved from config/
```

#### Changes to `src/agent_mesh/config_loader.py`

Add a `DATA_DIR` constant pointing to `data/` (sibling of `config/`).
Update these functions:
- `load_registry_config()` → read from `DATA_DIR / "crew_registry.yaml"`
- `save_registry_config()` → write to `DATA_DIR / "crew_registry.yaml"`
- `load_crew_config()` → search order: `config/crews/`, then `data/generated_crews/`

Create `DATA_DIR` and seed `data/crew_registry.yaml` from current
`config/crew_registry.yaml` if it doesn't exist (first-run migration).

#### Changes to `src/agent_mesh/crew_renderer.py`

Update `save_generated_crew()` to write to `DATA_DIR / "generated_crews/"`.

#### Changes to `.gitignore`

```
# Runtime state (written by crew runs)
/data/
```

#### Migration

Add a one-time migration in `config_loader.py`:

```python
def _ensure_data_dir() -> None:
    """Create data/ and seed registry from config/ on first run."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    registry_path = DATA_DIR / "crew_registry.yaml"
    if not registry_path.exists():
        seed = CONFIG_DIR / "crew_registry.yaml"
        if seed.exists():
            shutil.copy2(seed, registry_path)
    generated_dir = DATA_DIR / "generated_crews"
    generated_dir.mkdir(parents=True, exist_ok=True)
```

Call `_ensure_data_dir()` from `load_registry_config()` and `save_registry_config()`.

#### Changes to `src/agent_mesh/registry.py`

Update `promote()` to copy from `DATA_DIR / "generated_crews/"` to
`CONFIG_DIR / "crews/"`.

#### Changes to `docker-compose.yml`

Ensure `/workspace/data` is writable. With the current bind mount of `./:/workspace`
and UID/GID passthrough, this should work automatically.

#### Tests

Update `tests/test_registry.py`:
- `test_generated_crew_round_trip` should reference the new path
- Add `test_data_dir_created_on_first_load` — verify `data/` directory is created

#### Verification

```bash
.venv/bin/python -m pytest tests/ -v
ls -la data/  # should exist after test run
git status    # data/ should not appear (gitignored)
```

---

## Phase E — Dockerfile & Container Hardening

### a-s05 — Container Runtime Fixes

**Branch:** `sprint/a-s05-container-hardening`
**Depends on:** a-s04

#### Goal

Ensure the container can run reliably without filesystem permission issues,
regardless of host UID/GID, and that CrewAI's runtime state directories are
properly handled.

#### Changes to `dockerfile`

```dockerfile
FROM sageil/crewai:1.10.0

USER root
RUN python -m pip install --no-cache-dir crewai litellm requests pypdf

# Ensure crewai packages are accessible to all users
RUN chmod -R a+rX /home/appuser/.local/lib/

WORKDIR /workspace

# Don't hardcode user — docker-compose.yml sets user via LOCAL_UID:LOCAL_GID
# The entrypoint script will create needed temp dirs
CMD ["python", "supercrew.py"]
```

Remove `USER appuser` since docker-compose.yml already sets `user:`.

#### Changes to `supercrew.py`

Add a startup preamble that ensures writable directories exist:

```python
import os
from pathlib import Path

# Ensure CrewAI/LiteLLM runtime dirs exist and are writable
for env_var, default in [
    ("HOME", "/tmp/crewai-home"),
    ("XDG_DATA_HOME", "/tmp/crewai-home/.local/share"),
    ("XDG_CACHE_HOME", "/tmp/crewai-home/.cache"),
    ("XDG_CONFIG_HOME", "/tmp/crewai-home/.config"),
]:
    path = Path(os.environ.get(env_var, default))
    path.mkdir(parents=True, exist_ok=True)
```

#### Verification

```bash
# Build and run with default UID
docker compose run --rm crewai python -c "import crewai; print('OK')"

# Build and run as a different user
docker compose run --rm --user 1001:1001 crewai python -c "import crewai; print('OK')"
```

---

## Sprint Execution Order

```
a-s01 (validator alignment)     ← CRITICAL, do first
a-s04 (runtime state separation) ← can run in parallel with a-s01
a-s02 (planner normalization)   ← depends on a-s01
a-s03 (handbook update)         ← depends on a-s01
a-s05 (container hardening)     ← depends on a-s04
```

Suggested parallel execution:
- **Batch 1**: a-s01 + a-s04 (independent)
- **Batch 2**: a-s02 + a-s03 (both depend on a-s01)
- **Batch 3**: a-s05 (depends on a-s04)

---

## Acceptance Criteria (end-to-end)

After all sprints are complete:

1. `validate_crew_spec()` rejects every pattern that CrewAI's `Crew()` would reject
2. Planner LLM output with common mistakes (wrong field names, non-ASCII, missing
   fields) is auto-repaired before validation
3. Planner handbook explicitly documents all async/context constraints
4. `git status` stays clean during crew runs (no runtime writes to tracked files)
5. Container runs without permission errors regardless of host UID
6. All tests pass: `.venv/bin/python -m pytest tests/ -v`
