"""Tests for LLMRegistry environment resolution."""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_mesh"


def _ensure_crewai_stub() -> None:
    if "crewai" in sys.modules:
        return

    crewai = types.ModuleType("crewai")

    class LLM:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    crewai.LLM = LLM
    sys.modules["crewai"] = crewai


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


llm_registry_module = _load_agent_mesh_module("llm_registry")
LLMRegistry = llm_registry_module.LLMRegistry


def _config() -> dict:
    return {
        "defaults": {
            "litellm_base_url_env": "LITELLM_BASE_URL",
            "litellm_base_url": "http://example-proxy:4000/v1",
            "litellm_api_key_env": "LITELLM_API_KEY",
            "litellm_api_key": "replace_me",
        },
        "models": {
            "swarm": {
                "provider_model": "openai/local-swarm",
                "temperature": 0.2,
            }
        },
    }


def test_blank_env_api_key_uses_default(monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "")
    registry = LLMRegistry(_config())

    llm = registry.get("swarm")

    assert llm.kwargs["api_key"] == "replace_me"


def test_blank_env_base_url_uses_default(monkeypatch):
    monkeypatch.setenv("LITELLM_BASE_URL", "   ")
    registry = LLMRegistry(_config())

    llm = registry.get("swarm")

    assert llm.kwargs["base_url"] == "http://example-proxy:4000/v1"


def test_explicit_env_values_win(monkeypatch):
    monkeypatch.setenv("LITELLM_API_KEY", "real-key")
    monkeypatch.setenv("LITELLM_BASE_URL", "http://live-proxy:4000/v1")
    registry = LLMRegistry(_config())

    llm = registry.get("swarm")

    assert llm.kwargs["api_key"] == "real-key"
    assert llm.kwargs["base_url"] == "http://live-proxy:4000/v1"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
