# Resilience Sprints — Transport-Layer LLM Resilience

Reference: `docs/DECISIONS.md` ADR-001, `docs/specs/architecture.md`

These sprints replace the current monkey-patch approach to LLM integration
(`compat.py` patching `litellm.completion`) with a structural solution that
intercepts at the CrewAI `LLM.call()` level. See ADR-001 for full rationale.

---

## Phase R — LLM Call Resilience

### r-s01 — LLM Call Wrapper (message sanitization + request correlation)

**Branch:** `sprint/r-s01-llm-call-wrapper`
**Depends on:** nothing
**Priority:** Critical — root cause of recurring "System message must be at the beginning" errors

#### Goal

Replace the `litellm.completion` monkey-patch with a `crewai.LLM.call()` class-level
wrapper that sanitizes messages and logs request correlation data. After this sprint,
message ordering errors cannot occur regardless of CrewAI's internal routing.

#### Why LLM.call and not litellm.completion

The current approach in `compat.py` patches `litellm.completion` via
`litellm.completion = _wrap_completion_function(litellm.completion)`. This only
works if callers access the function through the module attribute at call time.
If CrewAI does `from litellm import completion` at import time, the local
reference bypasses the patch. Since `_apply_crewai_capability_overrides()` in
`supercrew.py` imports CrewAI modules (line 84-86) before `run_task()` calls
`patch_litellm_message_sanitizer()` (runner.py line 115), any import-time
references are already captured.

`crewai.LLM.call()` is the single Python-level entry point for ALL LLM
invocations from CrewAI. Wrapping the class method avoids import-order
sensitivity entirely.

#### File to create: `src/agent_mesh/llm_wrapper.py`

```python
"""LLM call wrapper — message sanitization, correlation, and timing.

This module wraps crewai.LLM.call() at the class level to provide:
1. Message sanitization (system message ordering, consecutive merging)
2. Request correlation IDs for end-to-end tracing
3. Per-call timing logs
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Union

logger = logging.getLogger(__name__)


def _sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reorder and merge messages for OpenAI-compatible APIs.

    Rules:
    1. All system messages are merged into ONE and placed first.
    2. Consecutive assistant messages (without tool_calls) are merged.
    """
    # Reuse the existing sanitize_messages logic from compat.py.
    # Import here to keep the function self-contained.
    from .compat import sanitize_messages
    return sanitize_messages(messages)


def _install_call_wrapper() -> None:
    """Wrap crewai.LLM.call() to sanitize messages and add correlation."""
    from crewai import LLM

    if getattr(LLM, "_agent_mesh_call_wrapper_installed", False):
        return

    original_call = LLM.call

    def wrapped_call(
        self: Any,
        messages: Union[str, list[dict[str, str]]],
        tools: Any = None,
        callbacks: Any = None,
        available_functions: Any = None,
        **kwargs: Any,
    ) -> Union[str, Any]:
        call_id = str(uuid.uuid4())[:12]
        model_name = str(getattr(self, "model", "unknown"))

        # Sanitize message list
        if isinstance(messages, list):
            messages = _sanitize_messages(messages)

        logger.info(
            "[llm_call] id=%s model=%s messages=%d",
            call_id,
            model_name,
            len(messages) if isinstance(messages, list) else 1,
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
            raise

    LLM.call = wrapped_call
    LLM._agent_mesh_call_wrapper_installed = True


def install_llm_resilience() -> None:
    """Install all LLM resilience layers. Call once at startup."""
    _install_call_wrapper()
```

#### Changes to `supercrew.py`

Replace the current startup sequence. The wrapper must be installed BEFORE any
CrewAI LLM instances are created, but AFTER crewai is importable.

**Current code (lines 218-223):**
```python
def main() -> None:
    from agent_mesh.runner import run_from_env

    _apply_crewai_capability_overrides()
    _suppress_crewai_trace_prompts()
    result = run_from_env()
```

**New code:**
```python
def main() -> None:
    from agent_mesh.llm_wrapper import install_llm_resilience
    from agent_mesh.runner import run_from_env

    install_llm_resilience()
    _apply_crewai_capability_overrides()
    _suppress_crewai_trace_prompts()
    result = run_from_env()
```

#### Changes to `src/agent_mesh/runner.py`

Remove the `patch_litellm_message_sanitizer()` call from `run_task()`. The
wrapper installed in `supercrew.py:main()` now handles this. Keep the import
and function in `compat.py` for now — it still provides `sanitize_messages()`
which the new wrapper calls.

**Line 115 — remove:**
```python
    patch_litellm_message_sanitizer()
```

**Line 9 — remove unused import:**
```python
from .compat import patch_litellm_message_sanitizer
```

#### Changes to `src/agent_mesh/compat.py`

Keep `sanitize_messages()` and its helper functions (they are reused by the
new wrapper). Mark `patch_litellm_message_sanitizer()` as deprecated with a
docstring note. It can be removed in a future cleanup sprint.

Add to the function docstring:
```python
def patch_litellm_message_sanitizer() -> None:
    """DEPRECATED: Use llm_wrapper.install_llm_resilience() instead.

    This patches litellm.completion at the module level, which can be
    bypassed if callers capture a reference at import time. The LLM.call
    wrapper in llm_wrapper.py is the replacement.
    """
```

#### Tests: `tests/test_llm_call_wrapper.py`

```python
"""Tests for LLM call wrapper installation and message sanitization."""

def test_wrapper_sanitizes_system_message_order():
    """Messages with system after user should be reordered."""
    # Create a mock LLM, install wrapper, call with bad message order,
    # verify the messages passed to the original call have system first.

def test_wrapper_is_idempotent():
    """Installing the wrapper twice should not double-wrap."""

def test_wrapper_adds_correlation_id(caplog):
    """Log output should contain call ID and model name."""

def test_wrapper_logs_timing(caplog):
    """Log output should contain elapsed time."""

def test_wrapper_propagates_exceptions():
    """Exceptions from the original call should propagate unchanged."""

def test_wrapper_handles_string_messages():
    """String message input (not list) should pass through without error."""
```

#### Verification

```bash
python -m pytest tests/test_llm_call_wrapper.py -v
python -m pytest tests/ -v  # all existing tests still pass
```

Verify manually that a crew run produces log lines like:
```
[llm_call] id=a1b2c3d4e5f6 model=local-swarm messages=3
[llm_call] id=a1b2c3d4e5f6 model=local-swarm status=ok elapsed=4.2s
```

#### Do NOT

- Do not delete `compat.py` — `sanitize_messages()` is still used
- Do not change the sanitization logic itself — only the interception point
- Do not add concurrency control in this sprint — that is r-s02

---

### r-s02 — Per-Model Concurrency Limiter

**Branch:** `sprint/r-s02-concurrency-limiter`
**Depends on:** r-s01

#### Goal

Add a `threading.Semaphore` per model profile that limits concurrent in-flight
LLM requests. This prevents vLLM backend saturation (100% KV cache, queued
requests) by applying client-side backpressure.

#### Design

Each model profile gets a semaphore with a capacity equal to a new config field
`client_concurrency` in `config/models.yaml`. When the semaphore is full,
additional requests block client-side until a slot opens. This is strictly
better than sending all requests to vLLM and having them queue/timeout there,
because:
- Client-side queuing is free (no GPU memory consumed)
- Timeout clocks don't tick while waiting for a slot
- Backend KV cache stays under control

#### Changes to `config/models.yaml`

Add `client_concurrency` to each model profile. This is the maximum number of
simultaneous HTTP requests the client will send to this model. It should be
**lower** than `max_concurrency` (which is a planner constraint on async agent
count).

```yaml
models:
  swarm:
    provider_model: local-swarm
    # ... existing fields ...
    max_concurrency: 16        # planner: max async agents
    client_concurrency: 4      # runtime: max simultaneous HTTP requests
    # Start conservative. Increase after measuring actual vLLM throughput.

  clever:
    provider_model: local-clever
    # ... existing fields ...
    max_concurrency: 2
    client_concurrency: 2      # clever has dedicated capacity

  cloud_fast:
    provider_model: cloud-fast
    # ... existing fields ...
    max_concurrency: 4
    client_concurrency: 4      # cloud has elastic capacity
```

**Rationale for swarm client_concurrency=4:** Your vLLM logs show saturation
at 5-6 concurrent requests with KV cache hitting 100%. Starting at 4 keeps
headroom. Adjust up/down based on observed behavior.

#### Changes to `src/agent_mesh/llm_wrapper.py`

Add a `ConcurrencyLimiter` class and integrate it into the call wrapper:

```python
import threading
from typing import Any


class ConcurrencyLimiter:
    """Per-model semaphore-based concurrency limiter."""

    def __init__(self) -> None:
        self._semaphores: dict[str, threading.Semaphore] = {}
        self._lock = threading.Lock()

    def configure(self, model_name: str, max_concurrent: int) -> None:
        with self._lock:
            if model_name not in self._semaphores:
                self._semaphores[model_name] = threading.Semaphore(max_concurrent)

    def acquire(self, model_name: str, timeout: float | None = None) -> bool:
        sem = self._semaphores.get(model_name)
        if sem is None:
            return True  # no limit configured
        return sem.acquire(timeout=timeout)

    def release(self, model_name: str) -> None:
        sem = self._semaphores.get(model_name)
        if sem is not None:
            sem.release()


# Module-level singleton
_limiter = ConcurrencyLimiter()


def configure_concurrency(models_config: dict[str, Any]) -> None:
    """Read client_concurrency from models config and set up semaphores."""
    for name, profile in models_config.get("models", {}).items():
        provider_model = str(profile.get("provider_model", name))
        client_concurrency = profile.get("client_concurrency")
        if client_concurrency is not None:
            _limiter.configure(provider_model, int(client_concurrency))
```

Update the `wrapped_call` from r-s01 to acquire/release the semaphore:

```python
def wrapped_call(self, messages, **kwargs):
    call_id = str(uuid.uuid4())[:12]
    model_name = str(getattr(self, "model", "unknown"))

    if isinstance(messages, list):
        messages = _sanitize_messages(messages)

    # Wait for concurrency slot
    wait_start = time.monotonic()
    acquired = _limiter.acquire(model_name, timeout=timeout_from_self_or_default)
    wait_time = time.monotonic() - wait_start
    if not acquired:
        raise TimeoutError(
            f"Timed out waiting for concurrency slot on {model_name}"
        )
    if wait_time > 1.0:
        logger.info(
            "[llm_call] id=%s model=%s queued=%.1fs",
            call_id, model_name, wait_time,
        )

    try:
        # ... existing call + timing logic ...
    finally:
        _limiter.release(model_name)
```

#### Changes to `src/agent_mesh/runner.py`

After loading models_config, configure the concurrency limiter:

```python
from .llm_wrapper import configure_concurrency

def run_task(...):
    # ... existing code ...
    models_config = load_models_config()
    configure_concurrency(models_config)  # <-- add this line
    # ... rest of function ...
```

#### Tests: `tests/test_concurrency_limiter.py`

```python
def test_semaphore_limits_concurrent_calls():
    """With client_concurrency=2, third concurrent call should block."""

def test_unconfigured_model_is_unlimited():
    """Models without client_concurrency should not block."""

def test_configure_is_idempotent():
    """Calling configure twice for the same model should not reset the semaphore."""

def test_release_after_exception():
    """Semaphore is released even if the LLM call raises."""

def test_queue_wait_time_logged(caplog):
    """When a call waits >1s for a slot, a log line should appear."""
```

#### Verification

```bash
python -m pytest tests/test_concurrency_limiter.py -v
python -m pytest tests/ -v
```

Manual verification: run a crew with 6+ swarm agents. Observe that:
- At most 4 concurrent requests hit LiteLLM (check LiteLLM request logs)
- vLLM KV cache stays below 80%
- Crew still completes (requests queue, not fail)

#### Do NOT

- Do not change `max_concurrency` values — those are planner constraints (sprint r-s03)
- Do not add model fallback logic yet — that is r-s03
- Do not make the semaphore timeout configurable via env var in this sprint —
  keep it simple, derive from the model's `timeout_seconds`

---

### r-s03 — Per-Call Circuit Breaker with Model Fallback

**Branch:** `sprint/r-s03-circuit-breaker`
**Depends on:** r-s02

#### Goal

When an individual LLM call times out, retry it once on a fallback model
transparently. This replaces the current crew-level retry in `runner.py` with
a per-call mechanism that preserves all completed work.

#### Design

The circuit breaker logic lives in the `wrapped_call` from r-s01/r-s02.
When a call to model X fails with a retryable timeout:
1. Log the failure with call ID and model
2. Look up a fallback model from config
3. Retry the same messages on the fallback model
4. If the fallback also fails, propagate the original exception

This is transparent to CrewAI — it just sees a successful (but slower) LLM
response.

#### Changes to `config/models.yaml`

Add `fallback_model` to profiles that need it:

```yaml
models:
  swarm:
    # ... existing fields ...
    fallback_model: clever    # on timeout, retry on clever

  clever:
    # ... existing fields ...
    fallback_model: null      # no fallback — clever is already the fallback

  cloud_fast:
    # ... existing fields ...
    fallback_model: null      # cloud failures should not fall back to local
```

#### Changes to `src/agent_mesh/llm_wrapper.py`

Add fallback registry and update the call wrapper:

```python
# Fallback configuration (model_name → fallback LLM instance)
_fallback_registry: dict[str, Any] = {}  # provider_model → crewai.LLM


def configure_fallbacks(
    models_config: dict[str, Any],
    llm_registry: "LLMRegistry",
) -> None:
    """Set up fallback LLM instances for models that have fallback_model."""
    for name, profile in models_config.get("models", {}).items():
        provider_model = str(profile.get("provider_model", name))
        fallback_name = profile.get("fallback_model")
        if fallback_name:
            _fallback_registry[provider_model] = llm_registry.get(fallback_name)
```

In `wrapped_call`, after the primary call fails with a retryable timeout:

```python
def wrapped_call(self, messages, **kwargs):
    # ... sanitization, concurrency acquire ...
    try:
        result = original_call(self, messages, **kwargs)
        return result
    except Exception as exc:
        if not _is_retryable_timeout(exc):
            raise

        fallback_llm = _fallback_registry.get(model_name)
        if fallback_llm is None:
            raise

        logger.warning(
            "[llm_call] id=%s model=%s fallback=%s reason=%s",
            call_id, model_name,
            getattr(fallback_llm, "model", "?"),
            type(exc).__name__,
        )
        # Retry on fallback — this goes through wrapped_call again
        # (since fallback_llm is also a crewai.LLM instance)
        return fallback_llm.call(messages, **kwargs)
    finally:
        _limiter.release(model_name)
```

Import `_is_retryable_timeout` from `runner.py` (or move it to a shared
utility module — see below).

#### Changes to `src/agent_mesh/runner.py`

**Simplify the retry loop.** The per-call circuit breaker now handles
individual timeouts transparently. The crew-level retry loop becomes a
simpler single-attempt with error reporting:

Remove the timeout retry loop (lines 228-265). Replace with:

```python
    from .llm_wrapper import configure_fallbacks

    configure_fallbacks(models_config, llms)

    crew = build_crew(
        config=crew_config,
        llms=llms,
        tools=tools,
        effort=effort,
    )
    try:
        result = crew.kickoff(inputs=final_inputs)
    except Exception:
        registry.record_usage(template_name, success=False)
        registry.save()
        raise
```

**Move `_is_retryable_timeout()` to a shared location.** Create
`src/agent_mesh/timeout_utils.py` with the function and `RETRYABLE_ERROR_NAMES`
constant. Import from both `runner.py` and `llm_wrapper.py`.

#### Changes to `src/agent_mesh/timeout_utils.py` (new file)

```python
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
```

#### Tests: `tests/test_circuit_breaker.py`

```python
def test_timeout_triggers_fallback():
    """A timeout on swarm should retry on clever."""

def test_non_timeout_error_propagates():
    """A 400 error should NOT trigger fallback."""

def test_fallback_timeout_propagates_original():
    """If fallback also times out, the original error propagates."""

def test_no_fallback_configured_propagates():
    """Models without fallback_model propagate timeout directly."""

def test_fallback_call_gets_same_messages():
    """The fallback call should receive the same sanitized messages."""

def test_runner_no_longer_has_retry_loop():
    """run_task should not catch and retry timeouts at the crew level."""
```

#### Tests: `tests/test_timeout_utils.py`

Move existing timeout detection tests from `tests/test_runner_retry.py` to
this file. Update imports. Keep the retry-specific tests (fallback config,
delay calculation) in `test_runner_retry.py` but mark them as testing
deprecated behavior that will be removed.

#### Verification

```bash
python -m pytest tests/test_circuit_breaker.py tests/test_timeout_utils.py -v
python -m pytest tests/ -v
```

Manual verification: run a crew with swarm agents. Artificially lower the
swarm timeout to 5s to trigger fallback. Observe:
- Log lines showing `fallback=local-clever`
- Crew completes successfully (no crew-level restart)
- All completed agent work is preserved

#### Do NOT

- Do not add retry counts or exponential backoff at the per-call level — one
  fallback attempt is enough. If both models fail, the error is real.
- Do not remove `_fallback_config_after_timeout` from runner.py yet — mark it
  deprecated. It can be cleaned up in a later sprint.
- Do not add circuit breaker state tracking (open/half-open/closed) — that is
  over-engineering for the current scale

---

### r-s04 — Realistic Concurrency Caps + Swarm Sizing

**Branch:** `sprint/r-s04-concurrency-caps`
**Depends on:** r-s02 (can run in parallel with r-s03)

#### Goal

Align the planner's model assignment policy with actual backend capacity.
Currently the planner is told "swarm supports 16 concurrent agents" and
generates crews accordingly, but the vLLM backend saturates at ~4-5 requests.

#### Changes to `config/models.yaml`

Reduce `max_concurrency` for swarm to reflect actual usable parallelism.
The `client_concurrency` from r-s02 prevents HTTP-level saturation, but
`max_concurrency` controls how many async agents the planner generates.
Having 16 async agents with client_concurrency=4 means 12 agents sit idle
waiting for slots — wasteful.

```yaml
models:
  swarm:
    # ... existing fields ...
    max_concurrency: 6         # was 16 — reduced to match vLLM capacity
    client_concurrency: 4      # from r-s02
```

**Why 6 instead of 4:** The planner uses `max_concurrency` to decide how many
async agents to create. With `client_concurrency=4`, 6 agents means at most
2 are queued client-side at any time — acceptable overhead. Going lower (e.g. 4)
would force mostly sequential execution, losing the parallelism benefit.

#### Changes to `config/effort.yaml`

Align `max_swarm_agents` with the new concurrency cap:

```yaml
levels:
  quick:
    max_swarm_agents: 2       # unchanged

  standard:
    max_swarm_agents: 4       # unchanged

  thorough:
    max_swarm_agents: 6       # was 8 — capped at max_concurrency

  exhaustive:
    max_swarm_agents: 6       # was 16 — capped at max_concurrency
```

#### Changes to `config/model_policy.yaml`

Update the swarm section to reflect realistic capacity:

```yaml
  swarm:
    description: >
      Local 9B model with vision. Small but fast. Supports up to 6
      concurrent agents, with 4 actively running and 2 queued.
    when_to_use:
      - Parallel research branches (up to 6 concurrent)
      # ... rest unchanged ...
    when_not_to_use:
      - Complex reasoning or synthesis (too small)
      - Final answers (quality insufficient)
      - Tasks requiring deep analytical thinking
      - More than 6 parallel branches (will queue and slow down)
    cost_note: "Free (local) — use for parallel workers, but keep under 6 agents"
```

Update `assignment_rules`:
```yaml
assignment_rules:
  - "Use swarm for parallel research: create up to max_swarm_agents async tasks"
  - "Do NOT create more swarm agents than max_swarm_agents for the effort level"
  # ... rest unchanged ...
```

#### Verification

```bash
python -m pytest tests/test_crew_spec.py -v  # concurrency validation still works
```

Run a `thorough` crew. Verify that the planner generates at most 6 swarm
agents (visible in the runtime diagnostic output from crew_builder.py).

#### Do NOT

- Do not change `client_concurrency` here — that was set in r-s02
- Do not change model strengths or role assignments
- Do not reduce `max_concurrency` below `client_concurrency` — that makes no sense

---

## Sprint Execution Order

```
r-s01 (LLM call wrapper)        ← CRITICAL, do first — fixes message ordering
r-s02 (concurrency limiter)     ← depends on r-s01
r-s03 (circuit breaker)         ← depends on r-s02
r-s04 (concurrency caps)        ← depends on r-s02, parallel with r-s03
```

Suggested execution:
- **Batch 1**: r-s01
- **Batch 2**: r-s02
- **Batch 3**: r-s03 + r-s04 (independent once r-s02 is done)

---

## Acceptance Criteria (end-to-end)

After all sprints are complete:

1. **No more "System message must be at the beginning" errors** — the LLM.call
   wrapper sanitizes messages before they reach any transport layer
2. **vLLM KV cache stays under 80%** during crew runs — verified by checking
   vLLM metrics during a thorough/exhaustive run
3. **Individual LLM timeouts are retried on fallback model** — visible in logs
   as `[llm_call] ... fallback=local-clever`
4. **Crew-level restart no longer happens on timeout** — the runner.py retry
   loop is removed
5. **Every LLM call has a correlation ID and timing** — visible in logs,
   enabling end-to-end request tracing
6. **Planner generates right-sized crews** — at most 6 swarm agents at
   thorough/exhaustive
7. **All tests pass**: `python -m pytest tests/ -v`

---

*End of sprint plan.*
