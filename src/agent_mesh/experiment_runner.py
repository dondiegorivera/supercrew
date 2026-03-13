from __future__ import annotations

from typing import Any

from .runner import run_task


def run_named_scenarios(task_text: str, scenario_names: list[str]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for scenario_name in scenario_names:
        results[scenario_name] = run_task(task_text=task_text, scenario_name=scenario_name)
    return results
