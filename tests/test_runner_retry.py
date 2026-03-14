"""Tests for timeout retry handling in runner.py."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_mesh"


def _load_runner_module():
    package_name = "agent_mesh_runner_testpkg"
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(SRC_DIR)]
        sys.modules[package_name] = package

    compat = types.ModuleType(f"{package_name}.compat")
    compat.patch_litellm_message_sanitizer = lambda: None
    sys.modules[f"{package_name}.compat"] = compat

    config_loader = types.ModuleType(f"{package_name}.config_loader")
    config_loader.load_crew_config = lambda name: {"name": name}
    config_loader.load_models_config = lambda: {}
    config_loader.load_routing_config = lambda: {"defaults": {"fallback_template": "research"}}
    config_loader.load_scenario_config = lambda name: {}
    config_loader.load_tools_config = lambda: {}
    sys.modules[f"{package_name}.config_loader"] = config_loader

    crew_builder = types.ModuleType(f"{package_name}.crew_builder")
    crew_builder.build_crew = lambda **kwargs: None
    sys.modules[f"{package_name}.crew_builder"] = crew_builder

    llm_registry = types.ModuleType(f"{package_name}.llm_registry")

    class LLMRegistry:
        def __init__(self, config):
            self.config = config

    llm_registry.LLMRegistry = LLMRegistry
    sys.modules[f"{package_name}.llm_registry"] = llm_registry

    registry = types.ModuleType(f"{package_name}.registry")

    class CrewEntry:
        def __init__(self, name, data):
            self.name = name
            self.data = data

    class CrewRegistry:
        def load(self):
            return None

        def record_usage(self, name, success):
            return None

        def save(self):
            return None

    registry.CrewEntry = CrewEntry
    registry.CrewRegistry = CrewRegistry
    sys.modules[f"{package_name}.registry"] = registry

    task_router = types.ModuleType(f"{package_name}.task_router")
    task_router.route_task = lambda **kwargs: "research"
    sys.modules[f"{package_name}.task_router"] = task_router

    tools = types.ModuleType(f"{package_name}.tools")
    tools.build_tool_registry = lambda config: {}
    sys.modules[f"{package_name}.tools"] = tools

    full_name = f"{package_name}.runner"
    if full_name in sys.modules:
        del sys.modules[full_name]

    module_path = SRC_DIR / "runner.py"
    spec = importlib.util.spec_from_file_location(full_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner_module()


def test_retryable_timeout_detection_matches_nested_timeout():
    class Timeout(Exception):
        pass

    root = Timeout("Request timed out.")
    wrapper = RuntimeError("worker failed")
    wrapper.__cause__ = root

    assert RUNNER._is_retryable_timeout(wrapper) is True


def test_non_timeout_error_is_not_retryable():
    assert RUNNER._is_retryable_timeout(ValueError("bad input")) is False


def test_timeout_retry_rewrites_swarm_agents_to_fallback_model():
    config = {
        "agents": {
            "researcher": {"model_profile": "swarm"},
            "analyst": {"model_profile": "clever"},
        }
    }

    updated, changed = RUNNER._fallback_config_after_timeout(config, fallback_model="clever")

    assert changed is True
    assert updated["agents"]["researcher"]["model_profile"] == "clever"
    assert updated["agents"]["analyst"]["model_profile"] == "clever"
    assert config["agents"]["researcher"]["model_profile"] == "swarm"


def test_run_task_retries_timeout_once(monkeypatch):
    attempts = {"count": 0}

    class Timeout(Exception):
        pass

    class FakeCrew:
        def kickoff(self, inputs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise Timeout("Request timed out.")
            return "ok"

    class FakeRegistry:
        def __init__(self):
            self.records = []

        def load(self):
            return None

        def record_usage(self, name, success):
            self.records.append((name, success))

        def save(self):
            return None

    fake_registry = FakeRegistry()

    monkeypatch.setenv("AGENT_MESH_TIMEOUT_RETRIES", "1")
    monkeypatch.setattr(RUNNER, "build_crew", lambda **kwargs: FakeCrew())
    monkeypatch.setattr(RUNNER, "CrewRegistry", lambda: fake_registry)
    monkeypatch.setattr(RUNNER, "time", types.SimpleNamespace(sleep=lambda _: None))

    result = RUNNER.run_task(
        task_text="find festivals",
        crew_template="research",
        planner_disabled=True,
    )

    assert result == "ok"
    assert attempts["count"] == 2
    assert fake_registry.records == [("research", True)]


def test_run_task_records_failure_after_retry_exhausted(monkeypatch):
    attempts = {"count": 0}

    class Timeout(Exception):
        pass

    class FakeCrew:
        def kickoff(self, inputs):
            attempts["count"] += 1
            raise Timeout("Request timed out.")

    class FakeRegistry:
        def __init__(self):
            self.records = []

        def load(self):
            return None

        def record_usage(self, name, success):
            self.records.append((name, success))

        def save(self):
            return None

    fake_registry = FakeRegistry()

    monkeypatch.setenv("AGENT_MESH_TIMEOUT_RETRIES", "1")
    monkeypatch.setattr(RUNNER, "build_crew", lambda **kwargs: FakeCrew())
    monkeypatch.setattr(RUNNER, "CrewRegistry", lambda: fake_registry)
    monkeypatch.setattr(RUNNER, "time", types.SimpleNamespace(sleep=lambda _: None))

    import pytest

    with pytest.raises(Timeout):
        RUNNER.run_task(
            task_text="find festivals",
            crew_template="research",
            planner_disabled=True,
        )

    assert attempts["count"] == 2
    assert fake_registry.records == [("research", False)]


def test_run_task_retries_with_fallback_model_config(monkeypatch):
    built_models = []

    class Timeout(Exception):
        pass

    class FakeCrew:
        def __init__(self, *, should_fail):
            self.should_fail = should_fail

        def kickoff(self, inputs):
            if self.should_fail:
                raise Timeout("Request timed out.")
            return "ok"

    class FakeRegistry:
        def __init__(self):
            self.records = []

        def load(self):
            return None

        def record_usage(self, name, success):
            self.records.append((name, success))

        def save(self):
            return None

    fake_registry = FakeRegistry()
    call_count = {"value": 0}

    def build_crew(**kwargs):
        call_count["value"] += 1
        built_models.append(
            {
                name: spec["model_profile"]
                for name, spec in kwargs["config"]["agents"].items()
            }
        )
        return FakeCrew(should_fail=call_count["value"] == 1)

    monkeypatch.setenv("AGENT_MESH_TIMEOUT_RETRIES", "1")
    monkeypatch.setenv("AGENT_MESH_TIMEOUT_FALLBACK_MODEL", "clever")
    monkeypatch.setattr(RUNNER, "build_crew", build_crew)
    monkeypatch.setattr(RUNNER, "CrewRegistry", lambda: fake_registry)
    monkeypatch.setattr(RUNNER, "time", types.SimpleNamespace(sleep=lambda _: None))
    monkeypatch.setattr(
        RUNNER,
        "load_crew_config",
        lambda name: {
            "agents": {
                "researcher": {"model_profile": "swarm"},
                "writer": {"model_profile": "cloud_fast"},
            }
        },
    )

    result = RUNNER.run_task(
        task_text="find festivals",
        crew_template="research",
        planner_disabled=True,
    )

    assert result == "ok"
    assert built_models == [
        {"researcher": "swarm", "writer": "cloud_fast"},
        {"researcher": "clever", "writer": "cloud_fast"},
    ]
    assert fake_registry.records == [("research", True)]
