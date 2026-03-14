"""Tests for runner wiring after per-call resilience moved into llm_wrapper."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_mesh"


def _load_runner_module():
    package_name = "agent_mesh_runner_testpkg"
    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(SRC_DIR)]
        sys.modules[package_name] = package

    config_loader = types.ModuleType(f"{package_name}.config_loader")
    config_loader.load_crew_config = lambda name: {"name": name}
    config_loader.load_models_config = lambda: {
        "models": {
            "swarm": {"provider_model": "local-swarm", "fallback_model": "clever"},
            "clever": {"provider_model": "local-clever"},
        }
    }
    config_loader.load_routing_config = lambda: {"defaults": {"fallback_template": "research"}}
    config_loader.load_scenario_config = lambda name: {}
    config_loader.load_tools_config = lambda: {}
    sys.modules[f"{package_name}.config_loader"] = config_loader

    crew_builder = types.ModuleType(f"{package_name}.crew_builder")
    crew_builder.build_crew = lambda **kwargs: None
    sys.modules[f"{package_name}.crew_builder"] = crew_builder

    llm_wrapper = types.ModuleType(f"{package_name}.llm_wrapper")
    llm_wrapper.configure_concurrency = lambda config: None
    llm_wrapper.configure_fallbacks = lambda config, registry: None
    sys.modules[f"{package_name}.llm_wrapper"] = llm_wrapper

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

    timeout_utils = types.ModuleType(f"{package_name}.timeout_utils")
    timeout_utils.is_retryable_timeout = lambda exc: "timed out" in str(exc).lower()
    sys.modules[f"{package_name}.timeout_utils"] = timeout_utils

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


def test_run_task_configures_concurrency_and_fallbacks(monkeypatch):
    configured = {"concurrency": None, "fallbacks": None}

    class FakeCrew:
        def kickoff(self, inputs):
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

    monkeypatch.setattr(
        RUNNER,
        "configure_concurrency",
        lambda config: configured.__setitem__("concurrency", config),
    )
    monkeypatch.setattr(
        RUNNER,
        "configure_fallbacks",
        lambda config, registry: configured.__setitem__("fallbacks", (config, registry)),
    )
    monkeypatch.setattr(RUNNER, "build_crew", lambda **kwargs: FakeCrew())
    monkeypatch.setattr(RUNNER, "CrewRegistry", lambda: fake_registry)

    result = RUNNER.run_task(
        task_text="find festivals",
        crew_template="research",
        planner_disabled=True,
    )

    assert result == "ok"
    assert configured["concurrency"]["models"]["swarm"]["provider_model"] == "local-swarm"
    assert configured["fallbacks"][0]["models"]["swarm"]["fallback_model"] == "clever"
    assert fake_registry.records == [("research", True)]


def test_run_task_no_longer_retries_timeouts(monkeypatch):
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

    monkeypatch.setattr(RUNNER, "build_crew", lambda **kwargs: FakeCrew())
    monkeypatch.setattr(RUNNER, "CrewRegistry", lambda: fake_registry)

    with pytest.raises(Timeout):
        RUNNER.run_task(
            task_text="find festivals",
            crew_template="research",
            planner_disabled=True,
        )

    assert attempts["count"] == 1
    assert fake_registry.records == [("research", False)]
