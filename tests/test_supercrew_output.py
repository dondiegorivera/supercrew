"""Tests for HTML-aware output saving in supercrew.py."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import types


MODULE_PATH = Path(__file__).resolve().parents[1] / "supercrew.py"
SPEC = importlib.util.spec_from_file_location("supercrew", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load module spec for {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_auto_detect_html_saves_html(tmp_path):
    result = MODULE._write_result_files(
        tmp_path,
        timestamp="20260314T120000Z",
        scenario="smoke",
        result_text="```html\n<html><body><h1>Hello</h1></body></html>\n```",
        task_text="make html",
        output_format="auto",
    )

    assert result.name.endswith(".html")
    assert (tmp_path / "latest.html").read_text(encoding="utf-8") == "<html><body><h1>Hello</h1></body></html>"
    payload = (tmp_path / "latest.json").read_text(encoding="utf-8")
    assert '"output_format": "html"' in payload


def test_explicit_html_saves_html_even_for_plain_text(tmp_path):
    result = MODULE._write_result_files(
        tmp_path,
        timestamp="20260314T120001Z",
        scenario="smoke",
        result_text="plain text but user asked for html artifact",
        task_text="make html",
        output_format="html",
    )

    assert result.name.endswith(".html")
    assert (tmp_path / "latest.html").read_text(encoding="utf-8") == "plain text but user asked for html artifact"


def test_explicit_text_skips_html_artifact(tmp_path):
    result = MODULE._write_result_files(
        tmp_path,
        timestamp="20260314T120002Z",
        scenario="smoke",
        result_text="<html><body>should stay text</body></html>",
        task_text="make text",
        output_format="text",
    )

    assert result.name.endswith(".txt")
    assert not (tmp_path / "latest.html").exists()
    payload = (tmp_path / "latest.json").read_text(encoding="utf-8")
    assert '"output_format": "text"' in payload


def test_existing_read_only_latest_files_are_replaced(tmp_path):
    latest_text = tmp_path / "latest.txt"
    latest_json = tmp_path / "latest.json"
    latest_html = tmp_path / "latest.html"
    latest_text.write_text("old text", encoding="utf-8")
    latest_json.write_text("old json", encoding="utf-8")
    latest_html.write_text("old html", encoding="utf-8")
    os.chmod(latest_text, 0o444)
    os.chmod(latest_json, 0o444)
    os.chmod(latest_html, 0o444)

    result = MODULE._write_result_files(
        tmp_path,
        timestamp="20260314T120003Z",
        scenario="smoke",
        result_text="<html><body>fresh html</body></html>",
        task_text="make html",
        output_format="html",
    )

    assert result.name.endswith(".html")
    assert latest_text.read_text(encoding="utf-8") == "<html><body>fresh html</body></html>"
    assert latest_json.read_text(encoding="utf-8").count('"output_format": "html"') == 1
    assert latest_html.read_text(encoding="utf-8") == "<html><body>fresh html</body></html>"


def test_suppress_crewai_trace_prompts_ignores_missing_crewai():
    MODULE._suppress_crewai_trace_prompts()


def test_suppress_crewai_trace_prompts_uses_crewai_hook(monkeypatch):
    sentinel = {"called": False, "value": None}

    tracing_utils = types.ModuleType("crewai.events.listeners.tracing.utils")

    def set_suppress_tracing_messages(value):
        sentinel["called"] = True
        sentinel["value"] = value

    tracing_utils.set_suppress_tracing_messages = set_suppress_tracing_messages
    monkeypatch.setitem(sys.modules, "crewai.events.listeners.tracing.utils", tracing_utils)

    MODULE._suppress_crewai_trace_prompts()

    assert sentinel == {"called": True, "value": True}
