---
title: Configuration
sidebar_position: 3
---

# Configuration

All configuration is done through environment variables. Copy `.env.example` to `.env` and adjust values as needed.

## Compose & Database

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `POSTGRES_DB` | string | `scholar` | PostgreSQL database name |
| `POSTGRES_USER` | string | `scholar` | PostgreSQL user |
| `POSTGRES_PASSWORD` | string | **required** | PostgreSQL password |
| `DATABASE_URL` | string | derived | SQLAlchemy async connection string |
| `TEST_DATABASE_URL` | string | derived | Override for test database. If empty, tests derive `<db_name>_test` |
| `SCHOLARR_IMAGE` | string | `justinzeus/scholarr:latest` | Docker image for the app service |

## App Runtime & Networking

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `APP_NAME` | string | `scholarr` | Application name used in logs and headers |
| `APP_HOST` | string | `0.0.0.0` | Bind address |
| `APP_PORT` | int | `8000` | Internal port |
| `APP_HOST_PORT` | int | `8000` | Host-mapped port |
| `APP_RELOAD` | bool | `0` | Enable uvicorn auto-reload (dev only) |
| `MIGRATE_ON_START` | bool | `1` | Run Alembic migrations on startup |
| `FRONTEND_ENABLED` | bool | `1` | Serve the built Vue frontend |
| `FRONTEND_DIST_DIR` | string | `/app/frontend/dist` | Path to compiled frontend assets |

## Database Pool

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `DATABASE_POOL_MODE` | string | `auto` | Pool mode (`auto`, `fixed`, `null`) |
| `DATABASE_POOL_SIZE` | int | `5` | Base pool size |
| `DATABASE_POOL_MAX_OVERFLOW` | int | `10` | Maximum overflow connections |
| `DATABASE_POOL_TIMEOUT_SECONDS` | int | `30` | Connection acquisition timeout |

## Frontend Dev Overrides

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `FRONTEND_HOST_PORT` | int | `5173` | Host port for Vite dev server |
| `CHOKIDAR_USEPOLLING` | bool | `1` | Enable polling for file watchers in containers |
| `VITE_DEV_API_PROXY_TARGET` | string | `http://app:8000` | Backend URL for Vite proxy |

## Auth & Session

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SESSION_SECRET_KEY` | string | **required** | Signing key for session cookies (32+ chars) |
| `SESSION_COOKIE_SECURE` | bool | `1` | Set `Secure` flag on session cookie (disable for local HTTP dev) |
| `LOGIN_RATE_LIMIT_ATTEMPTS` | int | `5` | Max login attempts per window |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | int | `60` | Sliding window for login rate limiting |

## HTTP Security Headers & CSP

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SECURITY_HEADERS_ENABLED` | bool | `1` | Enable security response headers |
| `SECURITY_X_CONTENT_TYPE_OPTIONS` | string | `nosniff` | X-Content-Type-Options header value |
| `SECURITY_X_FRAME_OPTIONS` | string | `DENY` | X-Frame-Options header value |
| `SECURITY_REFERRER_POLICY` | string | `strict-origin-when-cross-origin` | Referrer-Policy header value |
| `SECURITY_PERMISSIONS_POLICY` | string | *(restrictive)* | Permissions-Policy header value |
| `SECURITY_CROSS_ORIGIN_OPENER_POLICY` | string | `same-origin` | Cross-Origin-Opener-Policy header |
| `SECURITY_CROSS_ORIGIN_RESOURCE_POLICY` | string | `same-origin` | Cross-Origin-Resource-Policy header |
| `SECURITY_CSP_ENABLED` | bool | `1` | Enable Content-Security-Policy header |
| `SECURITY_CSP_POLICY` | string | *(restrictive)* | CSP for app routes |
| `SECURITY_CSP_DOCS_POLICY` | string | *(docs-specific)* | CSP for documentation routes |
| `SECURITY_CSP_REPORT_ONLY` | bool | `0` | Use report-only mode for CSP |
| `SECURITY_STRICT_TRANSPORT_SECURITY_ENABLED` | bool | `0` | Enable HSTS header |
| `SECURITY_STRICT_TRANSPORT_SECURITY_MAX_AGE` | int | `31536000` | HSTS max-age in seconds |
| `SECURITY_STRICT_TRANSPORT_SECURITY_INCLUDE_SUBDOMAINS` | bool | `1` | HSTS includeSubDomains directive |
| `SECURITY_STRICT_TRANSPORT_SECURITY_PRELOAD` | bool | `0` | HSTS preload directive |

## Logging

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `LOG_LEVEL` | string | `INFO` | Root log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `LOG_FORMAT` | string | `console` | Log format (`console` or `json`) |
| `LOG_REQUESTS` | bool | `1` | Log HTTP requests |
| `LOG_UVICORN_ACCESS` | bool | `0` | Enable uvicorn access log |
| `LOG_REQUEST_SKIP_PATHS` | string | `/healthz` | Comma-separated paths to exclude from request logging |
| `LOG_REDACT_FIELDS` | string | *(empty)* | Comma-separated field names to redact in logs |

## Scheduler & Ingestion Safety

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SCHEDULER_ENABLED` | bool | `1` | Enable the background scheduler |
| `SCHEDULER_TICK_SECONDS` | int | `60` | Scheduler poll interval |
| `SCHEDULER_QUEUE_BATCH_SIZE` | int | `10` | Max scholars processed per tick |
| `SCHEDULER_PDF_QUEUE_BATCH_SIZE` | int | `15` | Max PDF resolutions per tick |
| `INGESTION_AUTOMATION_ALLOWED` | bool | `1` | Allow automated (scheduled) runs |
| `INGESTION_MANUAL_RUN_ALLOWED` | bool | `1` | Allow manually triggered runs |
| `INGESTION_MIN_RUN_INTERVAL_MINUTES` | int | `15` | Minimum time between runs |
| `INGESTION_MIN_REQUEST_DELAY_SECONDS` | int | `2` | Floor delay between external requests |
| `INGESTION_NETWORK_ERROR_RETRIES` | int | `1` | Retries on network errors |
| `INGESTION_RETRY_BACKOFF_SECONDS` | float | `1.0` | Base backoff for network retries |
| `INGESTION_RATE_LIMIT_RETRIES` | int | `3` | Retries on 429 responses |
| `INGESTION_RATE_LIMIT_BACKOFF_SECONDS` | float | `30.0` | Backoff per 429 retry |
| `INGESTION_MAX_PAGES_PER_SCHOLAR` | int | `30` | Max paginated pages per scholar |
| `INGESTION_PAGE_SIZE` | int | `100` | Publications per page |
| `INGESTION_ALERT_BLOCKED_FAILURE_THRESHOLD` | int | `1` | Blocked failures before alert |
| `INGESTION_ALERT_NETWORK_FAILURE_THRESHOLD` | int | `2` | Network failures before alert |
| `INGESTION_ALERT_RETRY_SCHEDULED_THRESHOLD` | int | `3` | Scheduled retries before alert |
| `INGESTION_SAFETY_COOLDOWN_BLOCKED_SECONDS` | int | `1800` | Cooldown after blocked-failure threshold (30 min) |
| `INGESTION_SAFETY_COOLDOWN_NETWORK_SECONDS` | int | `900` | Cooldown after network-failure threshold (15 min) |
| `INGESTION_CONTINUATION_QUEUE_ENABLED` | bool | `1` | Enable continuation queue for multi-page ingestion |
| `INGESTION_CONTINUATION_BASE_DELAY_SECONDS` | int | `120` | Base delay for continuation queue items |
| `INGESTION_CONTINUATION_MAX_DELAY_SECONDS` | int | `3600` | Max delay for continuation queue items |
| `INGESTION_CONTINUATION_MAX_ATTEMPTS` | int | `6` | Max continuation attempts per scholar |

## Scholar Images & Name Search Safety

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SCHOLAR_IMAGE_UPLOAD_DIR` | string | `/var/lib/scholarr/uploads` | Directory for uploaded scholar images |
| `SCHOLAR_IMAGE_UPLOAD_MAX_BYTES` | int | `2000000` | Max image upload size (2 MB) |
| `SCHOLAR_NAME_SEARCH_ENABLED` | bool | `1` | Enable name-based scholar search |
| `SCHOLAR_NAME_SEARCH_CACHE_TTL_SECONDS` | int | `21600` | Cache TTL for successful searches (6 hours) |
| `SCHOLAR_NAME_SEARCH_BLOCKED_CACHE_TTL_SECONDS` | int | `300` | Cache TTL for blocked search results (5 min) |
| `SCHOLAR_NAME_SEARCH_CACHE_MAX_ENTRIES` | int | `512` | Max cache entries for name search |
| `SCHOLAR_NAME_SEARCH_MIN_INTERVAL_SECONDS` | float | `8.0` | Min interval between name searches |
| `SCHOLAR_NAME_SEARCH_INTERVAL_JITTER_SECONDS` | float | `2.0` | Random jitter added to search interval |
| `SCHOLAR_NAME_SEARCH_COOLDOWN_BLOCK_THRESHOLD` | int | `1` | Blocked results before cooldown |
| `SCHOLAR_NAME_SEARCH_COOLDOWN_SECONDS` | int | `1800` | Cooldown after blocked name search (30 min) |
| `SCHOLAR_NAME_SEARCH_ALERT_RETRY_COUNT_THRESHOLD` | int | `2` | Retries before alert |
| `SCHOLAR_NAME_SEARCH_ALERT_COOLDOWN_REJECTIONS_THRESHOLD` | int | `3` | Cooldown rejections before alert |

## OA Enrichment & PDF Resolution

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `UNPAYWALL_ENABLED` | bool | `1` | Enable Unpaywall DOI lookups |
| `UNPAYWALL_EMAIL` | string | *(empty)* | Polite pool email for Unpaywall API |
| `UNPAYWALL_TIMEOUT_SECONDS` | float | `4.0` | Request timeout |
| `UNPAYWALL_MIN_INTERVAL_SECONDS` | float | `0.6` | Min interval between Unpaywall requests |
| `UNPAYWALL_MAX_ITEMS_PER_REQUEST` | int | `20` | Max items per batch |
| `UNPAYWALL_RETRY_COOLDOWN_SECONDS` | int | `1800` | Cooldown after repeated failures |
| `UNPAYWALL_PDF_DISCOVERY_ENABLED` | bool | `1` | Enable HTML-based PDF link discovery |
| `UNPAYWALL_PDF_DISCOVERY_MAX_CANDIDATES` | int | `5` | Max candidate URLs to probe |
| `UNPAYWALL_PDF_DISCOVERY_MAX_HTML_BYTES` | int | `500000` | Max HTML response size to parse |
| `ARXIV_ENABLED` | bool | `1` | Enable arXiv API lookups |
| `ARXIV_TIMEOUT_SECONDS` | float | `3.0` | Request timeout |
| `ARXIV_MIN_INTERVAL_SECONDS` | float | `4.0` | Min interval between arXiv requests |
| `ARXIV_RATE_LIMIT_COOLDOWN_SECONDS` | float | `60.0` | Cooldown after arXiv 429 |
| `ARXIV_DEFAULT_MAX_RESULTS` | int | `3` | Default max results per query |
| `ARXIV_CACHE_TTL_SECONDS` | int | `900` | Query cache TTL (15 min) |
| `ARXIV_CACHE_MAX_ENTRIES` | int | `512` | Max cached queries |
| `ARXIV_MAILTO` | string | *(empty)* | Contact email for arXiv API headers |
| `PDF_AUTO_RETRY_INTERVAL_SECONDS` | int | `86400` | Auto-retry interval for failed PDFs (24 hours) |
| `PDF_AUTO_RETRY_FIRST_INTERVAL_SECONDS` | int | `3600` | First retry interval (1 hour) |
| `PDF_AUTO_RETRY_MAX_ATTEMPTS` | int | `3` | Max auto-retry attempts |
| `CROSSREF_ENABLED` | bool | `1` | Enable Crossref lookups |
| `CROSSREF_MAX_ROWS` | int | `10` | Max rows per Crossref query |
| `CROSSREF_TIMEOUT_SECONDS` | float | `8.0` | Request timeout |
| `CROSSREF_MIN_INTERVAL_SECONDS` | float | `0.6` | Min interval between Crossref requests |
| `CROSSREF_MAX_LOOKUPS_PER_REQUEST` | int | `8` | Max lookups per ingestion request |
| `OPENALEX_API_KEY` | string | *(empty)* | OpenAlex API key (optional) |
| `CROSSREF_API_TOKEN` | string | *(empty)* | Crossref Plus API token (optional) |
| `CROSSREF_API_MAILTO` | string | *(empty)* | Crossref polite pool email |

## Startup Bootstrap & DB Wait

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `BOOTSTRAP_ADMIN_ON_START` | bool | `0` | Create admin user on startup |
| `BOOTSTRAP_ADMIN_EMAIL` | string | *(empty)* | Admin email address |
| `BOOTSTRAP_ADMIN_PASSWORD` | string | *(empty)* | Admin password |
| `BOOTSTRAP_ADMIN_FORCE_PASSWORD` | bool | `0` | Overwrite existing admin password |
| `DB_WAIT_TIMEOUT_SECONDS` | int | `60` | Max seconds to wait for database readiness |
| `DB_WAIT_INTERVAL_SECONDS` | int | `2` | Poll interval while waiting for database |
