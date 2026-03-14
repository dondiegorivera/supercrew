"""Shared timeout detection utilities."""
from __future__ import annotations

RETRYABLE_ERROR_NAMES = {
    "APITimeoutError",
    "ReadTimeout",
    "Timeout",
}


def is_retryable_timeout(exc: BaseException) -> bool:
    """Check if an exception represents a retryable LLM timeout."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if type(current).__name__ in RETRYABLE_ERROR_NAMES:
            return True
        if "timed out" in str(current).lower():
            return True
        current = current.__cause__ or current.__context__
    return False
