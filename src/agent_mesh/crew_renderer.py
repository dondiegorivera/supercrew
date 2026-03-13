"""Render a CrewSpecPayload into a crew YAML file for crew_builder."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .config_loader import DATA_DIR
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
    """Save a rendered crew YAML to data/generated_crews/.

    Returns the path to the written file.
    """
    crew_name = name or spec.name
    generated_dir = DATA_DIR / "generated_crews"
    generated_dir.mkdir(parents=True, exist_ok=True)
    path = generated_dir / f"{crew_name}.yaml"
    path.write_text(render_crew_yaml(spec), encoding="utf-8")
    return path
