---
title: Deployment
sidebar_position: 2
---

# Deployment

## Production Docker Compose

The default `docker-compose.yml` runs two services:

| Service | Image | Description |
|---------|-------|-------------|
| `db` | `postgres:15-alpine` | PostgreSQL database with persistent volume |
| `app` | `justinzeus/scholarr:latest` | FastAPI application with embedded frontend |

### Start

```bash
docker compose up -d
```

### Stop

```bash
docker compose down
```

### Update

```bash
docker compose pull
docker compose up -d
```

### View Logs

```bash
docker compose logs -f app
docker compose logs -f db
```

## Required Environment Variables

These must be set in `.env` or the shell environment:

```bash
POSTGRES_PASSWORD=<secure-password>
SESSION_SECRET_KEY=<random-string-32-chars-minimum>
```

## Volumes

| Volume | Mount | Description |
|--------|-------|-------------|
| `postgres_data` | `/var/lib/postgresql/data` | Database files |
| `scholar_uploads` | `/var/lib/scholarr/uploads` | Scholar profile images |

## Health Checks

### Database

```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U $POSTGRES_USER -d $POSTGRES_DB"]
  interval: 5s
  timeout: 5s
  retries: 20
```

### Application

```yaml
healthcheck:
  test: ["CMD-SHELL", "curl -fsS http://localhost:8000/healthz >/dev/null || exit 1"]
  interval: 10s
  timeout: 5s
  retries: 12
```

The app service depends on `db` with `condition: service_healthy`, so it waits for the database to be ready.

## Database Readiness Wait

The app has built-in database readiness polling:

- `DB_WAIT_TIMEOUT_SECONDS` (default: 60) - Max wait time
- `DB_WAIT_INTERVAL_SECONDS` (default: 2) - Poll interval

## Auto-Migration

Set `MIGRATE_ON_START=1` (default) to run Alembic migrations automatically on startup.

## Scaling Considerations

- Run a single `app` instance to avoid scheduler conflicts (the scheduler is process-local).
- arXiv requests are globally serialized via a PostgreSQL advisory lock, so multiple instances safely share the rate limiter.
- Database pool defaults: 5 base connections + 10 overflow. Adjust `DATABASE_POOL_SIZE` and `DATABASE_POOL_MAX_OVERFLOW` for higher loads.

## Admin Bootstrap

For first-time setup without manual database access:

```bash
BOOTSTRAP_ADMIN_ON_START=1
BOOTSTRAP_ADMIN_EMAIL=admin@example.com
BOOTSTRAP_ADMIN_PASSWORD=<secure-password>
```

Set `BOOTSTRAP_ADMIN_FORCE_PASSWORD=1` to reset an existing admin password.

## Security Hardening

- Set `SESSION_COOKIE_SECURE=1` when serving over HTTPS.
- Enable HSTS: `SECURITY_STRICT_TRANSPORT_SECURITY_ENABLED=1`.
- Review CSP policy in `SECURITY_CSP_POLICY` for your domain.
- Set `UNPAYWALL_EMAIL` and `ARXIV_MAILTO` for polite API pool access.
