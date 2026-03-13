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


def load_effort_config() -> dict[str, Any]:
    return load_yaml(config_path("effort.yaml"))


def load_model_policy() -> str:
    path = config_path("model_policy.yaml")
    return path.read_text(encoding="utf-8")


def load_registry_config() -> dict[str, Any]:
    path = config_path("crew_registry.yaml")
    if not path.exists():
        return {"crews": {}}
    return load_yaml(path)


def save_registry_config(data: dict[str, Any]) -> None:
    import yaml as _yaml

    path = config_path("crew_registry.yaml")
    with path.open("w", encoding="utf-8") as handle:
        _yaml.dump(data, handle, default_flow_style=False, sort_keys=False)


def load_catalogs() -> dict[str, Any]:
    catalogs_dir = CONFIG_DIR / "catalogs"
    return {
        "role_archetypes": load_yaml(catalogs_dir / "role_archetypes.yaml"),
        "task_patterns": load_yaml(catalogs_dir / "task_patterns.yaml"),
    }


def load_planner_handbook() -> str:
    path = config_path("planner_handbook.md")
    return path.read_text(encoding="utf-8")


def load_crew_config(template_name: str) -> dict[str, Any]:
    """Try config/crews/ first, then config/generated_crews/."""
    primary = config_path("crews", f"{template_name}.yaml")
    if primary.exists():
        return load_yaml(primary)
    generated = config_path("generated_crews", f"{template_name}.yaml")
    if generated.exists():
        return load_yaml(generated)
    raise FileNotFoundError(
        f"No crew config found for '{template_name}' in crews/ or generated_crews/"
    )


def load_scenario_config(name: str) -> dict[str, Any]:
    return load_yaml(config_path("scenarios", f"{name}.yaml"))
