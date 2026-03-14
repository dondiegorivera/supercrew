"""Tests for effort profile reasoning policy."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_mesh"


def _load_crew_builder_module():
    crewai = types.ModuleType("crewai")

    class Crew:
        pass

    class Process:
        sequential = "sequential"
        hierarchical = "hierarchical"

    class Task:
        pass

    class LLM:
        pass

    crewai.Crew = Crew
    crewai.Process = Process
    crewai.Task = Task
    crewai.LLM = LLM
    sys.modules["crewai"] = crewai

    package_name = "agent_mesh_effort_policy_testpkg"
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(SRC_DIR)]
        sys.modules[package_name] = package

    agent_factory = types.ModuleType(f"{package_name}.agent_factory")
    agent_factory.build_agents = lambda **kwargs: {}
    sys.modules[f"{package_name}.agent_factory"] = agent_factory

    config_loader = types.ModuleType(f"{package_name}.config_loader")

    def load_effort_config():
        import yaml

        return yaml.safe_load(Path("/src/supercrew/config/effort.yaml").read_text())

    config_loader.load_effort_config = load_effort_config
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


def test_thorough_disables_crewai_reasoning_but_keeps_planning():
    overrides = MODULE._resolve_effort_overrides("thorough")

    assert overrides["planning"] is True
    assert overrides["reasoning"] is False


def test_exhaustive_disables_crewai_reasoning_but_keeps_planning():
    overrides = MODULE._resolve_effort_overrides("exhaustive")

    assert overrides["planning"] is True
    assert overrides["reasoning"] is False
