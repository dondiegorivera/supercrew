"""Tests for runtime diagnostics in crew_builder.py."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_mesh"


def _load_crew_builder_module():
    crewai = types.ModuleType("crewai")

    class Crew:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class Process:
        sequential = "sequential"
        hierarchical = "hierarchical"

    class Task:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class LLM:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    crewai.Crew = Crew
    crewai.Process = Process
    crewai.Task = Task
    crewai.LLM = LLM
    sys.modules["crewai"] = crewai

    package_name = "agent_mesh_crew_builder_testpkg"
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(SRC_DIR)]
        sys.modules[package_name] = package

    agent_factory = types.ModuleType(f"{package_name}.agent_factory")
    agent_factory.build_agents = lambda **kwargs: {}
    sys.modules[f"{package_name}.agent_factory"] = agent_factory

    config_loader = types.ModuleType(f"{package_name}.config_loader")
    config_loader.load_effort_config = lambda: {}
    config_loader.normalize_effort = lambda effort, effort_config=None: effort or "standard"
    sys.modules[f"{package_name}.config_loader"] = config_loader

    llm_registry = types.ModuleType(f"{package_name}.llm_registry")

    class LLMRegistry:
        pass

    llm_registry.LLMRegistry = LLMRegistry
    sys.modules[f"{package_name}.llm_registry"] = llm_registry

    full_name = f"{package_name}.crew_builder"
    module_path = SRC_DIR / "crew_builder.py"
    spec = importlib.util.spec_from_file_location(full_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


MODULE = _load_crew_builder_module()


def test_format_runtime_diagnostics_lists_effort_models_and_reasoning():
    class Agent:
        def __init__(self, model, reasoning):
            self.llm = types.SimpleNamespace(model=model)
            self.reasoning = reasoning

    summary = MODULE._format_runtime_diagnostics(
        effort="standard",
        effort_overrides={"planning": False},
        process_name="sequential",
        agents={
            "researcher": Agent("local-swarm", False),
            "writer": Agent("cloud-fast", True),
        },
    )

    assert summary.startswith("[agent_mesh] effort=standard planning=false process=sequential agents=")
    assert "researcher(model=local-swarm,reasoning=false)" in summary
    assert "writer(model=cloud-fast,reasoning=true)" in summary


def test_has_unexpected_reasoning_only_flags_quick_and_standard():
    agent = types.SimpleNamespace(reasoning=True)

    assert MODULE._has_unexpected_reasoning("standard", {"a": agent}) is True
    assert MODULE._has_unexpected_reasoning("quick", {"a": agent}) is True
    assert MODULE._has_unexpected_reasoning("thorough", {"a": agent}) is False
