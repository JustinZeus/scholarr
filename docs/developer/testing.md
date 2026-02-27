---
title: Testing
sidebar_position: 7
---

# Testing

## Running Tests

All tests must run inside containers:

```bash
# Unit tests (default: excludes integration markers)
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app \
  python -m pytest

# Integration tests
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app \
  python -m pytest -m integration

# Specific marker
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app \
  python -m pytest -m db

# Verbose output for a specific file
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app \
  python -m pytest tests/unit/test_fingerprints.py -v
```

## Test Configuration

From `pyproject.toml`:

```toml
[tool.pytest.ini_options]
addopts = "-q -m \"not integration\" --import-mode=importlib"
asyncio_mode = "auto"
testpaths = ["tests"]
```

- Default run excludes `integration` marked tests
- Uses `importlib` import mode to resolve module name collisions
- Async tests run automatically (no `@pytest.mark.asyncio` needed)

## Markers

| Marker | Description |
|--------|-------------|
| `integration` | Tests requiring external services (database, network) |
| `db` | Tests that validate database behavior and constraints |
| `migrations` | Tests focused on Alembic schema migration correctness |
| `schema` | Tests focused on multi-tenant schema invariants |
| `smoke` | Smoke tests for containerized runtime |

## Test Tiers

### Unit Tests (`tests/unit/`)

Fast, no-database tests. Mock external dependencies. These run by default.

Examples:
- `test_fingerprints.py` - Publication fingerprinting logic
- `test_scholar_parser.py` - HTML parsing without network calls
- `test_doi_normalize.py` - DOI normalization rules
- `test_ingestion_arxiv_rate_limit.py` - Rate limiter behavior
- `test_publication_pdf_resolution_pipeline.py` - PDF pipeline logic

Domain-specific unit tests are organized under `tests/unit/services/domains/`:
- `arxiv/` - Cache, client, gateway, guards, parser, rate limit tests
- `openalex/` - Client and matching tests
- `publications/` - Dedup tests

### Integration Tests (`tests/integration/`)

Require a running database. Test full request/response flows and data consistency.

Examples:
- `test_api_v1.py` - API endpoint integration tests
- `test_db_integrity.py` - Database integrity checks
- `test_run_lifecycle_consistency.py` - Run state machine transitions
- `test_deferred_enrichment.py` - Enrichment pipeline with real data
- `test_fixture_probe_runs.py` - Fixture-based run probes

### Smoke Tests

Marked with `@pytest.mark.smoke`. Validate the containerized runtime starts and serves basic requests.

## Fixtures

Test fixtures live in `tests/fixtures/`:

```
tests/fixtures/
└── scholar/
    ├── profile_ok_amIMrIEAAAAJ.html          # Successful profile HTML
    └── regression/
        ├── profile_P1RwlvoAAAAJ.html         # Regression case
        ├── profile_LZ5D_p4AAAAJ.html         # Regression case
        └── profile_AAAAAAAAAAAA.html         # Regression case
```

Scholar HTML fixtures are real Google Scholar profile pages used to test parser robustness against DOM structure changes.
