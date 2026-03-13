# {{PROJECT_NAME}} — Architecture Specification

**Version:** 1.0
**Date:** YYYY-MM-DD
**Author:** Architect
**Derived from:** `docs/specs/system.md` (product specification)
**Status:** Draft | Review | Approved

This is the **architecture spec** — it translates the product spec's *what/why*
into precise *how*: schemas, data flow, formulas, API contracts, and constraints.
Sprint plans are derived from this document, not from the product spec directly.

---

## 1. System Overview

[One paragraph: what the system does, its major components, and how they connect.
Reference the product spec for motivation — don't repeat the "why" here.]

## 2. Architecture Diagram

```
[ASCII diagram showing major components and data flow between them.
Example:

  User ──→ Frontend SPA ──→ API Worker ──→ Storage (R2/S3)
                                 ↑
                           Pipeline Agent ──→ State Files (git)
]
```

## 3. Component Inventory

| Component | Technology | Location | Purpose |
|-----------|-----------|----------|---------|
| [Frontend] | [e.g., Vanilla JS SPA] | `sites/` | [User interface] |
| [API] | [e.g., Cloudflare Worker] | `worker/` | [Data serving] |
| [Pipeline] | [e.g., Python scripts] | `agent/` | [Data collection/processing] |

## 4. Data Structures

### 4.1 [Primary data structure]

```json
{
  "example_field": "value",
  "nested": {
    "field": "type and purpose"
  }
}
```

**Invariants:**
- [Rules that must always hold, e.g., "baseline_date must never be mutated"]

### 4.2 [Secondary data structure]

[Repeat for each major data structure.]

## 5. Data Flow

### 5.1 [Pipeline name, e.g., "Daily Processing"]

```
Input: [source]
  → Step 1: [transform]
  → Step 2: [enrich]
  → Output: [destination file/path]
```

**Frequency:** [e.g., Daily via GitHub Actions]
**Trigger:** [e.g., Cron schedule, manual, webhook]

### 5.2 [Another pipeline]

[Repeat for each data flow.]

## 6. API Contracts

### 6.1 [Endpoint name]

```
GET /api/resource
Response: { "field": "type" }
```

**Auth:** [None | Token | etc.]
**Cache:** [Strategy]

### 6.2 [Another endpoint]

[Repeat for each endpoint.]

## 7. Formulas and Algorithms

[Any scoring, ranking, or computation logic that the coder must implement exactly.
Include the formula, input types, output types, and edge cases.]

```python
# Example: verbatim implementation-ready function
def compute_score(signals):
    """
    Input: list of signal dicts with 'strength' (0-1) and 'confidence' (0-1)
    Output: float score 0-100
    """
    if not signals:
        return 0.0
    return sum(s['strength'] * s['confidence'] for s in signals) / len(signals) * 100
```

## 8. Hard Constraints

These are **invariants** that the coder must never violate:

1. [e.g., "No database — all state is JSON files committed to git"]
2. [e.g., "State files are sacred — never delete `agent/state/*.json`"]
3. [e.g., "All API responses include CORS headers"]

## 9. File Map

New and modified files that will be created across all sprints:

| File | New/Modified | Purpose | Created in Sprint |
|------|-------------|---------|-------------------|
| | | | |

## 10. Phase Mapping

How the architecture maps to implementation phases and sprints:

| Phase | Sections | Sprint IDs | Summary |
|-------|----------|------------|---------|
| 1 | §3-§5 | p1-s01 to p1-sNN | [Core setup] |
| 2 | §6-§7 | p2-s01 to p2-sNN | [API + logic] |

---

*End of architecture specification. Use this document to derive sprint plans in `docs/sprints/`.*
