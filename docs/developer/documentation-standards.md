# Documentation Standards

This project keeps docs organized by audience and document type.

## Audience Split

- `user/`: onboarding and usage tasks for self-hosted users.
- `operations/`: runbooks and checklists for production operation.
- `developer/`: architecture, contribution workflow, and implementation guides.
- `reference/`: stable contracts (API, env variables, configuration behavior).

## Document Quality Rules

- One primary audience per page.
- Task pages must include prerequisites, exact commands, and verification steps.
- Reference pages should be contract-first and avoid procedural noise.
- Runbooks should include recovery steps and rollback/safety notes.
- Prefer concise pages with strong cross-links over long mixed-purpose pages.

## Required Top-Level Entrypoints

- `index.md`: user/developer/operator navigation hub.
- `user/getting-started.md`: first-run path.
- `developer/local-development.md`: contributor setup and validation path.
- `operations/overview.md`: operational playbook index.
- `reference/overview.md`: contract index.
