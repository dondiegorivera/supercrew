# Sprint Review Checklist

Use this checklist when the architect reviews a coder's implementation log.
Copy this template for each sprint review.

---

## Sprint: [ID] — [Title]
## Reviewer: Architect
## Date: YYYY-MM-DD

### Implementation Completeness
- [ ] All tasks in the sprint plan are addressed in the log
- [ ] All new files listed in the sprint plan were created
- [ ] All modified files listed in the sprint plan were changed
- [ ] No unexpected files were modified (check `git diff --stat` scope)

### Verification
- [ ] All acceptance criteria from the sprint plan are marked pass/fail in the log
- [ ] Any failing criteria have documented reasons
- [ ] Verification commands were run and output recorded

### Quality
- [ ] Deviations from plan are justified with clear reasoning
- [ ] No scope creep (changes outside sprint scope are logged, not silently done)
- [ ] Issues found are logged with backlog IDs where applicable

### Follow-up Actions
- [ ] Backlog updated with any new items from the log (`docs/sprints/backlog.md`)
- [ ] Status board in AGENTS.md Section 9 updated
- [ ] Open issues in `docs/logs/open-issues.md` assigned (Coder, Architect, or Owner)
- [ ] Next sprint prerequisites met (unblocked)

### Decision
- [ ] **Approve** — merge branch, mark sprint done in status board
- [ ] **Request changes** — list items that need fixing before merge
- [ ] **Block** — serious issue found, needs spec revision or re-planning
