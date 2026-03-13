from __future__ import annotations

from typing import Any

from crewai import Agent
from crewai.tools import BaseTool

from .llm_registry import LLMRegistry


def build_agents(
    config: dict[str, Any],
    llms: LLMRegistry,
    tools: dict[str, BaseTool],
) -> dict[str, Agent]:
    agents: dict[str, Agent] = {}

    for name, agent_spec in config.get("agents", {}).items():
        tool_names = agent_spec.get("tools", [])
        agent_tools = [tools[tool_name] for tool_name in tool_names]
        agents[name] = Agent(
            role=agent_spec["role"],
            goal=agent_spec["goal"],
            backstory=agent_spec.get("backstory", ""),
            llm=llms.get(agent_spec["model_profile"]),
            tools=agent_tools,
            verbose=agent_spec.get("verbose", True),
            allow_delegation=agent_spec.get("allow_delegation", False),
        )

    return agents
