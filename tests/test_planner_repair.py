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


def test_html_output_adds_final_html_hints():
    payload = _raw_payload()
    payload["crew_spec"]["agents"][0]["tools"] = []
    payload["crew_spec"]["tasks"][0]["expected_output"] = "A polished deliverable"

    repaired = repair_planner_output(payload, output_format="html")

    agent = repaired["crew_spec"]["agents"][0]
    task = repaired["crew_spec"]["tasks"][0]
    assert "html" in repaired["crew_spec"]["tags"]
    assert agent["role_archetype"] == "writer"
    assert agent["role"] == "HTML Content Writer"
    assert "html" in agent["goal"].lower()
    assert "html" in agent["backstory"].lower()
    assert "standalone valid html" in task["description"].lower()
    assert "html" in task["expected_output"].lower()


def test_broad_verify_task_gets_search_context_and_becomes_sync():
    payload = {
        "decision": "generate",
        "crew_spec": {
            "name": "festival_crew",
            "description": "festival_crew",
            "tags": [],
            "query_archetypes": [],
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
                },
                {
                    "name": "verifier",
                    "role": "Verifier",
                    "goal": "Verify festival details",
                    "backstory": "Verify official details",
                    "model_profile": "swarm",
                    "tools": ["searxng_search", "webpage_fetch"],
                    "allow_delegation": False,
                    "role_archetype": "deep_researcher",
                },
            ],
            "tasks": [
                {
                    "name": "search_festivals",
                    "description": "Search for all music festivals in Hungary 2026",
                    "expected_output": "List of all festivals and candidate events",
                    "agent": "researcher",
                    "context": [],
                    "async_execution": True,
                },
                {
                    "name": "verify_festival_details",
                    "description": "Verify ticket prices and lineup from official sources",
                    "expected_output": "Verified festival details from official sources",
                    "agent": "verifier",
                    "context": [],
                    "async_execution": True,
                },
            ],
        },
    }

    repaired = repair_planner_output(payload)

    verify_task = repaired["crew_spec"]["tasks"][1]
    assert verify_task["async_execution"] is False
    assert verify_task["context"] == ["search_festivals"]


def test_missing_topic_placeholder_is_added_to_first_task():
    payload = _raw_payload()
    payload["crew_spec"]["tasks"][0]["description"] = "Find festivals in Hungary"

    repaired = repair_planner_output(payload)

    assert repaired["crew_spec"]["tasks"][0]["description"].endswith("for {topic}")


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
