"""Unit tests for crew_spec validation."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "agent_mesh" / "crew_spec.py"
SPEC = importlib.util.spec_from_file_location("agent_mesh.crew_spec", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load module spec for {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

AgentSpec = MODULE.AgentSpec
CrewSpecPayload = MODULE.CrewSpecPayload
PlannerResponse = MODULE.PlannerResponse
TaskSpec = MODULE.TaskSpec
validate_crew_spec = MODULE.validate_crew_spec

TOOLS = {"searxng_search", "webpage_fetch", "pdf_fetch", "pdf_extract"}
MODELS = {"swarm", "clever", "cloud_fast"}
CONCURRENCY = {"swarm": 16, "clever": 2, "cloud_fast": 4}


def _minimal_spec(**overrides) -> CrewSpecPayload:
    defaults = dict(
        name="test_crew",
        description="A test crew",
        process="sequential",
        tags=["test"],
        query_archetypes=["test {topic}"],
        agents=[
            AgentSpec(
                name="researcher",
                role_archetype="researcher",
                role="Researcher",
                goal="Find info",
                backstory="Good at research",
                model_profile="swarm",
                tools=["searxng_search"],
            ),
            AgentSpec(
                name="analyst",
                role_archetype="analyst",
                role="Analyst",
                goal="Analyze",
                backstory="Good at analysis",
                model_profile="clever",
            ),
        ],
        tasks=[
            TaskSpec(
                name="search",
                description="Search for {topic}",
                expected_output="Results",
                agent="researcher",
            ),
            TaskSpec(
                name="analyze",
                description="Analyze the results",
                expected_output="Analysis",
                agent="analyst",
                context=["search"],
            ),
        ],
    )
    defaults.update(overrides)
    return CrewSpecPayload(**defaults)


def test_valid_spec_passes():
    spec = _minimal_spec()
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert errors == [], f"Unexpected errors: {errors}"


def test_too_few_agents():
    spec = _minimal_spec(
        agents=[
            AgentSpec(
                name="solo",
                role_archetype="researcher",
                role="Solo",
                goal="Do it all",
                backstory="Alone",
                model_profile="swarm",
            ),
        ],
        tasks=[
            TaskSpec(
                name="work",
                description="Do {topic}",
                expected_output="Done",
                agent="solo",
            ),
        ],
    )
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("Too few agents" in error for error in errors)


def test_unknown_tool():
    spec = _minimal_spec()
    spec.agents[0].tools = ["nonexistent_tool"]
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("unregistered tool" in error for error in errors)


def test_unknown_model():
    spec = _minimal_spec()
    spec.agents[0].model_profile = "nonexistent_model"
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("unknown model profile" in error for error in errors)


def test_task_references_unknown_agent():
    spec = _minimal_spec()
    spec.tasks[0].agent = "ghost"
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("unknown agent" in error for error in errors)


def test_context_cycle_detected():
    spec = _minimal_spec(
        tasks=[
            TaskSpec(
                name="task_a",
                description="Do {topic}",
                expected_output="A",
                agent="researcher",
                context=["task_b"],
            ),
            TaskSpec(
                name="task_b",
                description="Do more",
                expected_output="B",
                agent="analyst",
                context=["task_a"],
            ),
        ],
    )
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("Cycle" in error for error in errors)


def test_async_last_task_rejected():
    spec = _minimal_spec(
        tasks=[
            TaskSpec(
                name="search",
                description="Search {topic}",
                expected_output="Results",
                agent="researcher",
            ),
            TaskSpec(
                name="final",
                description="Finalize",
                expected_output="Done",
                agent="analyst",
                async_execution=True,
            ),
        ],
    )
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("no downstream sync consumer" in error for error in errors)
    assert not any("consecutive async tasks" in error for error in errors)


def test_trailing_async_block_rejected():
    spec = _minimal_spec(
        tasks=[
            TaskSpec(
                name="search",
                description="Search {topic}",
                expected_output="Results",
                agent="researcher",
            ),
            TaskSpec(
                name="branch_a",
                description="Collect branch A",
                expected_output="A",
                agent="researcher",
                async_execution=True,
            ),
            TaskSpec(
                name="branch_b",
                description="Collect branch B",
                expected_output="B",
                agent="analyst",
                async_execution=True,
            ),
        ],
    )
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("consecutive async tasks" in error for error in errors)


def test_single_trailing_async_allowed():
    spec = _minimal_spec(
        tasks=[
            TaskSpec(
                name="search",
                description="Search {topic}",
                expected_output="Results",
                agent="researcher",
            ),
            TaskSpec(
                name="final_async",
                description="Finalize {topic}",
                expected_output="Done",
                agent="analyst",
                async_execution=True,
            ),
        ],
    )
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("no downstream sync consumer" in error for error in errors)
    assert not any("consecutive async tasks" in error for error in errors)


def test_async_without_sync_consumer():
    spec = _minimal_spec(
        tasks=[
            TaskSpec(
                name="async_search",
                description="Search {topic}",
                expected_output="Results",
                agent="researcher",
                async_execution=True,
            ),
            TaskSpec(
                name="other",
                description="Something else",
                expected_output="Done",
                agent="analyst",
            ),
        ],
    )
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("no downstream sync consumer" in error for error in errors)


def test_async_context_sequential_adjacent_rejected():
    spec = _minimal_spec(
        agents=[
            AgentSpec(
                name="researcher",
                role_archetype="researcher",
                role="Researcher",
                goal="Find info",
                backstory="Good at research",
                model_profile="swarm",
            ),
            AgentSpec(
                name="verifier",
                role_archetype="auditor",
                role="Verifier",
                goal="Verify results",
                backstory="Careful verifier",
                model_profile="clever",
            ),
            AgentSpec(
                name="writer",
                role_archetype="writer",
                role="Writer",
                goal="Write output",
                backstory="Good writer",
                model_profile="clever",
            ),
        ],
        tasks=[
            TaskSpec(
                name="search_a",
                description="Search A for {topic}",
                expected_output="A",
                agent="researcher",
                async_execution=True,
            ),
            TaskSpec(
                name="verify_a",
                description="Verify A",
                expected_output="Verified",
                agent="verifier",
                context=["search_a"],
                async_execution=True,
            ),
            TaskSpec(
                name="write",
                description="Write the results",
                expected_output="Final",
                agent="writer",
                context=["verify_a"],
            ),
        ],
    )
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("sequentially adjacent async task" in error for error in errors)


def test_async_context_with_sync_separator_allowed():
    spec = _minimal_spec(
        agents=[
            AgentSpec(
                name="researcher",
                role_archetype="researcher",
                role="Researcher",
                goal="Find info",
                backstory="Good at research",
                model_profile="swarm",
            ),
            AgentSpec(
                name="verifier",
                role_archetype="auditor",
                role="Verifier",
                goal="Verify results",
                backstory="Careful verifier",
                model_profile="clever",
            ),
            AgentSpec(
                name="writer",
                role_archetype="writer",
                role="Writer",
                goal="Write output",
                backstory="Good writer",
                model_profile="clever",
            ),
        ],
        tasks=[
            TaskSpec(
                name="search_a",
                description="Search A for {topic}",
                expected_output="A",
                agent="researcher",
                async_execution=True,
            ),
            TaskSpec(
                name="merge_a",
                description="Merge A",
                expected_output="Merged",
                agent="verifier",
                context=["search_a"],
            ),
            TaskSpec(
                name="reuse_a",
                description="Reuse A",
                expected_output="Reused",
                agent="writer",
                context=["search_a"],
                async_execution=True,
            ),
            TaskSpec(
                name="publish",
                description="Publish the result",
                expected_output="Published",
                agent="verifier",
                context=["reuse_a"],
            ),
        ],
    )
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert errors == [], f"Unexpected errors: {errors}"


def test_context_references_future_task_rejected():
    spec = _minimal_spec(
        tasks=[
            TaskSpec(
                name="search",
                description="Search {topic}",
                expected_output="Results",
                agent="researcher",
                context=["analyze"],
            ),
            TaskSpec(
                name="analyze",
                description="Analyze results",
                expected_output="Analysis",
                agent="analyst",
            ),
        ],
    )
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("references future task" in error for error in errors)


def test_context_references_earlier_task_allowed():
    spec = _minimal_spec(
        tasks=[
            TaskSpec(
                name="search",
                description="Search {topic}",
                expected_output="Results",
                agent="researcher",
            ),
            TaskSpec(
                name="analyze",
                description="Analyze results",
                expected_output="Analysis",
                agent="analyst",
                context=["search"],
            ),
        ],
    )
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert errors == [], f"Unexpected errors: {errors}"


def test_hierarchical_without_manager_rejected():
    spec = _minimal_spec(process="hierarchical")
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("requires 'manager_model'" in error for error in errors)


def test_hierarchical_with_manager_passes():
    spec = _minimal_spec(process="hierarchical", manager_model="cloud_fast")
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert errors == [], f"Unexpected errors: {errors}"


def test_concurrency_exceeded():
    agents = [
        AgentSpec(
            name=f"worker_{i}",
            role_archetype="researcher",
            role=f"Worker {i}",
            goal="Search",
            backstory="Fast",
            model_profile="clever",
        )
        for i in range(4)
    ] + [
        AgentSpec(
            name="analyst",
            role_archetype="analyst",
            role="Analyst",
            goal="Merge",
            backstory="Smart",
            model_profile="clever",
        ),
    ]
    tasks = [
        TaskSpec(
            name=f"search_{i}",
            description="Search {topic}" if i == 0 else "Search more",
            expected_output="Results",
            agent=f"worker_{i}",
            async_execution=True,
        )
        for i in range(4)
    ] + [
        TaskSpec(
            name="merge",
            description="Merge results",
            expected_output="Merged",
            agent="analyst",
            context=[f"search_{i}" for i in range(4)],
        ),
    ]
    spec = _minimal_spec(agents=agents, tasks=tasks)
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("max_concurrency" in error for error in errors)


def test_no_topic_placeholder():
    spec = _minimal_spec(
        tasks=[
            TaskSpec(
                name="search",
                description="Search for stuff",
                expected_output="Results",
                agent="researcher",
            ),
            TaskSpec(
                name="analyze",
                description="Analyze the results",
                expected_output="Analysis",
                agent="analyst",
                context=["search"],
            ),
        ],
    )
    errors = validate_crew_spec(spec, TOOLS, MODELS, CONCURRENCY)
    assert any("{topic}" in error for error in errors)


def test_planner_response_reuse():
    response = PlannerResponse(decision="reuse", reuse_crew="deep_research")
    assert response.decision == "reuse"
    assert response.crew_spec is None


def test_planner_response_generate():
    spec = _minimal_spec()
    response = PlannerResponse(decision="generate", crew_spec=spec)
    assert response.decision == "generate"
    assert response.crew_spec is not None


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
