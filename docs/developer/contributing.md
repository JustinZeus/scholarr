---
title: Contributing
sidebar_position: 4
---

# Contributing

## PR Process

1. Create a feature branch from `main`.
2. Make your changes following the code standards below.
3. Run tests inside the container (see [Testing](testing.md)).
4. Run `ruff check .` and `mypy app/` to catch lint and type errors.
5. Open a pull request with a clear title and description.

## Commit Conventions

This project uses [Conventional Commits](https://www.conventionalcommits.org/) with [python-semantic-release](https://python-semantic-release.readthedocs.io/) for automated versioning.

Commit message format:

```
<type>(<scope>): <description>

[optional body]
```

Types: `feat`, `fix`, `docs`, `ci`, `refactor`, `test`, `chore`, `perf`.

Examples:
- `feat(scholars): add bulk import from CSV`
- `fix(ingestion): handle empty citation blocks`
- `docs: update configuration reference`

## Code Standards

### Function Length

Maximum 50 lines per function. Break complex logic into small, testable, single-responsibility functions.

### DRY

Abstract repetitive logic immediately. No duplicate boilerplate for database queries, API responses, or error handling.

### Negative Space Programming

Use explicit assertions and constraints to define invalid states. Fail fast and early. Do not allow silent failures or cascading malformed data, especially in DOM parsing.

### Cyclomatic Complexity

Flatten logic. Use early returns and guard clauses instead of deep nesting. No magic numbers.

### Domain Service Boundaries

All business logic resides in `app/services/<domain>/`. Flat files in the `app/services/` root are strictly prohibited. Each domain owns its own application service, types, and helpers.

### API Envelope

All `/api/v1` responses use the strict envelope format:

- Success: `{"data": ..., "meta": {"request_id": "..."}}`
- Error: `{"error": {"code": "...", "message": "...", "details": ...}, "meta": {"request_id": "..."}}`

### Data Isolation

- Scholar tracking is user-scoped.
- Publications are global, deduplicated records.
- Read/favorite/visibility state lives on scholar-publication link rows.

### Scrape Safety

Rate limits and cooldowns are immutable constraints. They prevent IP bans and must not be optimized away or set to zero.

## UI Standards

- Integrate Tailwind with the preset theming system (`frontend/src/theme/presets/`).
- Every UI element must have a clear purpose.
- Clarity through both styling and language.
