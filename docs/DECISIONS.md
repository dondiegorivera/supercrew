# Architecture Decision Records

Record significant decisions that affect the project's architecture,
conventions, or agent workflow. Number sequentially. Never renumber.

---

## ADR-001: Transport-Layer LLM Resilience

**Date:** 2026-03-14
**Status:** Accepted

### Context

We have been patching integration failures between CrewAI, LiteLLM, and our
vLLM backend one at a time. Each fix addresses a symptom but not the structural
cause. Specifically:

1. **Message sanitizer bypass.** `compat.py` patches `litellm.completion` at the
   module attribute level. But if CrewAI's internal code captures a reference
   to the original function at import time (via `from litellm import completion`),
   the patch is silently bypassed. This is why "System message must be at the
   beginning" errors keep returning even though the sanitizer exists.

2. **Crew-level retry is too coarse.** When one LLM call out of many times out,
   `runner.py` tears down the entire crew and restarts from scratch. This wastes
   all completed work and triggers CrewAI internal state corruption
   (`Event pairing mismatch` warnings).

3. **No client-side backpressure.** The model policy advertises 16 concurrent
   swarm agents but the vLLM backend saturates (100% KV cache) well before
   that. There is no throttling mechanism between the client and the backend.

### Decision

Replace the current approach (monkey-patching `litellm.completion`, crew-level
retry) with a layered resilience architecture that intercepts at three levels:

**Layer 1 — LLM call wrapper** (replaces compat.py monkey-patch)

Wrap `crewai.LLM.call()` at the class level. This is the single entry point
for ALL LLM invocations from CrewAI, regardless of whether CrewAI internally
uses `litellm.completion`, `litellm.acompletion`, or a provider SDK. No
import-order sensitivity. Message sanitization, request correlation, and
timing are applied here.

**Layer 2 — Per-model concurrency limiter** (new)

A `threading.Semaphore` per model profile, enforced in the LLM call wrapper.
Prevents more concurrent requests than the backend can handle. Requests
beyond the limit queue client-side instead of saturating vLLM.

**Layer 3 — Per-call circuit breaker with model fallback** (replaces crew-level retry)

Individual LLM calls that timeout get retried once on a fallback model (e.g.
swarm → clever), transparently. The crew doesn't know a fallback happened.
This preserves all completed work and avoids the crew restart cascade.

### Consequences

**Easier:**
- Message ordering bugs are fixed once, permanently — no import-order sensitivity
- Individual call failures are isolated — no crew-level restart for single timeouts
- Backend saturation is prevented by client-side throttling
- Request correlation (call IDs + timing) is built in, enabling the end-to-end
  tracing that was previously identified as the next investigation step
- Future CrewAI upgrades are less likely to break the integration

**Harder:**
- The LLM call wrapper adds a layer of indirection — debugging requires
  understanding that `LLM.call()` is wrapped
- Concurrency semaphores require tuning to match actual backend capacity
- Per-call fallback may mask backend problems that should be investigated
