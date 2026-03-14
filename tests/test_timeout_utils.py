"""Tests for shared timeout detection utilities."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "agent_mesh" / "timeout_utils.py"
SPEC = importlib.util.spec_from_file_location("agent_mesh_timeout_utils_test", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load module spec for {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["agent_mesh_timeout_utils_test"] = MODULE
SPEC.loader.exec_module(MODULE)
is_retryable_timeout = MODULE.is_retryable_timeout


def test_retryable_timeout_detection_matches_nested_timeout():
    class Timeout(Exception):
        pass

    root = Timeout("Request timed out.")
    wrapper = RuntimeError("worker failed")
    wrapper.__cause__ = root

    assert is_retryable_timeout(wrapper) is True


def test_non_timeout_error_is_not_retryable():
    assert is_retryable_timeout(ValueError("bad input")) is False
