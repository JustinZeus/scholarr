---
title: Environment Variables
sidebar_position: 3
---

# Environment Variables Quick Reference

All environment variables are documented in detail in [Configuration](../user/configuration.md).

## Required Variables

| Variable | Description |
|----------|-------------|
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `SESSION_SECRET_KEY` | Session cookie signing key (32+ characters) |

## Categories

| Category | Key Variables |
|----------|--------------|
| Database | `POSTGRES_DB`, `POSTGRES_USER`, `DATABASE_URL`, `DATABASE_POOL_*` |
| Runtime | `APP_HOST`, `APP_PORT`, `MIGRATE_ON_START`, `FRONTEND_ENABLED` |
| Auth | `SESSION_SECRET_KEY`, `SESSION_COOKIE_SECURE`, `LOGIN_RATE_LIMIT_*` |
| Security | `SECURITY_HEADERS_ENABLED`, `SECURITY_CSP_*`, `SECURITY_STRICT_TRANSPORT_*` |
| Logging | `LOG_LEVEL`, `LOG_FORMAT`, `LOG_REQUESTS` |
| Scheduler | `SCHEDULER_ENABLED`, `SCHEDULER_TICK_SECONDS`, `SCHEDULER_*_BATCH_SIZE` |
| Ingestion | `INGESTION_*` (safety floors, cooldowns, retry policies) |
| Scholar | `SCHOLAR_IMAGE_*`, `SCHOLAR_NAME_SEARCH_*` |
| Enrichment | `UNPAYWALL_*`, `ARXIV_*`, `CROSSREF_*`, `OPENALEX_*`, `PDF_AUTO_RETRY_*` |
| Bootstrap | `BOOTSTRAP_ADMIN_*`, `DB_WAIT_*` |

See [Configuration](../user/configuration.md) for the complete table with types, defaults, and descriptions.
