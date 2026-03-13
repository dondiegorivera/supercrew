from __future__ import annotations

from typing import Any

from crewai import Crew, Process, Task

from .agent_factory import build_agents
from .config_loader import load_effort_config
from .llm_registry import LLMRegistry


PROCESS_MAP = {
    "sequential": Process.sequential,
    "hierarchical": Process.hierarchical,
}


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
        config=config,
        llms=llms,
        tools=tools,
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

    if effort_overrides and effort_overrides.get("planning"):
        crew_kwargs["planning"] = True
        crew_kwargs["planning_llm"] = llms.get("cloud_fast")

    return Crew(**crew_kwargs)
