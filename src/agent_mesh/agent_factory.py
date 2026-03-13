from __future__ import annotations

from typing import Any

from crewai import Agent
from crewai.tools import BaseTool

from .llm_registry import LLMRegistry


def build_agents(
    config: dict[str, Any],
    llms: LLMRegistry,
    tools: dict[str, BaseTool],
    effort_overrides: dict[str, Any] | None = None,
) -> dict[str, Agent]:
    agents: dict[str, Agent] = {}

    for name, agent_spec in config.get("agents", {}).items():
        tool_names = agent_spec.get("tools", [])
        agent_tools = [tools[tool_name] for tool_name in tool_names]

        kwargs: dict[str, Any] = {
            "role": agent_spec["role"],
            "goal": agent_spec["goal"],
            "backstory": agent_spec.get("backstory", ""),
            "llm": llms.get(agent_spec["model_profile"]),
            "tools": agent_tools,
            "verbose": agent_spec.get("verbose", True),
            "allow_delegation": agent_spec.get("allow_delegation", False),
        }

        if effort_overrides:
            if "max_iter" in effort_overrides:
                kwargs["max_iter"] = effort_overrides["max_iter"]
            if "max_execution_time" in effort_overrides:
                kwargs["max_execution_time"] = effort_overrides[
                    "max_execution_time"
                ]
            if "max_retry_limit" in effort_overrides:
                kwargs["max_retry_limit"] = effort_overrides["max_retry_limit"]
            if effort_overrides.get("reasoning"):
                kwargs["reasoning"] = True
                if "max_reasoning_attempts" in effort_overrides:
                    kwargs["max_reasoning_attempts"] = effort_overrides[
                        "max_reasoning_attempts"
                    ]

        agents[name] = Agent(**kwargs)

    return agents
