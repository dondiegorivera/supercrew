"""Tests for registry and crew_renderer."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_mesh"


def _load_agent_mesh_module(module_name: str):
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


crew_spec_module = _load_agent_mesh_module("crew_spec")
_load_agent_mesh_module("config_loader")
crew_renderer_module = _load_agent_mesh_module("crew_renderer")
registry_module = _load_agent_mesh_module("registry")

AgentSpec = crew_spec_module.AgentSpec
CrewSpecPayload = crew_spec_module.CrewSpecPayload
TaskSpec = crew_spec_module.TaskSpec
render_crew_dict = crew_renderer_module.render_crew_dict
render_crew_yaml = crew_renderer_module.render_crew_yaml
save_generated_crew = crew_renderer_module.save_generated_crew
load_crew_config = sys.modules["agent_mesh.config_loader"].load_crew_config
CrewRegistry = registry_module.CrewRegistry


def _sample_spec() -> CrewSpecPayload:
    return CrewSpecPayload(
        name="test_crew",
        description="A test crew",
        process="sequential",
        tags=["test"],
        query_archetypes=["test {topic}"],
        agents=[
            AgentSpec(
                name="researcher",
                role_archetype="researcher",
                role="Researcher",
                goal="Find info",
                backstory="Good at research",
                model_profile="swarm",
                tools=["searxng_search"],
            ),
            AgentSpec(
                name="analyst",
                role_archetype="analyst",
                role="Analyst",
                goal="Analyze",
                backstory="Good at analysis",
                model_profile="clever",
            ),
        ],
        tasks=[
            TaskSpec(
                name="search",
                description="Search for {topic}",
                expected_output="Results",
                agent="researcher",
            ),
            TaskSpec(
                name="analyze",
                description="Analyze the results",
                expected_output="Analysis",
                agent="analyst",
                context=["search"],
            ),
        ],
    )


def test_render_crew_dict_structure():
    spec = _sample_spec()
    result = render_crew_dict(spec)
    assert result["name"] == "test_crew"
    assert result["process"] == "sequential"
    assert "researcher" in result["agents"]
    assert "search" in result["tasks"]
    assert result["tasks"]["analyze"]["context"] == ["search"]


def test_render_crew_yaml_is_valid():
    import yaml

    spec = _sample_spec()
    yaml_str = render_crew_yaml(spec)
    parsed = yaml.safe_load(yaml_str)
    assert parsed["name"] == "test_crew"
    assert "agents" in parsed
    assert "tasks" in parsed


def test_registry_load_and_find():
    registry = CrewRegistry()
    registry.load()
    crews = registry.list_crews()
    assert len(crews) > 0, "Registry should have existing crews"

    candidates = registry.find_candidates("research about jazz festivals")
    assert len(candidates) > 0


def test_registry_record_usage():
    registry = CrewRegistry()
    registry.load()
    name = registry.list_crews()[0].name
    entry = registry.get(name)
    assert entry is not None
    old_count = entry.use_count
    registry.record_usage(name, success=True)
    assert entry.use_count == old_count + 1
    assert entry.success_count > 0


def test_generated_crew_round_trip():
    spec = _sample_spec()
    spec.name = "roundtrip_test"
    path = save_generated_crew(spec)
    try:
        loaded = load_crew_config("roundtrip_test")
        assert loaded["name"] == "roundtrip_test"
        assert "researcher" in loaded["agents"]
        assert "search" in loaded["tasks"]
    finally:
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
