"""Tests for per-call timeout fallback in llm_wrapper."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import uuid

import pytest


SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "agent_mesh"


def _load_agent_mesh_module(package_name: str, module_name: str):
    full_name = f"{package_name}.{module_name}"
    module_path = SRC_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(full_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


def _load_llm_wrapper_with_fake_crewai(llm_class: type):
    package_name = f"agent_mesh_fallback_testpkg_{uuid.uuid4().hex}"
    package = types.ModuleType(package_name)
    package.__path__ = [str(SRC_DIR)]
    sys.modules[package_name] = package

    crewai = types.ModuleType("crewai")
    crewai.LLM = llm_class
    sys.modules["crewai"] = crewai

    _load_agent_mesh_module(package_name, "compat")
    _load_agent_mesh_module(package_name, "timeout_utils")
    return _load_agent_mesh_module(package_name, "llm_wrapper")


def test_timeout_triggers_fallback():
    class Timeout(Exception):
        pass

    class FakeLLM:
        def __init__(self, model="local-swarm", timeout=5, should_timeout=False):
            self.model = model
            self.timeout = timeout
            self.should_timeout = should_timeout
            self.calls = []

        def call(self, messages, **kwargs):
            self.calls.append(messages)
            if self.should_timeout:
                raise Timeout("Request timed out.")
            return f"ok:{self.model}"

    module = _load_llm_wrapper_with_fake_crewai(FakeLLM)
    module.install_llm_resilience()

    primary = FakeLLM("local-swarm", should_timeout=True)
    fallback = FakeLLM("local-clever")

    class FakeRegistry:
        def get(self, name):
            assert name == "clever"
            return fallback

    module.configure_fallbacks(
        {
            "models": {
                "swarm": {"provider_model": "local-swarm", "fallback_model": "clever"},
                "clever": {"provider_model": "local-clever"},
            }
        },
        FakeRegistry(),
    )

    assert primary.call([{"role": "user", "content": "hello"}]) == "ok:local-clever"
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1


def test_non_timeout_error_propagates():
    class FakeLLM:
        def __init__(self, model="local-swarm", timeout=5):
            self.model = model
            self.timeout = timeout

        def call(self, messages, **kwargs):
            raise ValueError("bad request")

    module = _load_llm_wrapper_with_fake_crewai(FakeLLM)
    module.install_llm_resilience()

    with pytest.raises(ValueError, match="bad request"):
        FakeLLM().call([{"role": "user", "content": "hello"}])


def test_fallback_timeout_propagates_original():
    class Timeout(Exception):
        pass

    class FakeLLM:
        def __init__(self, model="local-swarm", timeout=5, should_timeout=False):
            self.model = model
            self.timeout = timeout
            self.should_timeout = should_timeout

        def call(self, messages, **kwargs):
            if self.should_timeout:
                raise Timeout(f"{self.model} timed out")
            return "ok"

    module = _load_llm_wrapper_with_fake_crewai(FakeLLM)
    module.install_llm_resilience()

    primary = FakeLLM("local-swarm", should_timeout=True)
    fallback = FakeLLM("local-clever", should_timeout=True)

    class FakeRegistry:
        def get(self, name):
            return fallback

    module.configure_fallbacks(
        {"models": {"swarm": {"provider_model": "local-swarm", "fallback_model": "clever"}}},
        FakeRegistry(),
    )

    with pytest.raises(Timeout, match="local-swarm timed out"):
        primary.call([{"role": "user", "content": "hello"}])


def test_no_fallback_configured_propagates():
    class Timeout(Exception):
        pass

    class FakeLLM:
        def __init__(self, model="local-clever", timeout=5):
            self.model = model
            self.timeout = timeout

        def call(self, messages, **kwargs):
            raise Timeout("Request timed out.")

    module = _load_llm_wrapper_with_fake_crewai(FakeLLM)
    module.install_llm_resilience()

    with pytest.raises(Timeout, match="Request timed out"):
        FakeLLM().call([{"role": "user", "content": "hello"}])


def test_fallback_call_gets_same_messages():
    class Timeout(Exception):
        pass

    class FakeLLM:
        def __init__(self, model="local-swarm", timeout=5, should_timeout=False):
            self.model = model
            self.timeout = timeout
            self.should_timeout = should_timeout
            self.calls = []

        def call(self, messages, **kwargs):
            self.calls.append(messages)
            if self.should_timeout:
                raise Timeout("Request timed out.")
            return "ok"

    module = _load_llm_wrapper_with_fake_crewai(FakeLLM)
    module.install_llm_resilience()

    primary = FakeLLM("local-swarm", should_timeout=True)
    fallback = FakeLLM("local-clever")

    class FakeRegistry:
        def get(self, name):
            return fallback

    module.configure_fallbacks(
        {"models": {"swarm": {"provider_model": "local-swarm", "fallback_model": "clever"}}},
        FakeRegistry(),
    )

    messages = [
        {"role": "user", "content": "hello"},
        {"role": "system", "content": "be concise"},
    ]
    primary.call(messages)

    assert fallback.calls[0][0]["role"] == "system"
    assert fallback.calls[0][1]["role"] == "user"
