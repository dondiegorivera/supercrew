from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
import uuid


def _stringify_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
                    continue
                parts.append(str(item))
                continue
            parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()
    return str(content)


def _merge_message_group(group: list[dict[str, Any]]) -> dict[str, Any]:
    merged = dict(group[0])
    merged["content"] = "\n\n".join(
        part for part in (_stringify_content(message.get("content")) for message in group) if part
    ).strip()
    return merged


def sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not messages:
        return messages

    system_messages: list[dict[str, Any]] = []
    non_system_messages: list[dict[str, Any]] = []

    for message in messages:
        if message.get("role") == "system":
            system_messages.append(message)
            continue
        non_system_messages.append(message)

    sanitized: list[dict[str, Any]] = []
    if system_messages:
        sanitized.append(_merge_message_group(system_messages))

    pending_assistants: list[dict[str, Any]] = []

    def flush_pending() -> None:
        nonlocal pending_assistants
        if not pending_assistants:
            return
        sanitized.append(_merge_message_group(pending_assistants))
        pending_assistants = []

    for message in non_system_messages:
        role = message.get("role")
        has_tool_calls = bool(message.get("tool_calls"))
        if role == "assistant" and not has_tool_calls:
            pending_assistants.append(message)
            continue
        flush_pending()
        sanitized.append(message)

    flush_pending()
    return sanitized


def _wrap_completion_function(fn: Callable[..., Any]) -> Callable[..., Any]:
    def wrapped_completion(*args: Any, **kwargs: Any) -> Any:
        messages = kwargs.get("messages")
        if isinstance(messages, list):
            kwargs["messages"] = sanitize_messages(messages)
        debug_record = _build_debug_record(kwargs)
        try:
            result = fn(*args, **kwargs)
            _write_debug_record(debug_record | {"status": "ok", "response_preview": _preview_response(result)})
            return result
        except Exception as exc:
            _write_debug_record(
                debug_record
                | {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
            )
            raise

    return wrapped_completion


def _build_debug_record(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": str(uuid.uuid4()),
        "model": kwargs.get("model"),
        "base_url": kwargs.get("base_url"),
        "temperature": kwargs.get("temperature"),
        "tool_choice": kwargs.get("tool_choice"),
        "tools": kwargs.get("tools"),
        "messages": kwargs.get("messages"),
    }


def _preview_response(result: Any) -> Any:
    if result is None:
        return None
    if isinstance(result, dict):
        return result
    model_dump = getattr(result, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump()
        except Exception:
            return str(result)
    return str(result)


def _write_debug_record(record: dict[str, Any]) -> None:
    if os.getenv("AGENT_MESH_LLM_DEBUG", "").lower() not in {"1", "true", "yes", "on"}:
        return

    preferred_dir = Path(os.getenv("AGENT_MESH_LLM_DEBUG_DIR", "logs/llm_debug"))
    candidate_dirs = [
        preferred_dir,
        Path("/tmp/agent_mesh_llm_debug"),
    ]

    filename = f"{record['timestamp'].replace(':', '-').replace('+00:00', 'Z')}_{record['request_id']}.json"
    payload = json.dumps(record, ensure_ascii=True, indent=2)

    for debug_dir in candidate_dirs:
        try:
            debug_dir.mkdir(parents=True, exist_ok=True)
            path = debug_dir / filename
            path.write_text(payload, encoding="utf-8")
            return
        except OSError:
            continue


def patch_litellm_message_sanitizer() -> None:
    """DEPRECATED: Use llm_wrapper.install_llm_resilience() instead.

    This patches litellm.completion at the module level, which can be
    bypassed if callers capture a reference at import time. The LLM.call
    wrapper in llm_wrapper.py is the replacement.
    """
    import litellm

    if getattr(litellm, "_agent_mesh_message_patch", False):
        return

    litellm.completion = _wrap_completion_function(litellm.completion)
    if hasattr(litellm, "acompletion"):
        litellm.acompletion = _wrap_completion_function(litellm.acompletion)
    litellm._agent_mesh_message_patch = True
