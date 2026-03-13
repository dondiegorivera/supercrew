"""Planner — uses cloud LLM to select or generate crew configurations."""
from __future__ import annotations

import copy
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config_loader import (
    load_catalogs,
    load_crew_config,
    load_effort_config,
    load_model_policy,
    load_planner_handbook,
)
from .crew_renderer import render_crew_dict
from .crew_spec import CrewSpecPayload, PlannerResponse, validate_crew_spec
from .llm_registry import LLMRegistry
from .registry import CrewRegistry

logger = logging.getLogger(__name__)

PLANNER_MODEL_PROFILE = "cloud_fast"


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


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _normalize_planner_payload(parsed: dict[str, Any], task_text: str) -> dict[str, Any]:
    normalized = dict(parsed)
    crew_spec = normalized.get("crew_spec")
    if not isinstance(crew_spec, dict):
        return normalized

    spec = dict(crew_spec)
    spec["name"] = _sanitize_identifier(
        str(spec.get("name") or spec.get("crew_name") or "generated_crew"),
        fallback="generated_crew",
        max_length=60,
    )
    spec["description"] = str(
        spec.get("description") or f"Generated crew for: {task_text[:120]}"
    )
    spec["process"] = spec.get("process", "sequential")
    spec["tags"] = [str(tag) for tag in _listify(spec.get("tags"))]
    spec["query_archetypes"] = [
        str(item)
        for item in _listify(
            spec.get("query_archetypes") or spec.get("queries") or spec.get("archetypes")
        )
    ]

    original_agents = _listify(spec.get("agents"))
    agent_name_map: dict[str, str] = {}
    normalized_agents: list[dict[str, Any]] = []
    for index, agent in enumerate(original_agents, start=1):
        if not isinstance(agent, dict):
            continue
        agent_dict = dict(agent)
        raw_name = str(agent_dict.get("name") or f"agent_{index}")
        sanitized_name = _sanitize_identifier(raw_name, fallback=f"agent_{index}", max_length=40)
        agent_name_map[raw_name] = sanitized_name
        normalized_agents.append(
            {
                "name": sanitized_name,
                "role_archetype": str(
                    agent_dict.get("role_archetype")
                    or agent_dict.get("archetype")
                    or sanitized_name
                ),
                "role": str(agent_dict.get("role") or sanitized_name.replace("_", " ").title()),
                "goal": str(agent_dict.get("goal") or f"Complete the {sanitized_name} workstream."),
                "backstory": str(agent_dict.get("backstory") or ""),
                "model_profile": str(
                    agent_dict.get("model_profile")
                    or agent_dict.get("model")
                    or agent_dict.get("llm")
                ),
                "tools": [str(tool) for tool in _listify(agent_dict.get("tools"))],
                "allow_delegation": bool(agent_dict.get("allow_delegation", False)),
            }
        )

    original_tasks = _listify(spec.get("tasks"))
    task_name_map: dict[str, str] = {}
    normalized_tasks: list[dict[str, Any]] = []
    for index, task in enumerate(original_tasks, start=1):
        if not isinstance(task, dict):
            continue
        task_dict = dict(task)
        raw_name = str(task_dict.get("name") or task_dict.get("id") or f"task_{index}")
        sanitized_name = _sanitize_identifier(raw_name, fallback=f"task_{index}", max_length=40)
        task_name_map[raw_name] = sanitized_name
        normalized_tasks.append(
            {
                "name": sanitized_name,
                "description": str(task_dict.get("description") or task_dict.get("prompt") or ""),
                "expected_output": str(
                    task_dict.get("expected_output")
                    or task_dict.get("output")
                    or "A concise, structured result."
                ),
                "agent": str(task_dict.get("agent") or ""),
                "context": [str(item) for item in _listify(task_dict.get("context"))],
                "async_execution": bool(task_dict.get("async_execution", False)),
            }
        )

    for task in normalized_tasks:
        task["agent"] = agent_name_map.get(task["agent"], _sanitize_identifier(
            task["agent"],
            fallback="agent",
            max_length=40,
        ))
        task["context"] = [
            task_name_map.get(context_name, _sanitize_identifier(context_name, fallback="task", max_length=40))
            for context_name in task["context"]
        ]

    spec["agents"] = normalized_agents
    spec["tasks"] = normalized_tasks
    normalized["crew_spec"] = spec
    return normalized


def _repair_async_task_graph(spec: CrewSpecPayload) -> CrewSpecPayload:
    tasks = [task.model_copy(deep=True) for task in spec.tasks]
    sync_consumers_by_async: dict[str, bool] = {
        task.name: False for task in tasks if task.async_execution
    }
    if not sync_consumers_by_async:
        return spec

    for task in tasks:
        if task.async_execution:
            continue
        for context_name in task.context:
            if context_name in sync_consumers_by_async:
                sync_consumers_by_async[context_name] = True

    for index, task in enumerate(tasks):
        if not task.async_execution or sync_consumers_by_async.get(task.name):
            continue

        target = next(
            (candidate for candidate in tasks[index + 1 :] if not candidate.async_execution),
            None,
        )
        if target is None:
            target = next((candidate for candidate in reversed(tasks) if not candidate.async_execution), None)
        if target is None:
            continue
        if task.name not in target.context:
            target.context.append(task.name)
        sync_consumers_by_async[task.name] = True

    return spec.model_copy(update={"tasks": tasks})


def _repair_agent_limit(spec: CrewSpecPayload, *, max_agents: int = 8) -> CrewSpecPayload:
    if len(spec.agents) <= max_agents:
        return spec

    task_counts: dict[str, int] = {agent.name: 0 for agent in spec.agents}
    sync_task_counts: dict[str, int] = {agent.name: 0 for agent in spec.agents}
    for task in spec.tasks:
        if task.agent in task_counts:
            task_counts[task.agent] += 1
            if not task.async_execution:
                sync_task_counts[task.agent] += 1

    ranked_agents = sorted(
        enumerate(spec.agents),
        key=lambda item: (
            sync_task_counts.get(item[1].name, 0),
            task_counts.get(item[1].name, 0),
            item[0] * -1,
        ),
        reverse=True,
    )
    kept_names = {agent.name for _, agent in ranked_agents[:max_agents]}
    kept_agents = [agent.model_copy(deep=True) for agent in spec.agents if agent.name in kept_names]
    kept_name_set = {agent.name for agent in kept_agents}

    def _replacement_agent_name(agent_name: str) -> str:
        original_agent = next((agent for agent in spec.agents if agent.name == agent_name), None)
        if original_agent is None:
            return kept_agents[0].name

        same_model = [
            agent for agent in kept_agents if agent.model_profile == original_agent.model_profile
        ]
        same_role = [
            agent for agent in same_model if agent.role_archetype == original_agent.role_archetype
        ]
        candidates = same_role or same_model or kept_agents
        candidates = sorted(
            candidates,
            key=lambda agent: (task_counts.get(agent.name, 0), sync_task_counts.get(agent.name, 0)),
        )
        return candidates[0].name

    repaired_tasks: list[Any] = []
    for task in spec.tasks:
        repaired_task = task.model_copy(deep=True)
        if repaired_task.agent not in kept_name_set:
            repaired_task.agent = _replacement_agent_name(repaired_task.agent)
        repaired_tasks.append(repaired_task)

    return spec.model_copy(update={"agents": kept_agents, "tasks": repaired_tasks})


@dataclass
class PlannerResult:
    decision: str
    crew_name: str
    crew_config: dict[str, Any]
    is_new: bool = False
    save_path: Path | None = None
    spec: CrewSpecPayload | None = None
    base_crew: str | None = None


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
    force_generate: bool = False,
) -> list[dict[str, str]]:
    """Build the messages list for the planner LLM call."""
    effort_level = effort_config.get("levels", {}).get(effort, {})
    generation_rule = ""
    if force_generate:
        generation_rule = (
            "\n## Generation Mode\n"
            "Start from scratch. Do not reuse or adapt an existing crew. "
            "You must return decision=\"generate\".\n"
        )

    user_content = f"""## Task
{task_text}

## Effort Level
{effort}
Max swarm agents: {effort_level.get('max_swarm_agents', 4)}

## Existing Crews
{chr(10).join(candidates) if candidates else 'No existing crews registered.'}
{generation_rule}

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


def _agent_config_to_spec(name: str, agent_config: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "role_archetype": str(agent_config.get("role_archetype") or name),
        "role": agent_config["role"],
        "goal": agent_config["goal"],
        "backstory": agent_config.get("backstory", ""),
        "model_profile": agent_config["model_profile"],
        "tools": list(agent_config.get("tools", [])),
        "allow_delegation": agent_config.get("allow_delegation", False),
    }


def _task_config_to_spec(name: str, task_config: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "description": task_config["description"],
        "expected_output": task_config["expected_output"],
        "agent": task_config["agent"],
        "context": list(task_config.get("context", [])),
        "async_execution": task_config.get("async_execution", False),
    }


def _crew_config_to_payload(
    config: dict[str, Any],
    *,
    name: str,
    description: str,
    tags: list[str],
    query_archetypes: list[str],
) -> CrewSpecPayload:
    return CrewSpecPayload(
        name=name,
        description=description,
        process=config.get("process", "sequential"),
        tags=tags,
        query_archetypes=query_archetypes,
        agents=[
            _agent_config_to_spec(agent_name, agent_config)
            for agent_name, agent_config in config.get("agents", {}).items()
        ],
        tasks=[
            _task_config_to_spec(task_name, task_config)
            for task_name, task_config in config.get("tasks", {}).items()
        ],
    )


def _merge_adapted_crew_config(
    base_config: dict[str, Any],
    spec: CrewSpecPayload,
) -> dict[str, Any]:
    merged = copy.deepcopy(base_config)
    merged["name"] = spec.name
    merged["process"] = spec.process
    merged["verbose"] = base_config.get("verbose", True)
    merged.setdefault("agents", {})
    merged.setdefault("tasks", {})

    for agent in spec.agents:
        merged["agents"][agent.name] = {
            "role": agent.role,
            "goal": agent.goal,
            "backstory": agent.backstory,
            "model_profile": agent.model_profile,
            "tools": list(agent.tools),
            "allow_delegation": agent.allow_delegation,
            "verbose": True,
        }

    for task in spec.tasks:
        task_config: dict[str, Any] = {
            "description": task.description,
            "expected_output": task.expected_output,
            "agent": task.agent,
        }
        if task.context:
            task_config["context"] = list(task.context)
        if task.async_execution:
            task_config["async_execution"] = True
        merged["tasks"][task.name] = task_config

    return merged


def plan_crew(
    task_text: str,
    effort: str,
    llms: LLMRegistry,
    registry: CrewRegistry,
    available_tools: set[str],
    available_models: set[str],
    model_concurrency: dict[str, int],
    force_generate: bool = False,
) -> PlannerResult:
    """Run the planner to decide crew selection/generation."""
    handbook = load_planner_handbook()
    model_policy = load_model_policy()
    catalogs = load_catalogs()
    effort_config = load_effort_config()

    candidates_entries = [] if force_generate else registry.find_candidates(task_text, limit=5)
    candidates = [entry.summary_for_planner() for entry in candidates_entries]

    from .config_loader import load_models_config

    models_config = load_models_config()
    models_info = []
    for name, model in models_config.get("models", {}).items():
        models_info.append(
            {
                "name": name,
                "strengths": model.get("strengths", []),
                "max_concurrency": model.get("max_concurrency", 1),
                "has_vision": model.get("has_vision", False),
            }
        )

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
        force_generate=force_generate,
    )

    planner_llm = llms.get(PLANNER_MODEL_PROFILE)
    try:
        response = planner_llm.call(messages=messages)
    except Exception:
        logger.exception("Planner LLM call failed")
        raise

    raw_text = response if isinstance(response, str) else str(response)

    try:
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
        if isinstance(parsed, dict):
            parsed = _normalize_planner_payload(parsed, task_text)
        planner_response = PlannerResponse(**parsed)
    except Exception:
        logger.exception("Failed to parse planner response")
        raise

    if force_generate and planner_response.decision != "generate":
        raise ValueError(
            f"Planner returned decision='{planner_response.decision}' "
            "but force_generate was requested"
        )

    if planner_response.decision == "reuse" and planner_response.reuse_crew:
        crew_config = load_crew_config(planner_response.reuse_crew)
        return PlannerResult(
            decision="reuse",
            crew_name=planner_response.reuse_crew,
            crew_config=crew_config,
        )

    if planner_response.crew_spec is None:
        raise ValueError(
            f"Planner returned decision='{planner_response.decision}' "
            f"but no crew_spec"
        )

    spec = _repair_agent_limit(_repair_async_task_graph(planner_response.crew_spec))
    if planner_response.decision == "adapt" and planner_response.base_crew:
        base_config = load_crew_config(planner_response.base_crew)
        crew_config = _merge_adapted_crew_config(base_config, spec)
        merged_spec = _crew_config_to_payload(
            crew_config,
            name=spec.name,
            description=spec.description,
            tags=spec.tags,
            query_archetypes=spec.query_archetypes,
        )
        errors = validate_crew_spec(
            merged_spec,
            available_tools,
            available_models,
            model_concurrency,
        )
    else:
        crew_config = render_crew_dict(spec)
        errors = validate_crew_spec(
            spec,
            available_tools,
            available_models,
            model_concurrency,
        )

    if errors:
        raise ValueError(
            f"Planner generated invalid crew spec: {'; '.join(errors)}"
        )

    return PlannerResult(
        decision=planner_response.decision,
        crew_name=spec.name,
        crew_config=crew_config,
        is_new=True,
        spec=spec,
        base_crew=planner_response.base_crew,
    )
