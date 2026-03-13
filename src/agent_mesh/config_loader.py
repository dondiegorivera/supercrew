from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

import yaml


ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
DATA_DIR = ROOT_DIR / "data"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in config file: {path}")
    return data


def config_path(*parts: str) -> Path:
    return CONFIG_DIR.joinpath(*parts)


def _ensure_data_dir() -> None:
    """Create data/ and seed registry from config/ on first run."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    registry_path = DATA_DIR / "crew_registry.yaml"
    if not registry_path.exists():
        seed = CONFIG_DIR / "crew_registry.yaml"
        if seed.exists():
            shutil.copy2(seed, registry_path)
    (DATA_DIR / "generated_crews").mkdir(parents=True, exist_ok=True)


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
    _ensure_data_dir()
    path = DATA_DIR / "crew_registry.yaml"
    if not path.exists():
        return {"crews": {}}
    return load_yaml(path)


def save_registry_config(data: dict[str, Any]) -> None:
    _ensure_data_dir()
    path = DATA_DIR / "crew_registry.yaml"
    with path.open("w", encoding="utf-8") as handle:
        yaml.dump(data, handle, default_flow_style=False, sort_keys=False)


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
    """Try config/crews/ first, then data/generated_crews/."""
    primary = config_path("crews", f"{template_name}.yaml")
    if primary.exists():
        return load_yaml(primary)
    _ensure_data_dir()
    generated = DATA_DIR / "generated_crews" / f"{template_name}.yaml"
    if generated.exists():
        return load_yaml(generated)
    raise FileNotFoundError(
        f"No crew config found for '{template_name}' in config/crews/ or data/generated_crews/"
    )


def load_scenario_config(name: str) -> dict[str, Any]:
    return load_yaml(config_path("scenarios", f"{name}.yaml"))
