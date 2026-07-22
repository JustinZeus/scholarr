# Architecture specs

Specs are frozen in the order listed in `TASKS.md`. Each spec must:

- distinguish locked decisions from open questions;
- define data and trust boundaries;
- state failure, recovery, migration, and observability behavior;
- identify deterministic fixtures and acceptance tests;
- receive explicit owner review before being marked frozen.

No implementation for a subsystem starts before its spec is frozen.
