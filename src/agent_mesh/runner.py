from __future__ import annotations

import logging
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
from .registry import CrewEntry, CrewRegistry
from .task_router import route_task
from .tools import build_tool_registry

logger = logging.getLogger(__name__)


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
    effort: str = "standard",
    save_name: str | None = None,
    output_format: str | None = None,
    planner_disabled: bool = False,
    force_generate: bool = False,
) -> Any:
    patch_litellm_message_sanitizer()
    models_config = load_models_config()
    tools_config = load_tools_config()
    llms = LLMRegistry(models_config)
    tools = build_tool_registry(tools_config)
    registry: CrewRegistry | None = None

    scenario_inputs: dict[str, Any] = {}
    if scenario_name:
        scenario_inputs = load_scenario_config(scenario_name).get("inputs", {})

    final_inputs = _merge_inputs(scenario_inputs, inputs)
    if task_text:
        final_inputs["task_text"] = task_text
    if output_format:
        final_inputs["output_format"] = output_format

    # A CLI prompt should override scenario defaults unless TOPIC was set explicitly.
    if task_text and (not inputs or "topic" not in inputs):
        final_inputs["topic"] = task_text

    template_name = _resolve_template(
        task_text=task_text,
        scenario_name=scenario_name,
        explicit_template=crew_template,
    )

    crew_config = None

    if not crew_template and not scenario_name and task_text and not planner_disabled:
        try:
            from datetime import date

            from .crew_renderer import save_generated_crew
            from .planner import plan_crew

            registry = CrewRegistry()
            registry.load()

            available_tools = set(tools.keys())
            available_models = set(models_config.get("models", {}).keys())
            model_concurrency = {
                name: model.get("max_concurrency", 1)
                for name, model in models_config.get("models", {}).items()
            }

            planner_result = plan_crew(
                task_text=task_text,
                effort=effort,
                output_format=str(output_format or "auto"),
                llms=llms,
                registry=registry,
                available_tools=available_tools,
                available_models=available_models,
                model_concurrency=model_concurrency,
                force_generate=force_generate,
            )

            crew_config = planner_result.crew_config
            template_name = planner_result.crew_name

            if planner_result.is_new and planner_result.spec:
                generated_name = save_name or planner_result.spec.name
                save_generated_crew(planner_result.spec, name=generated_name)
                registry.register(
                    CrewEntry(
                        name=generated_name,
                        data={
                            "source": "generated",
                            "description": planner_result.spec.description,
                            "tags": planner_result.spec.tags,
                            "query_archetypes": planner_result.spec.query_archetypes,
                            "required_tools": sorted(
                                {
                                    tool_name
                                    for agent in planner_result.spec.agents
                                    for tool_name in agent.tools
                                }
                            ),
                            "required_capabilities": [],
                            "agent_count": len(planner_result.spec.agents),
                            "process": planner_result.spec.process,
                            "created_at": date.today().isoformat(),
                            "last_used_at": None,
                            "use_count": 0,
                            "success_count": 0,
                            "failure_count": 0,
                            "human_reviewed": False,
                            "supersedes": None,
                            "superseded_by": None,
                            "base_crew": planner_result.base_crew,
                        },
                    )
                )
                registry.save()
                template_name = generated_name

        except Exception:
            if force_generate:
                raise
            logger.warning(
                "Planner failed, falling back to keyword routing",
                exc_info=True,
            )
            crew_config = None

    if crew_config is None:
        crew_config = load_crew_config(template_name)

    if registry is None:
        registry = CrewRegistry()
        registry.load()

    crew = build_crew(
        config=crew_config,
        llms=llms,
        tools=tools,
        effort=effort,
    )
    try:
        result = crew.kickoff(inputs=final_inputs)
    except Exception:
        registry.record_usage(template_name, success=False)
        registry.save()
        raise

    registry.record_usage(template_name, success=True)
    registry.save()
    return result


def run_from_env() -> Any:
    task_text = os.getenv("TASK_TEXT")
    scenario_name = os.getenv("SCENARIO")
    crew_template = os.getenv("CREW_TEMPLATE")
    topic = os.getenv("TOPIC")
    effort = os.getenv("EFFORT", "standard")
    save_name = os.getenv("CREW_SAVE_NAME")
    output_format = os.getenv("OUTPUT_FORMAT")
    planner_disabled = os.getenv("PLANNER_DISABLED", "0") in ("1", "true", "yes")
    force_generate = os.getenv("FORCE_GENERATE", "0") in ("1", "true", "yes")
    input_file = os.getenv("INPUT_FILE")

    if input_file and not task_text:
        from pathlib import Path

        input_path = Path(input_file)
        if input_path.exists():
            task_text = input_path.read_text(encoding="utf-8").strip()

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
        effort=effort,
        save_name=save_name,
        output_format=output_format,
        planner_disabled=planner_disabled,
        force_generate=force_generate,
    )
