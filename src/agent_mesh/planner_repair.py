"""Normalize and repair planner LLM output before validation."""
from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no", ""}:
            return False
    return bool(value)


def _sanitize_identifier(value: str, *, fallback: str, max_length: int) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    ascii_value = ascii_value.lower().replace("-", "_").replace(" ", "_")
    ascii_value = re.sub(r"[^a-z0-9_]+", "_", ascii_value)
    ascii_value = re.sub(r"_+", "_", ascii_value).strip("_")
    if not ascii_value:
        ascii_value = fallback
    if not ascii_value[0].isalpha():
        ascii_value = f"{fallback}_{ascii_value}"
    ascii_value = ascii_value[:max_length].rstrip("_")
    return ascii_value or fallback


def _deduplicate_name(
    value: str,
    *,
    fallback: str,
    max_length: int,
    seen: dict[str, int],
) -> str:
    base = _sanitize_identifier(value, fallback=fallback, max_length=max_length)
    count = seen.get(base, 0)
    seen[base] = count + 1
    if count == 0:
        return base

    suffix = f"_{count + 1}"
    trimmed = base[: max_length - len(suffix)].rstrip("_") or fallback
    return f"{trimmed}{suffix}"


def repair_planner_output(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply normalization rules to raw parsed JSON from the planner LLM."""
    repaired = copy.deepcopy(raw)
    crew_spec = repaired.get("crew_spec")
    if not isinstance(crew_spec, dict):
        return repaired

    spec = dict(crew_spec)
    spec_name = str(spec.get("name") or spec.get("crew_name") or "generated_crew")
    spec["name"] = _sanitize_identifier(spec_name, fallback="generated_crew", max_length=60)
    spec["description"] = str(spec.get("description") or spec["name"])
    spec["tags"] = [str(tag) for tag in _listify(spec.get("tags"))]
    spec["query_archetypes"] = [str(item) for item in _listify(spec.get("query_archetypes"))]

    agent_seen: dict[str, int] = {}
    agent_name_map: dict[str, str] = {}
    repaired_agents: list[dict[str, Any]] = []
    for index, agent in enumerate(_listify(spec.get("agents")), start=1):
        if not isinstance(agent, dict):
            continue
        agent_dict = dict(agent)
        raw_name = str(agent_dict.get("name") or f"agent_{index}")
        repaired_name = _deduplicate_name(
            raw_name,
            fallback=f"agent_{index}",
            max_length=40,
            seen=agent_seen,
        )
        agent_name_map.setdefault(raw_name, repaired_name)
        goal = str(agent_dict.get("goal") or f"Complete the {repaired_name} workstream.")
        repaired_agents.append(
            {
                "name": repaired_name,
                "role_archetype": str(
                    agent_dict.get("role_archetype")
                    or agent_dict.get("archetype")
                    or repaired_name
                ),
                "role": str(agent_dict.get("role") or repaired_name.replace("_", " ").title()),
                "goal": goal,
                "backstory": str(agent_dict.get("backstory") or goal),
                "model_profile": str(
                    agent_dict.get("model_profile")
                    or agent_dict.get("model")
                    or agent_dict.get("llm")
                    or ""
                ),
                "tools": [str(tool) for tool in _listify(agent_dict.get("tools"))],
                "allow_delegation": _coerce_bool(
                    agent_dict.get("allow_delegation", agent_dict.get("delegation", False))
                ),
            }
        )

    task_seen: dict[str, int] = {}
    task_name_map: dict[str, str] = {}
    repaired_tasks: list[dict[str, Any]] = []
    for index, task in enumerate(_listify(spec.get("tasks")), start=1):
        if not isinstance(task, dict):
            continue
        task_dict = dict(task)
        raw_name = str(task_dict.get("name") or task_dict.get("id") or f"task_{index}")
        repaired_name = _deduplicate_name(
            raw_name,
            fallback=f"task_{index}",
            max_length=40,
            seen=task_seen,
        )
        task_name_map.setdefault(raw_name, repaired_name)
        repaired_tasks.append(
            {
                "name": repaired_name,
                "description": str(task_dict.get("description") or task_dict.get("prompt") or ""),
                "expected_output": str(
                    task_dict.get("expected_output")
                    or task_dict.get("output")
                    or "A concise, structured result."
                ),
                "agent": str(task_dict.get("agent") or ""),
                "context": [str(item) for item in _listify(task_dict.get("context"))],
                "async_execution": _coerce_bool(
                    task_dict.get("async_execution", task_dict.get("async", False))
                ),
            }
        )

    for task in repaired_tasks:
        task["agent"] = agent_name_map.get(
            task["agent"],
            _sanitize_identifier(task["agent"], fallback="agent", max_length=40),
        )
        task["context"] = [
            task_name_map.get(
                context_name,
                _sanitize_identifier(context_name, fallback="task", max_length=40),
            )
            for context_name in task["context"]
        ]

    spec["agents"] = repaired_agents
    spec["tasks"] = repaired_tasks
    repaired["crew_spec"] = spec
    return repaired
