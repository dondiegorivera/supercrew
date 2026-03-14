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
            "litellm_timeout_env": "LITELLM_TIMEOUT_SECONDS",
            "litellm_timeout_seconds": 180,
        },
        "models": {
            "swarm": {
                "provider_model": "local-swarm",
                "temperature": 0.2,
                "supports_function_calling": False,
            },
            "cloud_fast": {
                "provider_model": "cloud-fast",
                "temperature": 0.2,
                "supports_function_calling": False,
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


def test_timeout_defaults_from_config(monkeypatch):
    monkeypatch.delenv("LITELLM_TIMEOUT_SECONDS", raising=False)
    registry = LLMRegistry(_config())

    llm = registry.get("swarm")

    assert llm.kwargs["timeout"] == 180


def test_timeout_env_overrides_default(monkeypatch):
    monkeypatch.setenv("LITELLM_TIMEOUT_SECONDS", "45")
    registry = LLMRegistry(_config())

    llm = registry.get("swarm")

    assert llm.kwargs["timeout"] == 45.0


def test_profile_timeout_overrides_env(monkeypatch):
    monkeypatch.setenv("LITELLM_TIMEOUT_SECONDS", "45")
    config = _config()
    config["models"]["swarm"]["timeout_seconds"] = 12
    registry = LLMRegistry(config)

    llm = registry.get("swarm")

    assert llm.kwargs["timeout"] == 12


def test_profile_can_disable_function_calling(monkeypatch):
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    registry = LLMRegistry(_config())

    llm = registry.get("swarm")

    assert callable(llm.supports_function_calling)
    assert llm.supports_function_calling() is False


def test_cloud_profile_can_disable_function_calling(monkeypatch):
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    registry = LLMRegistry(_config())

    llm = registry.get("cloud_fast")

    assert callable(llm.supports_function_calling)
    assert llm.supports_function_calling() is False


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
