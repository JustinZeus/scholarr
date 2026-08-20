# Scholarr rewrite - testing strategy  **[live 2026-07-21]**

This is an agreed direction from the 2026-07-21 discussion with Justin, to be formalized during
spec freeze. Part of the [scholarr-rewrite](README.md) runbook; read the doctrine there first.

This document records how the rewrite proves itself correct. It is a decision record, not the final
spec: it feeds the spec set and defines the release gates below.

## Core principle

**Deterministic tests against recorded reality.** The service's hard logic (matching, dedup,
scheduling, backoff) must be testable with **zero network**. Nothing that matters to correctness
depends on a live provider being reachable at test time.

## Golden corpus

Two recorded artifacts become **permanent fixtures in the repo** (anonymized where needed):

- The **recovered v1 database**: 25,698 real publications, 492 profiles with real edge cases.
- The **calibration run's cached OpenAlex responses**.

These are the ground for deterministic replay: the matcher and dedup logic are exercised against
real data and real provider payloads without touching the network.

## The five pillars

1. **Pure logic** (normalization, fingerprinting, identifier parsing, confidence scoring):
   - table tests;
   - **property-based tests** for the invariants that must always hold: normalization is
     idempotent, dedup is order-independent, merge is commutative;
   - **Go native fuzzing** on every parser that touches external text or paste input.

2. **Provider clients:**
   - **contract tests** replaying recorded HTTP fixtures via `httptest`, including the ugly cases:
     `429` with and without `Retry-After`, truncated JSON, empty pages;
   - the **rate limiter and cooldown state machine** tested with a **fake clock**;
   - the **2026-07-21 OpenAlex IP block becomes a regression case** so the system's handling of an
     IP-level block is proven, not hoped.

3. **Sync engine** - executable invariants:
   - one active run per user;
   - idempotent re-runs;
   - additive-only baseline import;
   - crash-mid-run leaves resumable state;
   - **race detector in CI**, plus a **concurrent-write hammer test**, because single-writer
     discipline is the main risk of the SQLite-only design.

4. **Migrations:**
   - every migration tested **up and down** against a **real-database copy**;
   - plus a **seeded prior-version DB in CI**, so upgrades are proven **pre-release**.

5. **End-to-end smoke:**
   - the binary boots in CI with a **seeded SQLite** and a **stub provider**;
   - a **scripted curl** run walks the full API flow: onboard, import, sync, review-resolve, read,
     export.
   - **No browser automation.** UI QA is manual by Justin against the frozen design contract
     (`/opt/stacks/scholarr-rewrite/design/DESIGN.md`). See the working-conventions block
     in [README.md](README.md#conventions-for-any-agent-working-this-project).

## Dry runs are a product feature

Not test-only scaffolding, actual product behavior that also serves as the QA instrument:

- **bulk import previews** before creating anything;
- **`--dry-run`** on sync and on destructive admin actions.

## Acceptance

**Shadow-run** with the real ~253-author list for **2 to 3 weeks**, alongside the dad's existing
JS-script habit, and **diff what each caught**. This is the **release flip criterion** and follows
the conductarr-soak pattern.

## Release gates, in order

1. unit + property + fuzz green;
2. race detector green;
3. migration up/down green;
4. e2e smoke green;
5. **golden-corpus ratchet** - matcher changes may not regress the recorded auto-match baseline;
6. tagged release with a **tested backup/restore path documented**.

## Related

- The recovered v1 DB and calibration cache that become fixtures: [README.md](README.md) (Assets),
  [identity-calibration.md](identity-calibration.md).
- Manual-QA rule (no browser automation): a working convention of this project, stated in
  [README.md](README.md#conventions-for-any-agent-working-this-project).
