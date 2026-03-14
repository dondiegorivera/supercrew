"""Tests for planner adapt path."""
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


config_loader_module = _load_agent_mesh_module("config_loader")
_load_agent_mesh_module("crew_spec")
_load_agent_mesh_module("crew_renderer")
registry_module = _load_agent_mesh_module("registry")
planner_module = _load_agent_mesh_module("planner")
crew_builder_module = _load_agent_mesh_module("crew_builder")

CrewRegistry = registry_module.CrewRegistry
build_crew = crew_builder_module.build_crew
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


def test_adapt_research_with_added_auditor():
    registry = CrewRegistry()
    registry.load()

    payload = json.dumps(
        {
            "decision": "adapt",
            "base_crew": "research",
            "crew_spec": {
                "name": "research_with_auditor",
                "description": "Research crew with added auditing step",
                "process": "sequential",
                "tags": ["research", "audit"],
                "query_archetypes": ["research {topic} deeply"],
                "agents": [
                    {
                        "name": "auditor",
                        "role_archetype": "auditor",
                        "role": "Auditor",
                        "goal": "Check for missing candidates and weak evidence",
                        "backstory": "You verify that the research covered the important space.",
                        "model_profile": "clever",
                        "tools": ["searxng_search"],
                        "allow_delegation": False,
                    }
                ],
                "tasks": [
                    {
                        "name": "audit_research",
                        "description": "Audit the research output for {topic}",
                        "expected_output": "A short audit of missing evidence and weak claims.",
                        "agent": "auditor",
                        "context": ["analyze_research"],
                        "async_execution": False,
                    }
                ],
            },
        }
    )

    result = plan_crew(
        task_text="research jazz festivals",
        effort="standard",
        llms=_FakeLLMs(payload),
        registry=registry,
        available_tools={"searxng_search", "webpage_fetch", "pdf_fetch", "pdf_extract"},
        available_models={"swarm", "clever", "cloud_fast"},
        model_concurrency={"swarm": 16, "clever": 2, "cloud_fast": 4},
    )

    assert result.decision == "adapt"
    assert result.crew_name == "research_with_auditor"
    assert result.base_crew == "research"
    assert "researcher" in result.crew_config["agents"]
    assert "analyst" in result.crew_config["agents"]
    assert "writer" in result.crew_config["agents"]
    assert "auditor" in result.crew_config["agents"]
    assert "gather_research" in result.crew_config["tasks"]
    assert "analyze_research" in result.crew_config["tasks"]
    assert "audit_research" in result.crew_config["tasks"]
    assert result.crew_config["tasks"]["audit_research"]["context"] == ["analyze_research"]

    built = build_crew(
        config=result.crew_config,
        llms=_FakeLLMs(payload),
        tools={"searxng_search": object()},
        effort="standard",
        effort_config=config_loader_module.load_effort_config(),
    )

    assert built.kwargs["process"] == "sequential"
    assert len(built.kwargs["agents"]) == 4
    assert len(built.kwargs["tasks"]) == 4


def test_build_crew_enables_planning_with_clever_for_high_effort():
    registry = CrewRegistry()
    registry.load()

    payload = json.dumps(
        {
            "decision": "reuse",
            "reuse_crew": "research",
        }
    )

    result = plan_crew(
        task_text="research jazz festivals",
        effort="standard",
        llms=_FakeLLMs(payload),
        registry=registry,
        available_tools={"searxng_search", "webpage_fetch", "pdf_fetch", "pdf_extract"},
        available_models={"swarm", "clever", "cloud_fast"},
        model_concurrency={"swarm": 16, "clever": 2, "cloud_fast": 4},
    )

    built = build_crew(
        config=result.crew_config,
        llms=_FakeLLMs(payload),
        tools={"searxng_search": object()},
        effort="exhaustive",
        effort_config=config_loader_module.load_effort_config(),
    )

    assert built.kwargs["process"] == "sequential"
    assert built.kwargs["planning"] is True
    assert built.kwargs["planning_llm"] == "llm:clever"


def test_build_crew_no_planning_for_low_effort():
    registry = CrewRegistry()
    registry.load()

    payload = json.dumps(
        {
            "decision": "reuse",
            "reuse_crew": "research",
        }
    )

    result = plan_crew(
        task_text="research jazz festivals",
        effort="standard",
        llms=_FakeLLMs(payload),
        registry=registry,
        available_tools={"searxng_search", "webpage_fetch", "pdf_fetch", "pdf_extract"},
        available_models={"swarm", "clever", "cloud_fast"},
        model_concurrency={"swarm": 16, "clever": 2, "cloud_fast": 4},
    )

    built = build_crew(
        config=result.crew_config,
        llms=_FakeLLMs(payload),
        tools={"searxng_search": object()},
        effort="standard",
        effort_config=config_loader_module.load_effort_config(),
    )

    assert built.kwargs["process"] == "sequential"
    assert "planning" not in built.kwargs


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
