# a-s04 — Move Runtime State Out of Config — Implementation Log

**Date:** 2026-03-13
**Agent:** Codex GPT-5
**Branch:** sprint/a-s04-runtime-state
**Status:** Complete

## What Was Implemented
- Updated `src/agent_mesh/config_loader.py` to introduce `DATA_DIR`, create `data/` on first use, seed `data/crew_registry.yaml` from `config/crew_registry.yaml`, and load generated crews from `data/generated_crews/`.
- Updated `src/agent_mesh/crew_renderer.py` so generated crews are written to `data/generated_crews/`.
- Updated `src/agent_mesh/registry.py` so promotion copies generated crews from `data/generated_crews/` into `config/crews/`.
- Added `/data/` to `.gitignore`.
- Updated `tests/test_registry.py` to isolate config/data roots in a temp workspace and added coverage for first-load `data/` creation.

## Deviations from Sprint Plan
- Kept the existing tracked `config/generated_crews/` directory untouched for compatibility, but the runtime loader/writer path now exclusively uses `data/generated_crews/` as specified by the sprint.
- Verified the broader `tests/` suite instead of only the registry-focused subset because `config_loader.py` is shared across planner, registry, and config tests.

## Issues Found
- None in the implementation. The new runtime `data/` directory is created automatically and remains gitignored.

## Verification Results
- `python3 -m compileall src/agent_mesh/config_loader.py src/agent_mesh/crew_renderer.py src/agent_mesh/registry.py tests/test_registry.py tests/test_config_loader.py`
- `.venv/bin/python -m pytest tests/ -v`
- `ls -la data/`
- `git status --short --branch`
- Result: `29 passed`, `data/` exists, and `git status` does not show `data/`.

## Items for Architect Review
- Confirm whether a later cleanup sprint should remove or archive the now-legacy tracked `config/generated_crews/` path to avoid confusion, since runtime writes have moved to `data/generated_crews/`.
