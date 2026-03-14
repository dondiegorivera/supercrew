"""LLM call wrapper for sanitization, correlation, concurrency, and fallback."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any

from .timeout_utils import is_retryable_timeout

if TYPE_CHECKING:
    from .llm_registry import LLMRegistry


logger = logging.getLogger(__name__)


def _sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reorder and merge messages for OpenAI-compatible APIs."""
    from .compat import sanitize_messages

    return sanitize_messages(messages)


class ConcurrencyLimiter:
    """Per-model semaphore-based concurrency limiter."""

    def __init__(self) -> None:
        self._semaphores: dict[str, threading.Semaphore] = {}
        self._lock = threading.Lock()

    def configure(self, model_name: str, max_concurrent: int) -> None:
        if max_concurrent < 1:
            return
        with self._lock:
            if model_name not in self._semaphores:
                self._semaphores[model_name] = threading.Semaphore(max_concurrent)

    def acquire(self, model_name: str, timeout: float | None = None) -> bool:
        semaphore = self._semaphores.get(model_name)
        if semaphore is None:
            return True
        if timeout is None:
            return semaphore.acquire()
        return semaphore.acquire(timeout=timeout)

    def release(self, model_name: str) -> None:
        semaphore = self._semaphores.get(model_name)
        if semaphore is not None:
            semaphore.release()


_limiter = ConcurrencyLimiter()
_fallback_registry: dict[str, Any] = {}


def configure_concurrency(models_config: dict[str, Any]) -> None:
    """Read client_concurrency from models config and set up semaphores."""
    for name, profile in models_config.get("models", {}).items():
        provider_model = str(profile.get("provider_model", name) or name)
        client_concurrency = profile.get("client_concurrency")
        if client_concurrency is None:
            continue
        _limiter.configure(provider_model, int(client_concurrency))


def configure_fallbacks(models_config: dict[str, Any], llm_registry: "LLMRegistry") -> None:
    """Set up fallback LLM instances for models that have fallback_model."""
    _fallback_registry.clear()
    for name, profile in models_config.get("models", {}).items():
        provider_model = str(profile.get("provider_model", name) or name)
        fallback_name = profile.get("fallback_model")
        if fallback_name:
            _fallback_registry[provider_model] = llm_registry.get(str(fallback_name))


def _resolve_call_timeout(llm: Any) -> float | None:
    raw_timeout = getattr(llm, "timeout", None)
    if raw_timeout is None:
        return None
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError):
        return None
    if timeout <= 0:
        return None
    return timeout


def _build_wrapped_call(original_call: Any) -> Any:
    def wrapped_call(
        self: Any,
        messages: str | list[dict[str, Any]],
        tools: Any = None,
        callbacks: Any = None,
        available_functions: Any = None,
        **kwargs: Any,
    ) -> str | Any:
        call_id = str(uuid.uuid4())[:12]
        model_name = str(getattr(self, "model", "unknown") or "unknown")

        if isinstance(messages, list):
            messages = _sanitize_messages(messages)

        logger.info(
            "[llm_call] id=%s model=%s messages=%d",
            call_id,
            model_name,
            len(messages) if isinstance(messages, list) else 1,
        )

        wait_start = time.monotonic()
        acquired = _limiter.acquire(model_name, timeout=_resolve_call_timeout(self))
        wait_time = time.monotonic() - wait_start
        if not acquired:
            raise TimeoutError(f"Timed out waiting for concurrency slot on {model_name}")
        if wait_time > 1.0:
            logger.info(
                "[llm_call] id=%s model=%s queued=%.1fs",
                call_id,
                model_name,
                wait_time,
            )

        start = time.monotonic()
        try:
            result = original_call(
                self,
                messages,
                tools=tools,
                callbacks=callbacks,
                available_functions=available_functions,
                **kwargs,
            )
            elapsed = time.monotonic() - start
            logger.info(
                "[llm_call] id=%s model=%s status=ok elapsed=%.1fs",
                call_id,
                model_name,
                elapsed,
            )
            return result
        except Exception as exc:
            elapsed = time.monotonic() - start
            logger.warning(
                "[llm_call] id=%s model=%s status=error elapsed=%.1fs error=%s",
                call_id,
                model_name,
                elapsed,
                type(exc).__name__,
            )
            if not is_retryable_timeout(exc):
                raise

            fallback_llm = _fallback_registry.get(model_name)
            if fallback_llm is None:
                raise

            logger.warning(
                "[llm_call] id=%s model=%s fallback=%s reason=%s",
                call_id,
                model_name,
                str(getattr(fallback_llm, "model", "?") or "?"),
                type(exc).__name__,
            )
            try:
                return fallback_llm.call(
                    messages,
                    tools=tools,
                    callbacks=callbacks,
                    available_functions=available_functions,
                    **kwargs,
                )
            except Exception:
                raise exc
        finally:
            _limiter.release(model_name)

    return wrapped_call


def _install_call_wrapper_on_class(target_class: type, marker_name: str) -> None:
    """Wrap target_class.call() to sanitize messages and add resilience."""
    if getattr(target_class, marker_name, False):
        return

    original_call = getattr(target_class, "call", None)
    if not callable(original_call):
        return

    target_class.call = _build_wrapped_call(original_call)
    setattr(target_class, marker_name, True)


def _install_call_wrapper() -> None:
    """Wrap CrewAI LLM entry points to sanitize messages and add resilience."""
    from crewai import LLM

    _install_call_wrapper_on_class(LLM, "_agent_mesh_call_wrapper_installed")

    try:
        from crewai.llms.providers.openai.completion import OpenAICompletion
    except Exception:
        return

    _install_call_wrapper_on_class(
        OpenAICompletion,
        "_agent_mesh_openai_completion_wrapper_installed",
    )


def install_llm_resilience() -> None:
    """Install all LLM resilience layers. Call once at startup."""
    _install_call_wrapper()
