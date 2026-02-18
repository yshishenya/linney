<!--
managed-by: sdd-workflow-kit
kit-version: 0.2.2
template: docs/templates/SDD__README.md.tmpl
-->

# SDD (Spec-Driven Development)

This repository uses SDD: plan/spec first, then implement, then verify.

## Folder Layout

- `docs/ADR/`: architecture decisions
- `docs/Features/`: feature behaviour specs
- `docs/Architecture/`: system maps and boundaries
- `docs/templates/`: doc templates used by skills
- `specs/`: machine-readable specs (pending/active/completed)

## Core Rules

- No guessing: specs and docs must be executable and testable.
- Atomic tasks: one file change per task whenever possible.

