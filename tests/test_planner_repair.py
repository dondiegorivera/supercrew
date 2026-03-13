"""Unit tests for planner output repair."""
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "agent_mesh" / "planner_repair.py"
SPEC = importlib.util.spec_from_file_location("agent_mesh.planner_repair", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load module spec for {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

repair_planner_output = MODULE.repair_planner_output


def _raw_payload() -> dict:
    return {
        "decision": "generate",
        "crew_spec": {
            "name": "festival_crew",
            "agents": [
                {
                    "name": "researcher",
                    "role": "Researcher",
                    "goal": "Find festivals",
                    "backstory": "Find festivals",
                    "model_profile": "swarm",
                    "tools": ["searxng_search"],
                    "allow_delegation": False,
                    "role_archetype": "researcher",
                }
            ],
            "tasks": [
                {
                    "name": "search_festivals",
                    "description": "Find festivals for {topic}",
                    "expected_output": "A list of festivals",
                    "agent": "researcher",
                    "context": [],
                    "async_execution": False,
                }
            ],
            "description": "festival_crew",
            "tags": [],
            "query_archetypes": [],
        },
    }


def test_model_alias_fixed():
    payload = _raw_payload()
    del payload["crew_spec"]["agents"][0]["model_profile"]
    payload["crew_spec"]["agents"][0]["model"] = "swarm"

    repaired = repair_planner_output(payload)

    assert repaired["crew_spec"]["agents"][0]["model_profile"] == "swarm"


def test_non_ascii_name_sanitized():
    payload = _raw_payload()
    payload["crew_spec"]["tasks"][0]["name"] = "search_trödelmarkts"

    repaired = repair_planner_output(payload)

    assert repaired["crew_spec"]["tasks"][0]["name"] == "search_trodelmarkts"


def test_missing_description_defaulted():
    payload = _raw_payload()
    del payload["crew_spec"]["description"]

    repaired = repair_planner_output(payload)

    assert repaired["crew_spec"]["description"] == "festival_crew"


def test_boolean_coercion():
    payload = _raw_payload()
    payload["crew_spec"]["agents"][0]["allow_delegation"] = "true"
    payload["crew_spec"]["tasks"][0]["async_execution"] = "false"

    repaired = repair_planner_output(payload)

    assert repaired["crew_spec"]["agents"][0]["allow_delegation"] is True
    assert repaired["crew_spec"]["tasks"][0]["async_execution"] is False


def test_missing_backstory_defaults_to_goal():
    payload = _raw_payload()
    del payload["crew_spec"]["agents"][0]["backstory"]

    repaired = repair_planner_output(payload)

    assert repaired["crew_spec"]["agents"][0]["backstory"] == "Find festivals"


def test_missing_role_archetype_defaults_to_name():
    payload = _raw_payload()
    del payload["crew_spec"]["agents"][0]["role_archetype"]

    repaired = repair_planner_output(payload)

    assert repaired["crew_spec"]["agents"][0]["role_archetype"] == "researcher"


def test_duplicate_names_deduplicated():
    payload = _raw_payload()
    payload["crew_spec"]["agents"].append(
        {
            "name": "researcher",
            "role": "Verifier",
            "goal": "Verify festivals",
            "model": "clever",
        }
    )
    payload["crew_spec"]["tasks"] = [
        {
            "name": "search_trödelmarkts",
            "description": "Find festivals for {topic}",
            "expected_output": "A list of festivals",
            "agent": "researcher",
        },
        {
            "name": "search_trödelmarkts",
            "description": "Verify festival details",
            "output": "Verified festival details",
            "agent": "researcher",
            "context": ["search_trödelmarkts"],
            "async": "true",
        },
    ]

    repaired = repair_planner_output(payload)

    assert repaired["crew_spec"]["agents"][0]["name"] == "researcher"
    assert repaired["crew_spec"]["agents"][1]["name"] == "researcher_2"
    assert repaired["crew_spec"]["tasks"][0]["name"] == "search_trodelmarkts"
    assert repaired["crew_spec"]["tasks"][1]["name"] == "search_trodelmarkts_2"
    assert repaired["crew_spec"]["tasks"][1]["context"] == ["search_trodelmarkts"]


def test_already_valid_input_unchanged():
    payload = _raw_payload()
    original = copy.deepcopy(payload)

    repaired = repair_planner_output(payload)

    assert repaired == original


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
