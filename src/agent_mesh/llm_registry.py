from __future__ import annotations

import os
from typing import Any

from crewai import LLM


class LLMRegistry:
    def __init__(self, config: dict[str, Any]) -> None:
        self._defaults = config.get("defaults", {})
        self._models = config.get("models", {})
        self._cache: dict[str, LLM] = {}

    def _resolve_base_url(self) -> str:
        env_name = self._defaults.get("litellm_base_url_env", "LITELLM_BASE_URL")
        env_value = os.getenv(env_name)
        if env_value and env_value.strip():
            return env_value.strip()
        return self._defaults.get("litellm_base_url", "http://100.80.49.81:4000/v1")

    def _resolve_api_key(self) -> str:
        env_name = self._defaults.get("litellm_api_key_env", "LITELLM_API_KEY")
        env_value = os.getenv(env_name)
        if env_value and env_value.strip():
            return env_value.strip()

        default_value = str(self._defaults.get("litellm_api_key", "")).strip()
        if default_value:
            return default_value

        return "litellm-placeholder"

    def get(self, profile_name: str) -> LLM:
        if profile_name in self._cache:
            return self._cache[profile_name]

        if profile_name not in self._models:
            raise KeyError(f"Unknown model profile: {profile_name}")

        profile = self._models[profile_name]
        llm = LLM(
            model=profile["provider_model"],
            base_url=self._resolve_base_url(),
            api_key=self._resolve_api_key(),
            temperature=profile.get("temperature", 0.2),
        )
        self._cache[profile_name] = llm
        return llm
