# Scholarr task cards

Work in order. A card is complete only when its acceptance criteria are met. Specs are reviewed
and frozen one at a time before implementation begins.

## Card 0: publish the clean repository  **COMPLETE 2026-07-22**

**Goal:** publish this clean-history bootstrap as the public project.

The legacy GitHub repository was preserved as `JustinZeus/scholarr-legacy`. The clean bootstrap is
public at `JustinZeus/scholarr` on GitHub, with the same history copied to Forgejo. GitHub is the
primary remote.

**Acceptance:** public `justinzeus/scholarr` repositories exist on GitHub (primary) and Forgejo
(copy), both point at this clean history, no legacy history is present, and no secret or work
identity appears anywhere.

## Card 1: freeze the data model spec  **REVIEW-READY 2026-07-23, NOT FROZEN**

**Goal:** specify global author/publication identity, per-user follows/read state, review records,
and merge/undo behavior.

Inputs: the project identity decision record, the legacy schema concepts worth salvaging, and the
global `FollowedAuthor` plus `AuthorSourceIdentity` direction.

**Acceptance:** `docs/specs/data-model.md` is owner-reviewed and marked frozen; constraints,
migrations, duplicate prevention, audit/undo behavior, and every remaining open question are
explicit.

**Draft result:** [`docs/specs/data-model.md`](docs/specs/data-model.md) is complete for owner and
independent review. It records fixed decisions, proposes a concrete SQLite model, and isolates five
owner decisions. Acceptance remains open until the owner reviews those decisions and explicitly
marks the spec frozen. Do not begin implementation.

## Card 2: freeze provider contracts and health

**Goal:** specify sanctioned API contracts, etiquette, persisted rate clocks/cooldowns, and
user-visible source health for OpenAlex, Crossref, arXiv, Unpaywall, and ORCID.

**Acceptance:** `docs/specs/providers.md` is owner-reviewed and marked frozen; keyed and anonymous
lanes, contact identity, retry semantics, restart behavior, fixture boundaries, and open questions
are explicit.

## Card 3: freeze the sync engine and run lifecycle

**Goal:** define safe, resumable acquisition within SQLite's concurrency model.

**Acceptance:** `docs/specs/sync-engine.md` is owner-reviewed and marked frozen; it defines one
active run per user, idempotent reruns, additive-only baseline import, resumability, writer
serialization, dry runs, and failure recovery.

## Card 4: freeze PDF resolution

**Goal:** define legal open-access discovery and provenance.

**Acceptance:** `docs/specs/pdf-resolution.md` is owner-reviewed and marked frozen; source order,
license/provenance handling, retry behavior, and the absence of all Google access are explicit.

## Card 5: freeze auth

**Goal:** define internal, generic OIDC, and trusted-header auth without provider-specific coupling.

**Acceptance:** `docs/specs/auth.md` is owner-reviewed and marked frozen; identity linking, roles,
session/security behavior, first-admin recovery, and mode-specific trust boundaries are explicit.

## Card 6: freeze the config schema

**Goal:** define one declarative configuration surface for the service.

**Acceptance:** `docs/specs/config.md` is owner-reviewed and marked frozen; defaults, validation,
secret references, provider settings, reload/restart behavior, and upgrade compatibility are
explicit.

## Card 7: freeze onboarding UX

**Goal:** make first run straightforward: search or paste Scholar URLs, review candidates, confirm,
and begin tracking.

**Acceptance:** `docs/specs/onboarding.md` is owner-reviewed and marked frozen; empty, ambiguous,
cooldown, partial-success, and unresolved-shell paths match the frozen UI and honest calibration
expectations.

## Card 8: choose the public license

**Goal:** make the repository genuinely open source under a consciously selected OSI license.

**Acceptance:** the owner selects the license, `LICENSE` is added with correct copyright identity,
and README/project metadata are updated.

## Card 9: plan build phases

**Goal:** split implementation into reviewable vertical slices against the frozen specs and UI.

**Acceptance:** build cards cover schema/migrations, providers, sync, auth, API, Vue port,
packaging, backup/restore, and release gates. Every card names its tests and demo proof.
