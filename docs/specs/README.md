# Architecture specs

Specs are frozen in the order listed in `TASKS.md`. Each spec must:

- distinguish locked decisions from open questions;
- define data and trust boundaries;
- state failure, recovery, migration, and observability behavior;
- identify deterministic fixtures and acceptance tests;
- receive explicit owner review before being marked frozen.

No implementation for a subsystem starts before its spec is frozen.

## Current review

- [Data model](data-model.md): review-ready draft dated 2026-07-23, not frozen. Owner decisions
  D1 through D5 remain open.
