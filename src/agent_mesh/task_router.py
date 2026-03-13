from __future__ import annotations

from typing import Any


def route_task(task_text: str, routing_config: dict[str, Any]) -> str:
    lowered = task_text.lower()
    task_types = routing_config.get("task_types", {})

    for task_type in task_types.values():
        keywords = task_type.get("keywords", [])
        if any(keyword.lower() in lowered for keyword in keywords):
            return task_type["crew_template"]

    defaults = routing_config.get("defaults", {})
    return defaults.get("fallback_template", "research")
