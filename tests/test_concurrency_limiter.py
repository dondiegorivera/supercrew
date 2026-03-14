"""Tests for per-model concurrency limiting in llm_wrapper."""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
import sys
import threading
import time
import types
import uuid


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
    package_name = f"agent_mesh_concurrency_testpkg_{uuid.uuid4().hex}"
    package = types.ModuleType(package_name)
    package.__path__ = [str(SRC_DIR)]
    sys.modules[package_name] = package

    crewai = types.ModuleType("crewai")
    crewai.LLM = llm_class
    sys.modules["crewai"] = crewai

    _load_agent_mesh_module(package_name, "compat")
    _load_agent_mesh_module(package_name, "timeout_utils")
    return _load_agent_mesh_module(package_name, "llm_wrapper")


def test_semaphore_limits_concurrent_calls():
    entered = threading.Event()
    release = threading.Event()
    active = {"count": 0, "max": 0}
    lock = threading.Lock()

    class FakeLLM:
        def __init__(self, model="local-swarm", timeout=5):
            self.model = model
            self.timeout = timeout

        def call(self, messages, **kwargs):
            with lock:
                active["count"] += 1
                active["max"] = max(active["max"], active["count"])
                if active["count"] == 2:
                    entered.set()
            release.wait(timeout=2)
            with lock:
                active["count"] -= 1
            return "ok"

    module = _load_llm_wrapper_with_fake_crewai(FakeLLM)
    module.install_llm_resilience()
    module.configure_concurrency({"models": {"swarm": {"provider_model": "local-swarm", "client_concurrency": 2}}})

    llm = FakeLLM()
    threads = [
        threading.Thread(target=llm.call, args=([{"role": "user", "content": f"msg-{index}"}],))
        for index in range(3)
    ]
    for thread in threads:
        thread.start()

    entered.wait(timeout=1)
    time.sleep(0.1)

    assert active["max"] == 2

    release.set()
    for thread in threads:
        thread.join(timeout=2)


def test_unconfigured_model_is_unlimited():
    active = {"count": 0, "max": 0}
    lock = threading.Lock()
    release = threading.Event()

    class FakeLLM:
        def __init__(self, model="local-swarm", timeout=5):
            self.model = model
            self.timeout = timeout

        def call(self, messages, **kwargs):
            with lock:
                active["count"] += 1
                active["max"] = max(active["max"], active["count"])
            release.wait(timeout=1)
            with lock:
                active["count"] -= 1
            return "ok"

    module = _load_llm_wrapper_with_fake_crewai(FakeLLM)
    module.install_llm_resilience()

    llm = FakeLLM()
    threads = [
        threading.Thread(target=llm.call, args=([{"role": "user", "content": f"msg-{index}"}],))
        for index in range(3)
    ]
    for thread in threads:
        thread.start()

    time.sleep(0.1)
    release.set()
    for thread in threads:
        thread.join(timeout=2)

    assert active["max"] == 3


def test_configure_is_idempotent():
    class FakeLLM:
        def __init__(self, model="local-swarm", timeout=5):
            self.model = model
            self.timeout = timeout

        def call(self, messages, **kwargs):
            return "ok"

    module = _load_llm_wrapper_with_fake_crewai(FakeLLM)
    module.configure_concurrency({"models": {"swarm": {"provider_model": "local-swarm", "client_concurrency": 2}}})
    semaphore = module._limiter._semaphores["local-swarm"]

    module.configure_concurrency({"models": {"swarm": {"provider_model": "local-swarm", "client_concurrency": 4}}})

    assert module._limiter._semaphores["local-swarm"] is semaphore


def test_release_after_exception():
    class FakeLLM:
        def __init__(self, model="local-swarm", timeout=5):
            self.model = model
            self.timeout = timeout
            self.calls = 0

        def call(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ValueError("boom")
            return "ok"

    module = _load_llm_wrapper_with_fake_crewai(FakeLLM)
    module.install_llm_resilience()
    module.configure_concurrency({"models": {"swarm": {"provider_model": "local-swarm", "client_concurrency": 1}}})

    llm = FakeLLM()
    try:
        llm.call([{"role": "user", "content": "first"}])
    except ValueError:
        pass

    assert llm.call([{"role": "user", "content": "second"}]) == "ok"


def test_queue_wait_time_logged(caplog):
    release = threading.Event()

    class FakeLLM:
        def __init__(self, model="local-swarm", timeout=5):
            self.model = model
            self.timeout = timeout

        def call(self, messages, **kwargs):
            release.wait(timeout=2)
            return "ok"

    module = _load_llm_wrapper_with_fake_crewai(FakeLLM)
    module.install_llm_resilience()
    module.configure_concurrency({"models": {"swarm": {"provider_model": "local-swarm", "client_concurrency": 1}}})

    caplog.set_level(logging.INFO, logger=module.__name__)
    llm = FakeLLM()

    holder = threading.Thread(target=llm.call, args=([{"role": "user", "content": "hold"}],))
    holder.start()
    time.sleep(0.1)
    waiter = threading.Thread(target=llm.call, args=([{"role": "user", "content": "wait"}],))
    waiter.start()
    time.sleep(1.2)
    release.set()
    holder.join(timeout=2)
    waiter.join(timeout=2)

    assert any("queued=" in record.message for record in caplog.records)
