# AGENTS.md — {{PROJECT_NAME}} Multi-Agent Framework

This file is the shared knowledge base for all agents working in this repository.
Read this file first. It tells you where everything is, what the conventions are,
and how the two-agent collaboration works.

---

## 1. Project in One Paragraph

{{PROJECT_DESCRIPTION}}

---

## 2. Agent Roles

### Owner (Human)
- Writes the product specification (`docs/specs/system.md`) — vision, decisions, requirements
- Reviews and approves architecture specs and sprint plans before execution
- Merges branches after architect review
- Provides domain knowledge and clarifications when asked

### Architect (Claude Code)
- Translates the product spec into an architecture spec (`docs/specs/architecture.md`) — schemas, data flow, formulas, API contracts, hard constraints
- Translates the architecture spec into sprint plans (`docs/sprints/`) — exact file paths, code snippets, verification steps
- Reviews implementation logs from the coder and updates `docs/sprints/backlog.md`
- Writes to `docs/specs/` and `docs/sprints/` and `AGENTS.md`
- Never implements code directly in the repo source — only plans

### Coder (Codex / Cursor / Aider)
- Reads sprint plans from `docs/sprints/`
- Implements exactly what the sprint specifies
- Writes implementation notes to `docs/logs/` after each sprint
- Creates branches, commits, and PRs per the conventions below
- Flags blockers, gaps, or spec ambiguities in log files for the architect
- Updates `docs/logs/open-issues.md` for unresolved high-impact issues

### The Spec-to-Code Pipeline
```
Owner writes product spec (system.md)
  → Architect translates to architecture spec (architecture.md)
    → Architect translates to sprint plans (docs/sprints/)
      → Coder implements sprint → Coder writes log
                                       │
  Architect reads log, updates backlog ←┘
```

**Why three steps, not two?**
The product spec captures *what* and *why*. The architecture spec locks down *how* —
schemas, formulas, data flow, API contracts — before any sprint planning begins.
Sprint plans then become precise implementation instructions rather than design sessions.
This prevents the coder from making architectural decisions during implementation.

---

## 3. Repository Structure

### Source code
```
# TODO: Document your project's source code structure here.
# Example:
# src/                   Application source code
# tests/                 Test files
# scripts/               Build, deploy, utility scripts
```

### Documentation
```
docs/
  specs/                Specifications (owner + architect)
    system.md           Product spec — vision, decisions, requirements (authored by owner)
    architecture.md     Architecture spec — schemas, data flow, contracts (authored by architect)
  sprints/              Sprint plans (authored by architect, executed by coder)
    backlog.md          Deferred items, known gaps, future work
  logs/                 Implementation notes (authored by coder, reviewed by architect)
    open-issues.md      Shared tracker for unresolved delivery/ops issues
  archive/              Historical documents (executed, kept for reference)
  DECISIONS.md          Architecture Decision Records
  review-checklist.md   Sprint review template for architect
```

### Root files
```
CLAUDE.md               Architect agent config → points to AGENTS.md
CODEX.md                Coder agent config → points to AGENTS.md
AGENTS.md               THIS FILE — shared agent knowledge base
Makefile                Dev convenience targets
.gitignore              Ignore rules
.gitattributes          State file merge strategy (if applicable)
.env.example            Environment variable documentation
```

---

## 4. Naming Conventions

### 4.1 Sprint IDs

Format: `{track}-{sequence}` — lowercase, hyphen-separated.

| Track | Format | Example | Description |
|-------|--------|---------|-------------|
| Feature | `p{phase}-s{nn}` | `p1-s01` | Phase 1, Sprint 01 |
| Compliance/Ops | `c-s{nn}` | `c-s01` | Compliance Sprint 01 |
| Backlog | `b-{nnn}` | `b-001` | Backlog item 001 |

Sprint IDs are stable — once assigned, never renumbered.

### 4.2 Branch Naming

Format: `{type}/{sprint-id}-{short-description}`

```
sprint/p1-s01-initial-scaffold
sprint/p2-s03-api-endpoints
sprint/c-s01-legal-pages
fix/p2-s04-api-fallback
chore/docs-restructure
chore/deps-update
```

**Types:**
- `sprint/` — implementing a planned sprint
- `fix/` — fixing a bug or gap found during/after a sprint
- `chore/` — maintenance (deps, docs, CI config)
- `refactor/` — restructuring without behavior change

**Rules:**
- Always branch from `main`
- One branch per sprint (a sprint may contain multiple commits)
- Merge to `main` when sprint verification passes
- Delete branch after merge

### 4.3 Commit Messages

[Conventional Commits](https://www.conventionalcommits.org/) format:

```
{type}({scope}): {description}

{optional body}
```

**Types:** `feat`, `fix`, `refactor`, `docs`, `chore`, `test`, `style`

**Scope:** Sprint ID or component name.

**Examples:**
```
feat(p1-s01): create project scaffold
feat(p2-s03): add API endpoint for user data
fix(p2-s04): correct API fallback path for local dev
docs(c-s01): add privacy policy page
chore(deps): update dependency versions
chore(bot): automated daily run YYYY-MM-DD
```

**Rules:**
- Imperative mood: "add", "fix", "update" — not "added", "fixes", "updated"
- First line under 72 characters
- Body optional, used for explaining *why* not *what*
- Automated pipeline commits use `chore(bot):` prefix

### 4.4 File Naming in docs/

- Lowercase, hyphens: `feature-sprints.md`, `p1-notes.md`
- Specs: descriptive name (`system.md`, `architecture.md`)
- Sprint plans: by track (`feature-sprints.md`, `compliance-sprints.md`)
- Logs: by phase or topic (`p1-notes.md`, `general-notes.md`)
- No version numbers in filenames — use git history

### 4.5 Log File Convention

When the coder finishes a sprint, write a log to `docs/logs/`:

```markdown
# {Sprint ID} — {Title} — Implementation Log

**Date:** YYYY-MM-DD
**Agent:** {Agent name and version}
**Branch:** sprint/{branch-name}
**Status:** Complete | Partial | Blocked

## What Was Implemented
- Bullet list of changes with file paths

## Deviations from Sprint Plan
- Anything done differently from the plan, with reasoning

## Issues Found
- Bugs, gaps, or ambiguities discovered during implementation

## Verification Results
- Which acceptance criteria passed/failed

## Items for Architect Review
- Questions, backlog items, or spec clarifications needed
```

For cross-sprint unresolved issues, also add/update an entry in
`docs/logs/open-issues.md` and reference its backlog ID.

---

## 5. Key Architectural Constraints

These are **hard rules** that both agents must respect:

<!-- TODO: Replace these examples with your project's actual constraints. -->
<!-- Delete examples that don't apply. Add your own. -->

1. **Example:** No database — all state is JSON files committed to git.
2. **Example:** No framework — vanilla code, no build step.
3. **Example:** Single hosting provider for simplicity.
4. **Example:** State files are sacred — never delete them.
5. **Example:** One-person maintenance model — everything must be operable solo.

---

## 6. Environment & Secrets

<!-- TODO: List your project's environment variables here. -->

```
# EXAMPLE_API_KEY        Description of what this key is for
# DEPLOY_TOKEN           Deployment authentication
# SLACK_WEBHOOK_URL      Optional failure notifications
```

All secrets set via: `gh secret set {NAME} --repo {owner}/{repo}`

---

## 7. Quick Reference — Make Targets

```
make help          Show all targets
```

<!-- TODO: Add your project's make targets here as you define them. -->

---

## 8. Document Migration Map

<!-- Optional section. Use when reorganizing docs from a different structure. -->
<!-- Delete this section if starting fresh. -->

| Original Location | New Location | Notes |
|-------------------|-------------|-------|
| | | |

---

## 9. Sprint Status Tracking

Use this section as a living status board. Update after each sprint completes.

### Feature Sprints

| ID | Phase | Title | Status |
|----|-------|-------|--------|
| | | | |

### Compliance / Ops Sprints

| ID | Title | Status |
|----|-------|--------|
| | | |

### Backlog

| ID | Title | Status |
|----|-------|--------|
| | | |
