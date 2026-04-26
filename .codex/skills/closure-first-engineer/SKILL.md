---
name: closure-first-engineer
description: Use for multi-step coding, refactors, feature closeout, or game-tooling work when the goal is to reduce rework, late fixes, and patch-after-the-fact cleanup. Enforces contract-first edits, paired tests and docs, plan-to-review-to-release closure, data schema validation, release QA gates, and serial verification in this repo.
---

# Closure First Engineer

Use this skill when a task is likely to sprawl across models, APIs, Portal UI, router logic, release artifacts, or historical data, and "make it work first, patch it later" would create debt.

## Workflow

1. Map the closure loop before editing.
   - Check whether the task touches `plan`, `execute`, `review`, `history`, `release`, `data_tables`, or `qa_gate`.
   - If a concept appears in more than one layer, define its canonical fields in the backend model or response contract first.

2. Make the contract explicit before broad edits.
   - Keep field names aligned across `Task.context`, API payloads, Portal state, export metadata, and MCP outputs.
   - Prefer stable, structured outputs over ad hoc strings.

3. Implement end-to-end in one pass.
   - If the backend exposes a new field, wire the UI or caller in the same turn.
   - If the UI adds a new action, add or extend the backing API instead of storing local-only state.

4. Add regression coverage while context is fresh.
   - Add targeted tests for success, invalid input, and serialization shape.
   - For review, history, release, or data-pipeline changes, assert persisted context or artifact metadata, not just top-level messages.

5. Close the smallest durable docs surface before stopping.
   - Usually update `README.md`.
   - Update a focused docs file only when behavior or workflow expectations changed there.

6. Verify in two passes.
   - Run targeted tests first.
   - Then run `python -m pytest -m "not live" -q` serially.
   - Do not run overlapping pytest suites in parallel in this repo.

## Repo Guardrails

- Portal and history work:
  - If a list can grow, design filtering and pagination at the API layer early.
  - Do not stop at front-end-only filtering for historical data.

- Feature review work:
  - New feature metadata must survive retry, rollback, and history serialization.
  - Execution that waits for review should emit a change summary or acceptance checklist.

- Release work:
  - Release artifacts should carry `build_id`, `version`, `channel`, `release_summary`, and machine-readable metadata.
  - Release gates should fail closed when review status or QA evidence is missing.

- Data table work:
  - Ship schema, validation, preview or diff, and write path together.
  - Avoid direct write-only import flows.

- Live and UI work:
  - Keep live tests separate from non-live CI.
  - If browser or editor automation was not run, state that explicitly in the final answer.

## Done Criteria

- Canonical contract updated in the backend model or API surface
- Caller, UI, or router integration closed for the same concept
- Targeted regression tests added
- Serial non-live verification run when shared logic changed
- User-facing docs updated where behavior changed
- Residual risk called out explicitly when live or browser verification was skipped
