# Scholarr agent brief

This file is the canonical brief for every coding agent working in this repository. Read it and
`TASKS.md` before making changes.

## Product

Scholarr is a public, self-hosted FOSS author watchlist and publication tracker. A user follows
authors, learns when they publish, and finds legal open-access PDFs. It must serve a real
multi-user household deployment while remaining straightforward for the wider self-hosting
community.

## Immutable doctrine

There is zero Google Scholar network contact, ever.

- No application code, test, tool, CI job, or documentation example may request a Google
  endpoint.
- No scraping, browser automation, CAPTCHA handling, anti-bot behavior, or evasion machinery.
- Scholar IDs and URLs may exist only as inert imported metadata and human-clickable links.
- Acquisition uses documented APIs: OpenAlex, Crossref, arXiv, Unpaywall, and ORCID.
- Semantic Scholar is not a v1 requirement.
- Provider clients must use a contact identity, conservative persisted rate limits, restart-safe
  cooldowns, and user-visible health. OpenAlex must stay at or below 2 requests per second.

This doctrine outranks convenience and implementation shortcuts.

## Locked architecture

- Backend: Go.
- Frontend: Vue.
- Database: SQLite only. Design for single-writer discipline from the start.
- Root author entity: `FollowedAuthor`, with one or more `AuthorSourceIdentity` records.
- Names are labels, never identity keys. External source IDs anchor identity.
- Publications are globally deduplicated. Follows and read state are per user.
- Auth v1 includes internal username/password, generic OIDC, and trusted-header/forward-auth.
- The service is config-driven. One declarative config controls providers and behavior.
- GitHub `justinzeus/scholarr` is the intended public primary. Forgejo keeps a copy.

Do not silently change a locked decision. Record a proposed change as open and ask the owner.

## Decision record

On tank, the authoritative project runbook is:

`/opt/stacks/server-docs/runbooks/scholarr-rewrite/README.md`

It owns doctrine, locked decisions, empirical calibration results, and project state. Its
companion files own the identity model and testing strategy. This brief is self-contained for
agents without tank access, but any state or design decision reached on tank must also be written
to that runbook in the same session.

## Frozen UI contract

- `design/DESIGN.md` is the frozen Vue handoff contract.
- `design/tokens.css`, `design/component-reference.html`, and `design/assets/` are canonical UI
  inputs.
- `design/reference/Scholarr.dc.html` is the reviewed proof implementation.
- `design/reference/support.js` belongs only to that design proof. Never ship it in production.
- Port the design faithfully. Do not redesign while implementing.
- Carry two cleanup items into the Vue port: avoid em dashes in bulk-import copy, and do not show
  raw match percentages as user-facing confidence labels.

UI QA is manual and performed by the owner against the frozen contract. Do not add or run
Playwright, Selenium, or other browser automation. Unit, integration, build, and curl smoke tests
are expected.

## Work process

- Work through `TASKS.md` in order. Each task has a goal and acceptance criteria.
- Freeze one spec at a time. Decided items are labeled decided; open items remain open for owner
  review.
- Do not start implementation for an area whose spec is not frozen.
- Keep commits focused and use plain imperative commit messages without trailers.
- Stage only files you changed.
- Do not use em dashes in prose, code comments, commit messages, or user-facing copy.
- Never commit secrets, real user data, database dumps, provider payloads containing private
  data, API keys, tokens, or real email addresses.
- Keep configuration examples synthetic and safe to publish.

## Correctness obligations

- Pure normalization, fingerprinting, parsing, and scoring logic gets table tests, property tests
  for invariants, and Go fuzz tests for external input parsers.
- Provider clients use deterministic `httptest` fixtures, including 429 responses, missing
  `Retry-After`, truncated JSON, and empty pages. Rate and cooldown tests use a fake clock.
- Sync tests prove one active run per user, idempotent reruns, additive-only baseline import,
  resumability after interruption, and SQLite concurrency behavior. Run the race detector.
- Every migration is tested up and down, including upgrade from a seeded prior-version database.
- End-to-end smoke boots a seeded SQLite database with stub providers and exercises onboarding,
  import, sync, review, read state, and export through the API.
- Matching and dedup changes may not regress the recorded golden-corpus baseline.

Dry-run import previews and dry-run destructive admin actions are product features, not test-only
helpers.
