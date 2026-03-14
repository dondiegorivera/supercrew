"""Tests for LLM call wrapper installation and message sanitization."""
from __future__ import annotations

import importlib.util
import logging
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
    package_name = f"agent_mesh_llm_wrapper_testpkg_{uuid.uuid4().hex}"
    package = types.ModuleType(package_name)
    package.__path__ = [str(SRC_DIR)]
    sys.modules[package_name] = package

    crewai = types.ModuleType("crewai")
    crewai.LLM = llm_class
    sys.modules["crewai"] = crewai

    _load_agent_mesh_module(package_name, "compat")
    _load_agent_mesh_module(package_name, "timeout_utils")
    return _load_agent_mesh_module(package_name, "llm_wrapper")


def test_wrapper_sanitizes_system_message_order():
    class FakeLLM:
        def __init__(self, model="local-swarm", timeout=30):
            self.model = model
            self.timeout = timeout
            self.seen_messages = None

        def call(self, messages, **kwargs):
            self.seen_messages = messages
            return "ok"

    module = _load_llm_wrapper_with_fake_crewai(FakeLLM)
    module.install_llm_resilience()

    llm = FakeLLM()
    llm.call(
        [
            {"role": "user", "content": "Find events"},
            {"role": "system", "content": "Be precise"},
            {"role": "assistant", "content": "intermediate"},
            {"role": "assistant", "content": "draft"},
        ]
    )

    assert llm.seen_messages[0]["role"] == "system"
    assert llm.seen_messages[0]["content"] == "Be precise"
    assert llm.seen_messages[2]["role"] == "assistant"
    assert llm.seen_messages[2]["content"] == "intermediate\n\ndraft"


def test_wrapper_is_idempotent():
    class FakeLLM:
        def __init__(self, model="local-swarm", timeout=30):
            self.model = model
            self.timeout = timeout

        def call(self, messages, **kwargs):
            return "ok"

    module = _load_llm_wrapper_with_fake_crewai(FakeLLM)
    module.install_llm_resilience()
    wrapped_once = FakeLLM.call

    module.install_llm_resilience()

    assert FakeLLM.call is wrapped_once


def test_wrapper_adds_correlation_id(caplog):
    class FakeLLM:
        def __init__(self, model="local-swarm", timeout=30):
            self.model = model
            self.timeout = timeout

        def call(self, messages, **kwargs):
            return "ok"

    module = _load_llm_wrapper_with_fake_crewai(FakeLLM)
    module.install_llm_resilience()

    caplog.set_level(logging.INFO, logger=module.__name__)
    FakeLLM().call([{"role": "user", "content": "hello"}])

    assert any("[llm_call] id=" in record.message and "model=local-swarm" in record.message for record in caplog.records)


def test_wrapper_logs_timing(caplog):
    class FakeLLM:
        def __init__(self, model="local-swarm", timeout=30):
            self.model = model
            self.timeout = timeout

        def call(self, messages, **kwargs):
            return "ok"

    module = _load_llm_wrapper_with_fake_crewai(FakeLLM)
    module.install_llm_resilience()

    caplog.set_level(logging.INFO, logger=module.__name__)
    FakeLLM().call([{"role": "user", "content": "hello"}])

    assert any("status=ok elapsed=" in record.message for record in caplog.records)


def test_wrapper_propagates_exceptions():
    class FakeLLM:
        def __init__(self, model="local-swarm", timeout=30):
            self.model = model
            self.timeout = timeout

        def call(self, messages, **kwargs):
            raise ValueError("bad input")

    module = _load_llm_wrapper_with_fake_crewai(FakeLLM)
    module.install_llm_resilience()

    with pytest.raises(ValueError, match="bad input"):
        FakeLLM().call([{"role": "user", "content": "hello"}])


def test_wrapper_handles_string_messages():
    class FakeLLM:
        def __init__(self, model="local-swarm", timeout=30):
            self.model = model
            self.timeout = timeout
            self.seen_messages = None

        def call(self, messages, **kwargs):
            self.seen_messages = messages
            return "ok"

    module = _load_llm_wrapper_with_fake_crewai(FakeLLM)
    module.install_llm_resilience()

    llm = FakeLLM()
    llm.call("hello")

    assert llm.seen_messages == "hello"
