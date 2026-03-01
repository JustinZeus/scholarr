---
title: Local Development
sidebar_position: 3
---

# Local Development

## Prerequisites

- Docker and Docker Compose v2+
- Python 3.12+ (for IDE support and local linting)
- Node.js 20+ (for frontend development)

## Starting the Dev Stack

The development compose file overlays the production config with hot-reload and a separate Vite dev server:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

This starts three services:

| Service | Port | Description |
|---------|------|-------------|
| `db` | 5432 (internal) | PostgreSQL 15 |
| `app` | 8000 | FastAPI backend with `APP_RELOAD=1` |
| `frontend` | 5173 | Vite dev server proxying API calls to `app:8000` |

### Dev-Specific Overrides

The `docker-compose.dev.yml` file applies these changes:

- **`app`**: Uses `scholarr-dev:local` image built from the `dev` stage. Mounts the project root as `/app` for hot reload. Disables `SESSION_COOKIE_SECURE` and the built frontend.
- **`frontend`**: Node 20 container running `npm install && npm run dev`. Mounts `./frontend` with a named volume for `node_modules`. Uses polling for file watching (`CHOKIDAR_USEPOLLING=1`).

## Environment Setup

```bash
cp .env.example .env
```

Set at minimum:

```bash
POSTGRES_PASSWORD=localdev
SESSION_SECRET_KEY=local-dev-secret-at-least-32-characters
SESSION_COOKIE_SECURE=0
```

## Running Tests

All tests run inside containers:

```bash
# Run unit tests (default: excludes integration markers)
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app \
  python -m pytest

# Run integration tests
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app \
  python -m pytest -m integration

# Run a specific test file
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app \
  python -m pytest tests/unit/test_fingerprints.py -v
```

See [Testing](testing.md) for markers, fixtures, and conventions.

## Linting and Type Checking

```bash
# Ruff linting
ruff check .

# Ruff formatting check
ruff format --check .

# Mypy type checking
mypy app/
```

Ruff config is in `pyproject.toml`: target Python 3.12, line length 120, rules `E F W I UP B SIM RUF`.

## Database Migrations

Alembic migrations run automatically on startup when `MIGRATE_ON_START=1`. To run manually:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app \
  alembic upgrade head
```

To create a new migration:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app \
  alembic revision --autogenerate -m "description of change"
```
