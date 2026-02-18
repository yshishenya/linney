<!--
managed-by: sdd-workflow-kit
kit-version: 0.2.2
template: docs/templates/Architecture-Template.md.tmpl
-->

# Architecture Overview

## Scoping (Read First)

- Use this as the map to avoid repo-wide scanning.
- Link modules to entry points, key docs, and key code paths.

## Summary

## System/Module Map

```mermaid
flowchart LR
  UI["UI"] -->|"HTTP"| API["API"]
  API -->|"calls"| CORE["Core"]
```

## Module Index

## Dependency Rules

## Key Decisions (ADRs)

