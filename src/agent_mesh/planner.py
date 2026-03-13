"""Planner — uses cloud LLM to select or generate crew configurations."""
from __future__ import annotations

import json
import logging
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
    """Run the planner to decide crew selection/generation."""
    handbook = load_planner_handbook()
    model_policy = load_model_policy()
    catalogs = load_catalogs()
    effort_config = load_effort_config()

    candidates_entries = registry.find_candidates(task_text, limit=5)
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
        planner_response = PlannerResponse(**parsed)
    except Exception:
        logger.exception("Failed to parse planner response")
        raise

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

    spec = planner_response.crew_spec
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

    crew_config = render_crew_dict(spec)
    return PlannerResult(
        decision=planner_response.decision,
        crew_name=spec.name,
        crew_config=crew_config,
        is_new=True,
        spec=spec,
        base_crew=planner_response.base_crew,
    )
