<!--
managed-by: sdd-workflow-kit
kit-version: 0.2.0
template: docs/templates/Architecture__Overview.md.tmpl
-->

# Architecture Overview

This file is the top-level map of boundaries and dependency rules.

If you already have an architecture doc, keep yours and disable this in `.sddkit/config.toml`.

## Scoping (Read First)

- Start from this document before touching code.
- Use links to navigate (avoid repo-wide scanning).

## System Map

```mermaid
flowchart LR
  Entry["Entry Points"] -->|"calls"| Modules["Modules"]
  Modules -->|"reads/writes"| Data["Data/State"]
```

## Module Index

## Dependency Rules

## Key Decisions (ADRs)

