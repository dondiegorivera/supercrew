from __future__ import annotations

from typing import Any

from crewai import Crew, Process, Task

from .agent_factory import build_agents
from .config_loader import load_effort_config, normalize_effort
from .llm_registry import LLMRegistry


PROCESS_MAP = {
    "sequential": Process.sequential,
    "hierarchical": Process.hierarchical,
}


def _format_runtime_diagnostics(
    *,
    effort: str,
    effort_overrides: dict[str, Any] | None,
    process_name: str,
    agents: dict[str, Any],
) -> str:
    planning_enabled = bool(effort_overrides and effort_overrides.get("planning"))
    agent_parts = []
    for name, agent in agents.items():
        model_name = str(getattr(getattr(agent, "llm", None), "model", "") or "?")
        reasoning_enabled = bool(getattr(agent, "reasoning", False))
        agent_parts.append(
            f"{name}(model={model_name},reasoning={str(reasoning_enabled).lower()})"
        )
    agents_summary = ", ".join(agent_parts) if agent_parts else "none"
    return (
        f"[agent_mesh] effort={effort} planning={str(planning_enabled).lower()} "
        f"process={process_name} agents={agents_summary}"
    )


def _has_unexpected_reasoning(effort: str, agents: dict[str, Any]) -> bool:
    if effort not in {"quick", "standard"}:
        return False
    return any(bool(getattr(agent, "reasoning", False)) for agent in agents.values())


def _build_tasks(config: dict[str, Any], agents: dict[str, Any]) -> list[Task]:
    tasks: list[Task] = []
    task_index: dict[str, Task] = {}

    for name, task_spec in config.get("tasks", {}).items():
        context_names = task_spec.get("context", [])
        context_tasks = [task_index[context_name] for context_name in context_names]

        task_kwargs: dict[str, Any] = {
            "description": task_spec["description"],
            "expected_output": task_spec["expected_output"],
            "agent": agents[task_spec["agent"]],
        }
        if context_tasks:
            task_kwargs["context"] = context_tasks
        if "async_execution" in task_spec:
            task_kwargs["async_execution"] = task_spec["async_execution"]

        task = Task(**task_kwargs)
        task_index[name] = task
        tasks.append(task)

    return tasks


def _resolve_effort_overrides(
    effort: str,
    effort_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if effort_config is None:
        effort_config = load_effort_config()
    levels = effort_config.get("levels", {})
    return levels.get(normalize_effort(effort, effort_config))


def build_crew(
    config: dict[str, Any],
    llms: LLMRegistry,
    tools: dict[str, Any],
    effort: str = "standard",
    effort_config: dict[str, Any] | None = None,
) -> Crew:
    effort_overrides = _resolve_effort_overrides(effort, effort_config)
    agents = build_agents(
        config=config,
        llms=llms,
        tools=tools,
        effort_overrides=effort_overrides,
    )
    tasks = _build_tasks(config=config, agents=agents)

    process_name = config.get("process", "sequential")
    if process_name not in PROCESS_MAP:
        raise ValueError(f"Unsupported process: {process_name}")

    print(
        _format_runtime_diagnostics(
            effort=effort,
            effort_overrides=effort_overrides,
            process_name=process_name,
            agents=agents,
        )
    )
    if _has_unexpected_reasoning(effort, agents):
        print(
            f"[agent_mesh] warning: reasoning enabled during {effort} run; "
            "check effort overrides and generated crew settings"
        )

    crew_kwargs: dict[str, Any] = {
        "agents": list(agents.values()),
        "tasks": tasks,
        "process": PROCESS_MAP[process_name],
        "verbose": config.get("verbose", True),
    }

    manager_model = config.get("manager_model")
    if process_name == "hierarchical" and manager_model:
        crew_kwargs["manager_llm"] = llms.get(manager_model)

    if effort_overrides and effort_overrides.get("planning"):
        crew_kwargs["planning"] = True
        planning_profile = effort_overrides.get("planning_model", "clever")
        crew_kwargs["planning_llm"] = llms.get(planning_profile)

    return Crew(**crew_kwargs)
