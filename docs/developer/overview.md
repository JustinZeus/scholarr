---
title: Developer Overview
sidebar_position: 1
---

# Developer Overview

Scholarr is a Python 3.12+ FastAPI backend with an async SQLAlchemy ORM layer, PostgreSQL database, and a Vue 3 + TypeScript + Vite frontend.

## Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.12+, FastAPI, SQLAlchemy 2.0 (async/asyncpg), Alembic |
| Frontend | TypeScript, Vue 3, Vite, Tailwind CSS |
| Database | PostgreSQL 15 |
| Infrastructure | Multi-stage Docker, Docker Compose |
| Linting | ruff (E, F, W, I, UP, B, SIM, RUF), mypy |
| Testing | pytest, pytest-asyncio |
| Versioning | python-semantic-release, conventional commits |

## Quick Start

```bash
# Build the dev image and start services
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

# Backend: http://localhost:8000 (hot reload enabled)
# Frontend: http://localhost:5173 (Vite dev server with API proxy)
```

See [Local Development](local-development.md) for the full setup guide.

## Project Layout

```
app/
├── api/routers/          # FastAPI route handlers
├── auth/                 # Session + CSRF middleware
├── db/                   # SQLAlchemy models, session factory, migrations
├── services/             # Domain service modules (see Architecture)
│   ├── arxiv/            # arXiv API client, cache, rate limiting
│   ├── crossref/         # Crossref DOI lookups
│   ├── dbops/            # Database integrity + repair operations
│   ├── ingestion/        # Run orchestration, scheduler, safety gates
│   ├── openalex/         # OpenAlex metadata matching
│   ├── portability/      # Import/export workflows
│   ├── publication_identifiers/  # Multi-identifier resolution
│   ├── publications/     # Listing, enrichment, dedup, PDF queue
│   ├── runs/             # Run history, continuation queue
│   ├── scholar/          # HTML parser, source fetch adapters
│   ├── scholars/         # Scholar CRUD, image upload, name search
│   └── unpaywall/        # Unpaywall PDF discovery
├── main.py               # App factory, lifespan, middleware stack
frontend/
├── src/
│   ├── components/       # Reusable Vue components
│   ├── theme/presets/    # Color theme presets (light + dark)
│   └── ...
scripts/db/               # Operational database scripts
tests/
├── unit/                 # Fast, no-database tests
├── integration/          # Tests requiring database + services
└── fixtures/             # Shared test fixtures
```
