# Scholarr rewrite charter  **[live 2026-08-20]**

Tracker: https://git.justintime.lol/justinzeus/scholarr/issues

Durable doctrine for the Scholarr rewrite: what was decided and why, and the
constraints every piece of work inherits. It holds no status, no next action and
no progress notes; those live on the issues. Migrated from the retired
`server-docs/runbooks/scholarr-rewrite/` on 2026-08-20, which is now git history.

## Goal

A self-hosted author-watchlist and publication tracker. A user follows a set of
authors; the service tracks what those authors publish and surfaces
legally-available open-access PDFs.

**Dual purpose, and both halves are first-class:**

- **Daily driver for Justin's dad** (he already follows hundreds of authors; the
  v1 product was built for exactly this use).
- **The one repo Justin wants to be genuinely useful to the general public**, a
  real public FOSS project, not a personal-tool-that-happens-to-be-on-GitHub.
  Design and polish are held to that bar.

## IMMUTABLE DOCTRINE: no Google Scholar network contact, ever

This is the entire reason the rewrite exists. It is not a preference or a
default; it is a hard invariant of the new system.

- **Zero Google Scholar network contact from the service, ever.** No scraping, no
  automated fetches from `scholar.google.com`, no headless-browser calls, no
  CAPTCHA-solving, no anti-bot or evasion machinery of any kind. There is no code
  path in the rewrite that reaches a Google endpoint.
- **Scholar IDs and Scholar URLs live on only as inert imported metadata and
  human-clickable links.** A stored Scholar profile URL is a link a *person* can
  click in a browser; the service itself never dereferences it.
- **Official APIs only.** Acquisition and enrichment go through documented,
  sanctioned APIs:
  - **OpenAlex**, primary works + authors source.
  - **Crossref**, **arXiv**, **Unpaywall**, metadata, preprints, legal
    open-access PDF resolution.
  - **ORCID**, identity anchor for disambiguating authors.
  - **Semantic Scholar**, resolved **not** a v1 requirement (2026-07-22
    calibration verdict). Possible later addition only.
- **Every provider is a good citizen.** Per-provider **persisted** rate limits,
  cooldowns, and **user-visible source health** are part of the design from the
  first spec, not bolted on later. Etiquette (contact `mailto`, modest request
  rates, backoff) is mandatory.

**Rationale (2026-07-21):** the v1 product was Scholar-first. Google login-gated
and CAPTCHA-challenged the scrapes, the box got blocked and IP-banned, name
search had to be **permanently disabled** in the UI, and development died
**2026-03-07** in the middle of Scholar-breakage firefighting. Justin's stated
requirement for the rewrite is: **"no risk of Google getting mad at my box, or
the service just stopping suddenly."** The doctrine above is the direct,
non-negotiable answer to that requirement.

## Locked decisions  *(2026-07-21, decided by Justin)*

| Area | Decision |
|---|---|
| **Language / stack** | Backend **Go**, frontend **Vue**. |
| **Database** | **SQLite only** (no Postgres). The concurrency design must fit SQLite from the start, it is not a placeholder to be swapped later. |
| **Root entity** | **`FollowedAuthor`** (source-agnostic), with **`AuthorSourceIdentity`** rows attached (OpenAlex / ORCID / Semantic Scholar / Scholar-imported). Scholar is **demoted** to an import reference plus a manual fallback identity, never the root. |
| **Auth (v1)** | Three modes, all in v1: (1) **internal username/password**, always available, the zero-dependency default; (2) **generic OIDC**, where Authentik is *one* provider among many and the integration is never Authentik-specific; (3) **trusted-header / forward-auth** mode. |
| **Multi-user** | **Confirmed requirement.** A **global, deduplicated publication store** shared across users, with **per-user follow links and per-user read state**. |
| **Hosting** | **GitHub is primary** and the public face. Personal identity only: **`justinzeus` / `justinfvisser@gmail.com`**, never the maxdoro work identity. **Forgejo keeps a copy** at `https://git.justintime.lol`. |
| **Repos** | The old Forgejo repo `justinzeus/scholarr` was renamed **`scholarr-legacy`** (kept as reference: specs, regression fixtures, git history). The rewrite is a **fresh `scholarr` repo with clean history**. |
| **Design values** | **Easy onboarding**: first run must be trivial, import Scholar URLs or search for authors, confirm, done. **Config-driven design throughout**: a conductarr-style declarative config, a single config file driving behavior. |

## Still open, deliberately

Recorded as open, not resolved here. Each is an owner decision, not an
implementation detail.

- **Release and distribution mechanics.** `ghcr` versus GitHub Releases; a single
  self-contained binary with an embedded frontend versus container-first.
- **License choice for a public FOSS product.** The legacy repo ships **MIT**
  (`Copyright (c) 2026 JustinZeus`). Whether the rewrite keeps MIT or picks
  another OSI license is a conscious decision, not a carry-over by inertia.
- **Semantic Scholar** stays a possible later addition. Resolved as out of scope
  for v1, not resolved as never.

## Working conventions

Binding on any agent editing this repo.

- **Commit messages: plain imperative, no trailers of any kind.** No
  `Co-Authored-By`, no `Generated-with`, no sign-off, no attribution lines.
- **Stage only your own files by name.** Never `git add -A` or `git add .`.
- **No em dashes in any written output.** Owner rule. Use commas, parentheses, or
  a spaced hyphen. Applies to docs, commits and code comments.
- **Immutable doctrine applies to every artifact.** No code path, spec, test or
  tool may reach a Google endpoint.
- **UI QA is manual, done by Justin. No browser automation.** Do not add or run
  Playwright, Selenium or headless-browser UI tests. Smoke via build, curl, unit
  and integration tests only; UI review is Justin's, against the frozen design
  contract.
- **Secrets never in git or logs.** API keys (for example `OPENALEX_API_KEY`), the
  safety dump, and any real email address stay out of the repo, out of logs, and
  out of these docs. Reference secrets by variable name and escrow location,
  never by value.

## Assets

Everything is on the tank server unless stated. None of the originals are
modified.

- **Legacy checkout:** `/opt/stacks/scholarr`, a clone of Forgejo
  `justinzeus/scholarr-legacy` at commit `f501ea4`, the last commit before
  development stopped (Python FastAPI + Vue, ~120 commits 2026-02-16 to
  2026-03-07). Its `.backup/`, `.experiment/` and `design/` directories are
  locally git-excluded via `.git/info/exclude`.
- **Rewrite checkout:** `/opt/stacks/scholarr-rewrite`. Primary
  `https://github.com/JustinZeus/scholarr` (`origin`), Forgejo copy
  `https://git.justintime.lol/justinzeus/scholarr` (`forgejo`). Bootstrap
  completion commit `ba7592e`.
- **Safety dump (the seed dataset):**
  `/opt/stacks/scholarr/.backup/scholarr-pgdump-20260721.dump`, ~6.3 MB
  `pg_dump` custom format, verified restorable. **Contains real email
  addresses.** Locally git-excluded and must never be committed or published
  anywhere.
- **Frozen UI spec (FROZEN 2026-07-22):** `/opt/stacks/scholarr-rewrite/design/`,
  holding `DESIGN.md` (the contract), `tokens.css`, `component-reference.html`,
  `assets/` and `reference/`. `reference/support.js` is proof-only and never
  ships. Review records stay in the git-excluded legacy `design/` directory.
- **Calibration workspace:** `/opt/stacks/scholarr/.experiment/`, git-excluded,
  cache-first and resumable.

**The legacy dataset is an identity seed and a partial floor, not ground truth.**
492 followed-author rows collapsing to 253 distinct people, 25,698 publications,
~47k author-to-publication links, last successful crawl 2026-03-12. It was
harvested by a scraper that was already being blocked, enrichment was half done,
and **97 profiles never completed a baseline crawl**. Calibrate against it; do
not treat it as correct or complete.

## The spec freeze gate

The data-model spec at `docs/specs/data-model.md` is **reviewed and revised but
not frozen**. Its Card C.1 independent architecture review (2026-07-23, four
adversarial dimensions over the `e36e486` draft) returned **NO-FREEZE with seven
blockers**, all spec-text gaps rather than design flaws, and the revision
applying every finding is committed at `a8c5939`.

Freezing means the owner has answered **D1 through D7** (D2 split into D2a-D2d),
approved any resulting edits, and marked the spec frozen. **No implementation and
no Card C.2 work begins before that freeze.** That rule is not enforced by
convention any more: the implementation issue carries real Forgejo dependencies
on all seven decision issues, so Forgejo itself refuses to close it while any
decision is open.

The **UI spec is already frozen** and needs no freeze card.

## Related

- [identity-calibration.md](identity-calibration.md), the calibration method and
  its completed results.
- [identity-model.md](identity-model.md), the identity and duplicate-prevention
  decision record. Its deterministic merge-target rule governs every author
  merge, so the survivor is not assumed to be the already-followed record.
- [testing-strategy.md](testing-strategy.md), the testing strategy and release
  gates decision record.
- Work tracking doctrine: `server-docs/runbooks/tracking/charter.md`.
