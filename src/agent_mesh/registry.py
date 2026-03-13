"""Crew registry — tracks all crews (manual and generated) with metadata."""
from __future__ import annotations

from datetime import date
import shutil
from pathlib import Path
from typing import Any

from .config_loader import CONFIG_DIR, DATA_DIR, load_registry_config, save_registry_config


class CrewEntry:
    """In-memory representation of one registry entry."""

    def __init__(self, name: str, data: dict[str, Any]) -> None:
        self.name = name
        self.source: str = data.get("source", "manual")
        self.description: str = data.get("description", "")
        self.tags: list[str] = data.get("tags", [])
        self.query_archetypes: list[str] = data.get("query_archetypes", [])
        self.required_tools: list[str] = data.get("required_tools", [])
        self.required_capabilities: list[str] = data.get(
            "required_capabilities", []
        )
        self.agent_count: int = data.get("agent_count", 0)
        self.process: str = data.get("process", "sequential")
        self.use_count: int = data.get("use_count", 0)
        self.success_count: int = data.get("success_count", 0)
        self.failure_count: int = data.get("failure_count", 0)
        self.human_reviewed: bool = data.get("human_reviewed", False)
        self.created_at: str = data.get("created_at", "")
        self.last_used_at: str | None = data.get("last_used_at")
        self.supersedes: str | None = data.get("supersedes")
        self.superseded_by: str | None = data.get("superseded_by")
        self.base_crew: str | None = data.get("base_crew")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "description": self.description,
            "tags": self.tags,
            "query_archetypes": self.query_archetypes,
            "required_tools": self.required_tools,
            "required_capabilities": self.required_capabilities,
            "agent_count": self.agent_count,
            "process": self.process,
            "use_count": self.use_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "human_reviewed": self.human_reviewed,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
            "base_crew": self.base_crew,
        }

    def summary_for_planner(self) -> str:
        """Short text summary suitable for inclusion in a planner prompt."""
        return (
            f"- {self.name}: {self.description} "
            f"[tags: {', '.join(self.tags)}] "
            f"[agents: {self.agent_count}, process: {self.process}] "
            f"[tools: {', '.join(self.required_tools) or 'none'}] "
            f"[uses: {self.use_count}, success_rate: "
            f"{self.success_count}/{self.use_count if self.use_count else '?'}] "
            f"[reviewed: {self.human_reviewed}]"
        )


class CrewRegistry:
    """Load, query, and persist the crew registry."""

    def __init__(self) -> None:
        self._crews: dict[str, CrewEntry] = {}

    def load(self) -> None:
        raw = load_registry_config()
        self._crews = {
            name: CrewEntry(name, data)
            for name, data in raw.get("crews", {}).items()
        }

    def save(self) -> None:
        data = {"crews": {name: entry.to_dict() for name, entry in self._crews.items()}}
        save_registry_config(data)

    def list_crews(self) -> list[CrewEntry]:
        return list(self._crews.values())

    def get(self, name: str) -> CrewEntry | None:
        return self._crews.get(name)

    def register(self, entry: CrewEntry) -> None:
        self._crews[entry.name] = entry

    def record_usage(self, name: str, success: bool) -> None:
        entry = self._crews.get(name)
        if not entry:
            return
        entry.use_count += 1
        if success:
            entry.success_count += 1
        else:
            entry.failure_count += 1
        entry.last_used_at = date.today().isoformat()

    def promote(self, name: str) -> Path | None:
        """Copy a generated crew to config/crews/ and mark human_reviewed."""
        entry = self._crews.get(name)
        if not entry or entry.source != "generated":
            return None

        src = DATA_DIR / "generated_crews" / f"{name}.yaml"
        dst = CONFIG_DIR / "crews" / f"{name}.yaml"
        if not src.exists():
            return None

        shutil.copy2(src, dst)
        entry.source = "manual"
        entry.human_reviewed = True
        return dst

    def find_candidates(
        self,
        task_text: str,
        limit: int = 5,
    ) -> list[CrewEntry]:
        """Score and rank crews by simple tag/keyword overlap with task text.

        Returns the top `limit` matches sorted by score descending.
        Prefers human_reviewed crews over generated ones.
        """
        lowered = task_text.lower()
        scored: list[tuple[float, CrewEntry]] = []

        for entry in self._crews.values():
            if entry.superseded_by:
                continue

            score = 0.0
            for tag in entry.tags:
                if tag.lower() in lowered:
                    score += 1.0

            for archetype in entry.query_archetypes:
                tokens = archetype.lower().replace("{", "").replace("}", "").split()
                matches = sum(1 for token in tokens if token in lowered)
                score += matches * 0.5

            if entry.human_reviewed:
                score += 0.5

            if entry.use_count > 0:
                score += (entry.success_count / entry.use_count) * 0.5

            scored.append((score, entry))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for _, entry in scored[:limit]]
