from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in config file: {path}")
    return data


def config_path(*parts: str) -> Path:
    return CONFIG_DIR.joinpath(*parts)


def load_models_config() -> dict[str, Any]:
    return load_yaml(config_path("models.yaml"))


def load_tools_config() -> dict[str, Any]:
    return load_yaml(config_path("tools.yaml"))


def load_routing_config() -> dict[str, Any]:
    return load_yaml(config_path("routing.yaml"))


def load_crew_config(template_name: str) -> dict[str, Any]:
    return load_yaml(config_path("crews", f"{template_name}.yaml"))


def load_scenario_config(name: str) -> dict[str, Any]:
    return load_yaml(config_path("scenarios", f"{name}.yaml"))
