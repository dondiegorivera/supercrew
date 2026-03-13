"""Tests for planner payload normalization."""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_mesh"


def _ensure_crewai_stub() -> None:
    if "crewai" in sys.modules:
        return

    crewai = types.ModuleType("crewai")

    class Agent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class Crew:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class Task:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class Process:
        sequential = "sequential"
        hierarchical = "hierarchical"

    class LLM:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    crewai.Agent = Agent
    crewai.Crew = Crew
    crewai.Task = Task
    crewai.Process = Process
    crewai.LLM = LLM
    sys.modules["crewai"] = crewai

    tools_module = types.ModuleType("crewai.tools")

    class BaseTool:
        pass

    tools_module.BaseTool = BaseTool
    sys.modules["crewai.tools"] = tools_module


def _load_agent_mesh_module(module_name: str):
    _ensure_crewai_stub()

    package_name = "agent_mesh"
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(SRC_DIR)]
        sys.modules[package_name] = package

    full_name = f"{package_name}.{module_name}"
    if full_name in sys.modules:
        return sys.modules[full_name]

    module_path = SRC_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(full_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


registry_module = _load_agent_mesh_module("registry")
planner_module = _load_agent_mesh_module("planner")

CrewRegistry = registry_module.CrewRegistry
plan_crew = planner_module.plan_crew


class _FakePlannerLLM:
    def __init__(self, payload: str):
        self.payload = payload

    def call(self, messages):
        return self.payload


class _FakeLLMs:
    def __init__(self, payload: str):
        self.payload = payload

    def get(self, name: str):
        if name == planner_module.PLANNER_MODEL_PROFILE:
            return _FakePlannerLLM(self.payload)
        return f"llm:{name}"


def test_generate_payload_normalizes_aliases_and_ascii_names():
    registry = CrewRegistry()
    registry.load()

    payload = json.dumps(
        {
            "decision": "generate",
            "crew_spec": {
                "name": "trödelmarkt steinfurt finder",
                "process": "sequential",
                "tags": ["research", "events"],
                "query_archetypes": ["find flea markets in {topic}"],
                "agents": [
                    {
                        "name": "market_searcher",
                        "role": "Market Searcher",
                        "goal": "Find candidate markets",
                        "tools": ["searxng_search"],
                        "model": "swarm",
                    },
                    {
                        "name": "date_verifier",
                        "role": "Date Verifier",
                        "goal": "Verify dates and organizers",
                        "backstory": "You cross-check official sources.",
                        "tools": ["webpage_fetch"],
                        "model": "swarm",
                    },
                    {
                        "name": "location_analyst",
                        "role": "Location Analyst",
                        "goal": "Summarize city size and structure the answer",
                        "backstory": "You synthesize the findings into a final list.",
                        "tools": [],
                        "model": "clever",
                    },
                ],
                "tasks": [
                    {
                        "name": "search_trödelmarkts",
                        "description": "Find trödelmärkte for {topic}",
                        "expected_output": "A candidate list with organizer links.",
                        "agent": "market_searcher",
                    },
                    {
                        "name": "verify_market_dates",
                        "description": "Verify each market date and location",
                        "expected_output": "A verified list of market dates.",
                        "agent": "date_verifier",
                        "context": ["search_trödelmarkts"],
                    },
                    {
                        "name": "summarize_city_sizes",
                        "description": "Summarize cities and produce the final table",
                        "expected_output": "A final table with date, city, and city size.",
                        "agent": "location_analyst",
                        "context": ["verify_market_dates"],
                    },
                ],
            },
        }
    )

    result = plan_crew(
        task_text="kreis steinfurt flea markets in April and May 2026",
        effort="standard",
        llms=_FakeLLMs(payload),
        registry=registry,
        available_tools={"searxng_search", "webpage_fetch", "pdf_fetch", "pdf_extract"},
        available_models={"swarm", "clever", "cloud_fast"},
        model_concurrency={"swarm": 16, "clever": 2, "cloud_fast": 4},
        force_generate=True,
    )

    assert result.decision == "generate"
    assert result.spec is not None
    assert result.spec.name == "trodelmarkt_steinfurt_finder"
    assert result.spec.description.startswith("Generated crew for:")
    assert result.spec.agents[0].role_archetype == "market_searcher"
    assert result.spec.agents[0].model_profile == "swarm"
    assert result.spec.agents[2].model_profile == "clever"
    assert result.spec.tasks[0].name == "search_trodelmarkts"
    assert result.spec.tasks[1].context == ["search_trodelmarkts"]
    assert "search_trodelmarkts" in result.crew_config["tasks"]


def test_generate_payload_repairs_unconsumed_async_tasks():
    registry = CrewRegistry()
    registry.load()

    payload = json.dumps(
        {
            "decision": "generate",
            "crew_spec": {
                "name": "hungary_music_festivals",
                "description": "Festival research crew",
                "process": "sequential",
                "tags": ["music", "festival"],
                "query_archetypes": ["find festivals in {topic}"],
                "agents": [
                    {
                        "name": "major_finder",
                        "role_archetype": "researcher",
                        "role": "Major Finder",
                        "goal": "Find major festivals",
                        "backstory": "",
                        "model_profile": "swarm",
                        "tools": ["searxng_search"],
                    },
                    {
                        "name": "medium_finder",
                        "role_archetype": "researcher",
                        "role": "Medium Finder",
                        "goal": "Find medium festivals",
                        "backstory": "",
                        "model_profile": "swarm",
                        "tools": ["searxng_search"],
                    },
                    {
                        "name": "minor_finder",
                        "role_archetype": "researcher",
                        "role": "Minor Finder",
                        "goal": "Find minor festivals",
                        "backstory": "",
                        "model_profile": "swarm",
                        "tools": ["searxng_search"],
                    },
                    {
                        "name": "festival_writer",
                        "role_archetype": "writer",
                        "role": "Festival Writer",
                        "goal": "Merge the research into a final answer",
                        "backstory": "",
                        "model_profile": "clever",
                        "tools": [],
                    },
                ],
                "tasks": [
                    {
                        "name": "search_major_festivals",
                        "description": "Find major music festivals in {topic}",
                        "expected_output": "Major festival candidates",
                        "agent": "major_finder",
                        "async_execution": True,
                    },
                    {
                        "name": "search_medium_festivals",
                        "description": "Find medium music festivals in {topic}",
                        "expected_output": "Medium festival candidates",
                        "agent": "medium_finder",
                        "async_execution": True,
                    },
                    {
                        "name": "search_minor_festivals",
                        "description": "Find minor music festivals in {topic}",
                        "expected_output": "Minor festival candidates",
                        "agent": "minor_finder",
                        "async_execution": True,
                    },
                    {
                        "name": "merge_festival_results",
                        "description": "Merge all findings into a final festival table",
                        "expected_output": "A final table with date, location, ticket price, and major bands",
                        "agent": "festival_writer",
                    },
                ],
            },
        }
    )

    result = plan_crew(
        task_text="all music festivals in Hungary in 2026",
        effort="exhaustive",
        llms=_FakeLLMs(payload),
        registry=registry,
        available_tools={"searxng_search", "webpage_fetch", "pdf_fetch", "pdf_extract"},
        available_models={"swarm", "clever", "cloud_fast"},
        model_concurrency={"swarm": 16, "clever": 2, "cloud_fast": 4},
        force_generate=True,
    )

    assert result.spec is not None
    assert result.spec.tasks[-1].name == "merge_festival_results"
    assert result.spec.tasks[-1].context == [
        "search_major_festivals",
        "search_medium_festivals",
        "search_minor_festivals",
    ]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
