"""Pydantic models for planner-generated crew specifications."""
from __future__ import annotations

from typing import Literal

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
    manager_model: str | None = None
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

    if len(spec.agents) < 2:
        errors.append(f"Too few agents: {len(spec.agents)} (min 2)")
    if len(spec.agents) > 8:
        errors.append(f"Too many agents: {len(spec.agents)} (max 8)")

    if len(spec.tasks) < 1:
        errors.append("No tasks defined (min 1)")
    if len(spec.tasks) > 12:
        errors.append(f"Too many tasks: {len(spec.tasks)} (max 12)")

    agent_names: set[str] = set()
    for agent in spec.agents:
        if agent.name in agent_names:
            errors.append(f"Duplicate agent name: {agent.name}")
        agent_names.add(agent.name)

    task_names: set[str] = set()
    for task in spec.tasks:
        if task.name in task_names:
            errors.append(f"Duplicate task name: {task.name}")
        task_names.add(task.name)

    for task in spec.tasks:
        if task.agent not in agent_names:
            errors.append(
                f"Task '{task.name}' references unknown agent '{task.agent}'"
            )

    for task in spec.tasks:
        for ctx in task.context:
            if ctx not in task_names:
                errors.append(
                    f"Task '{task.name}' context references unknown task '{ctx}'"
                )
            if ctx == task.name:
                errors.append(f"Task '{task.name}' references itself in context")

    task_deps: dict[str, list[str]] = {task.name: list(task.context) for task in spec.tasks}
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

    for task_name in task_deps:
        if _has_cycle(task_name):
            errors.append(f"Cycle detected in task context graph involving '{task_name}'")
            break

    for agent in spec.agents:
        for tool in agent.tools:
            if tool not in available_tools:
                errors.append(f"Agent '{agent.name}' uses unregistered tool '{tool}'")

    for agent in spec.agents:
        if agent.model_profile not in available_models:
            errors.append(
                f"Agent '{agent.name}' uses unknown model profile "
                f"'{agent.model_profile}'"
            )

    if spec.process == "hierarchical":
        if not spec.manager_model:
            errors.append("Hierarchical process requires 'manager_model' to be set")
        elif spec.manager_model not in available_models:
            errors.append(
                f"manager_model '{spec.manager_model}' is not a valid model profile"
            )

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

    task_list = spec.tasks
    task_index = {task.name: index for index, task in enumerate(task_list)}
    async_task_names = {task.name for task in spec.tasks if task.async_execution}
    for index, task in enumerate(task_list):
        for ctx in task.context:
            ctx_idx = task_index.get(ctx)
            if ctx_idx is not None and ctx_idx > index:
                errors.append(
                    f"Task '{task.name}' references future task '{ctx}' "
                    f"in context (context tasks must appear earlier in the task list)"
                )

        if not task.agent:
            errors.append(f"Task '{task.name}' must define an agent")

        if not task.async_execution:
            continue
        for ctx in task.context:
            if ctx not in async_task_names:
                continue
            has_sync_separator = False
            for reverse_index in range(index - 1, -1, -1):
                if task_list[reverse_index].name == ctx:
                    break
                if not task_list[reverse_index].async_execution:
                    has_sync_separator = True
                    break
            if not has_sync_separator:
                errors.append(
                    f"Async task '{task.name}' cannot include sequentially adjacent "
                    f"async task '{ctx}' in its context (CrewAI constraint)"
                )

    consumed_by_sync: set[str] = set()
    for task in spec.tasks:
        if not task.async_execution:
            consumed_by_sync.update(ctx for ctx in task.context if ctx in async_task_names)
    unconsumed = async_task_names - consumed_by_sync
    for task_name in unconsumed:
        errors.append(f"Async task '{task_name}' has no downstream sync consumer")

    if model_concurrency:
        async_agents_per_model: dict[str, int] = {}
        for task in spec.tasks:
            if task.async_execution:
                agent_spec = next((agent for agent in spec.agents if agent.name == task.agent), None)
                if agent_spec:
                    model = agent_spec.model_profile
                    async_agents_per_model[model] = async_agents_per_model.get(model, 0) + 1
        for model, count in async_agents_per_model.items():
            limit = model_concurrency.get(model)
            if limit is not None and count > limit:
                errors.append(
                    f"Model '{model}' has {count} async agents but "
                    f"max_concurrency is {limit}"
                )

    has_topic = any("{topic}" in task.description for task in spec.tasks)
    if not has_topic:
        errors.append("No task description contains the '{topic}' placeholder")

    return errors
