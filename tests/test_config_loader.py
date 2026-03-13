"""Tests for config_loader new functions."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "agent_mesh" / "config_loader.py"
SPEC = importlib.util.spec_from_file_location("agent_mesh.config_loader", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load module spec for {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

load_catalogs = MODULE.load_catalogs
load_effort_config = MODULE.load_effort_config
load_model_policy = MODULE.load_model_policy
load_models_config = MODULE.load_models_config
load_registry_config = MODULE.load_registry_config


def test_effort_config_loads():
    config = load_effort_config()
    assert "levels" in config
    assert "standard" in config["levels"]
    assert "max_iter" in config["levels"]["standard"]


def test_effort_levels_complete():
    config = load_effort_config()
    for level in ("quick", "standard", "thorough", "exhaustive"):
        assert level in config["levels"], f"Missing effort level: {level}"
        entry = config["levels"][level]
        assert "max_iter" in entry
        assert "max_execution_time" in entry
        assert "max_swarm_agents" in entry


def test_model_policy_loads_as_string():
    policy = load_model_policy()
    assert isinstance(policy, str)
    assert "cloud_fast" in policy
    assert "swarm" in policy


def test_models_have_concurrency():
    config = load_models_config()
    for name, model in config["models"].items():
        assert "max_concurrency" in model, (
            f"Model '{name}' missing max_concurrency"
        )
        assert "has_vision" in model, f"Model '{name}' missing has_vision"


def test_registry_loads():
    config = load_registry_config()
    assert "crews" in config
    assert "deep_research" in config["crews"]


def test_catalogs_load():
    catalogs = load_catalogs()
    assert "role_archetypes" in catalogs
    assert "task_patterns" in catalogs
    assert "archetypes" in catalogs["role_archetypes"]
    assert "patterns" in catalogs["task_patterns"]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
