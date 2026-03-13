from __future__ import annotations

import os
from typing import Any

from .compat import patch_litellm_message_sanitizer
from .config_loader import (
    load_crew_config,
    load_models_config,
    load_routing_config,
    load_scenario_config,
    load_tools_config,
)
from .crew_builder import build_crew
from .llm_registry import LLMRegistry
from .task_router import route_task
from .tools import build_tool_registry


def _merge_inputs(base: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(base)
    if overrides:
        merged.update({key: value for key, value in overrides.items() if value is not None})
    return merged


def _resolve_template(task_text: str | None, scenario_name: str | None, explicit_template: str | None) -> str:
    if explicit_template:
        return explicit_template

    if scenario_name:
        scenario_config = load_scenario_config(scenario_name)
        template_name = scenario_config.get("crew_template")
        if template_name:
            return template_name

    if task_text:
        return route_task(task_text=task_text, routing_config=load_routing_config())

    return load_routing_config().get("defaults", {}).get("fallback_template", "research")


def run_task(
    task_text: str | None = None,
    *,
    inputs: dict[str, Any] | None = None,
    scenario_name: str | None = None,
    crew_template: str | None = None,
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

    # A CLI prompt should override scenario defaults unless TOPIC was set explicitly.
    if task_text and (not inputs or "topic" not in inputs):
        final_inputs["topic"] = task_text

    template_name = _resolve_template(
        task_text=task_text,
        scenario_name=scenario_name,
        explicit_template=crew_template,
    )

    crew_config = load_crew_config(template_name)
    crew = build_crew(config=crew_config, llms=llms, tools=tools)
    return crew.kickoff(inputs=final_inputs)


def run_from_env() -> Any:
    task_text = os.getenv("TASK_TEXT")
    scenario_name = os.getenv("SCENARIO")
    crew_template = os.getenv("CREW_TEMPLATE")
    topic = os.getenv("TOPIC")

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
    )
