# {{PROJECT_NAME}} — Sprint Plan: [Track Name]

**Version:** 1.0
**Date:** YYYY-MM-DD
**Derived from:** [Link to spec or requirement document]
**Purpose:** Step-by-step sprint plan for a coding agent to execute.

---

## How to Use This Document

Execute sprints in order within each phase. Each sprint is self-contained.

**Sprint format:**
- **Goal:** One sentence describing what "done" looks like
- **Prerequisites:** What must exist before starting
- **Branch:** The branch to create for this sprint
- **Tasks:** Numbered steps — execute in order
- **Verification:** How to confirm the sprint is complete
- **Do NOT:** Explicit guardrails — things to avoid

---

## Phase 1 — [Phase Title]

> [One-line description of what this phase accomplishes]

---

### Sprint p1-s01 — [Sprint Title]

**Goal:** [One sentence. What does "done" look like?]

**Prerequisites:**
- [What must exist before starting]
- [Previous sprint completed, data files present, etc.]

**Branch:** `sprint/p1-s01-[description]`

**Tasks:**

1. **[Task title]**

   **File:** `path/to/file`

   [Detailed instructions. Include exact file paths, code snippets,
   and the reasoning behind the approach.]

2. **[Task title]**

   **File:** `path/to/file`

   [Continue numbering. Each task builds on the previous one.]

**Verification:**

- [ ] [Specific, testable acceptance criterion]
- [ ] [Command to run and expected output]
- [ ] [Files that should exist after completion]

**Do NOT:**
- [Explicit guardrails — things the coder must avoid]
- [Files not to touch, patterns not to follow]
- [Scope boundaries — what is out of scope for this sprint]

---

### Sprint p1-s02 — [Next Sprint Title]

[Same structure repeats for each sprint.]

---

## Sprint Dependency Map

```
p1-s01 (Scaffold)      → can start immediately
p1-s02 (Core logic)    → after p1-s01
```

---

## Checklist Summary

After all sprints in this plan complete:

- [ ] [High-level acceptance criterion for the entire plan]
- [ ] [Another criterion]

---

*End of sprint plan.*
