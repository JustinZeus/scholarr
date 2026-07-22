# Scholarr

Scholarr is a self-hosted author watchlist and publication tracker. Follow researchers, learn
when they publish, and find legal open-access copies of their work.

The rewrite is pre-alpha. Its product direction and interface are settled, and the architecture
specs are being frozen before implementation begins.

## Non-negotiable rule

Scholarr never makes network requests to Google Scholar or any other Google endpoint. Imported
Scholar IDs and URLs are inert metadata and human-clickable links only. Publication data comes
from documented APIs such as OpenAlex, Crossref, arXiv, Unpaywall, and ORCID.

## Technical direction

- Go backend
- Vue frontend
- SQLite only
- Multi-user, with a globally deduplicated publication store and per-user follow/read state
- Internal auth, generic OIDC, and trusted-header auth in v1
- Config-driven operation and simple first-run onboarding

See [AGENTS.md](AGENTS.md) for the full project constraints and [TASKS.md](TASKS.md) for the
ordered work queue.

## Frozen interface contract

The reviewed interface contract is in [design/DESIGN.md](design/DESIGN.md). Its tokens, component
reference, icons, logos, favicons, and proof implementation are checked in beside it. These files
are the source for the Vue port, not an application implementation.

## License

The license has not been selected yet. Until a LICENSE file is added, normal copyright rules
apply. License selection is an explicit project decision in [TASKS.md](TASKS.md).
