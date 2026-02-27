---
title: Ingestion Pipeline
sidebar_position: 5
---

# Ingestion Pipeline

The `ScholarIngestionService` drives the primary data acquisition loop. Google Scholar uses heavy bot protection, so the pipeline includes nuanced backoff strategies to protect user networks from IP bans.

## Pipeline Overview

1. The scheduler (or a manual trigger) starts a **run** for one or more scholars.
2. The service connects via HTTPX with strict browser headers.
3. Paginated HTML feeds are downloaded for each scholar profile.
4. A regex + DOM-invariant parser (`gsc_vcd_cib` selectors) extracts publication blocks.
5. Publications are fingerprinted and deduplicated against the global store.
6. External APIs resolve additional identifiers.
7. The PDF resolution pipeline runs asynchronously for publications with known DOIs.

## Rate Limiting & Backoff

### Network Errors

Handled via `INGESTION_NETWORK_ERROR_RETRIES` (default: 1) with base backoff of `INGESTION_RETRY_BACKOFF_SECONDS` (default: 1.0s).

### HTTP 429 (Rate Limited)

When the parser detects `BLOCKED_OR_CAPTCHA` with `blocked_http_429_rate_limited`, a dedicated cooldown applies:

- Retries: `INGESTION_RATE_LIMIT_RETRIES` (default: 3)
- Backoff per retry: `INGESTION_RATE_LIMIT_BACKOFF_SECONDS` (default: 30s)

This pauses the pipeline gracefully instead of failing the entire run.

### Safety Cooldowns

Threshold-based cooldowns halt all ingestion after repeated failures:

| Threshold | Variable | Default | Cooldown |
|-----------|----------|---------|----------|
| Blocked failures | `INGESTION_ALERT_BLOCKED_FAILURE_THRESHOLD` | 1 | 1800s (30 min) |
| Network failures | `INGESTION_ALERT_NETWORK_FAILURE_THRESHOLD` | 2 | 900s (15 min) |

## Continuation Queue

Multi-page ingestion uses a continuation queue to spread load over time:

- `INGESTION_CONTINUATION_QUEUE_ENABLED` (default: `1`)
- Base delay: `INGESTION_CONTINUATION_BASE_DELAY_SECONDS` (default: 120s)
- Max delay: `INGESTION_CONTINUATION_MAX_DELAY_SECONDS` (default: 3600s)
- Max attempts: `INGESTION_CONTINUATION_MAX_ATTEMPTS` (default: 6)

Each continuation item is re-enqueued with exponential backoff.

## Identifier Resolution

After publication extraction, the `gather_identifiers_for_publication` module resolves identifiers:

1. **Local parsing** - Searches HTML parameters for DOI patterns and arXiv regex matches.
2. **arXiv API** - Queries `export.arxiv.org/api/query` by title and author strings.
3. **Crossref API** - Queries Crossref REST API by title and author strings.

Identifiers are stored in the `publication_identifiers` table rather than as hardcoded properties, maximizing matching resilience for the PDF resolution stage.

## PDF Resolution

Publications with resolved DOIs enter the PDF resolution pipeline:

1. **Unpaywall** - Queries the Unpaywall API for open-access PDF URLs.
2. **PDF Discovery** - If Unpaywall returns an OA page URL without a direct PDF link, the service fetches the HTML and searches for PDF link candidates.
3. **arXiv Direct** - If an arXiv ID is known, the PDF URL is derived directly.

Auto-retry is configured via `PDF_AUTO_RETRY_*` variables.

## arXiv Request Controls

- **Global throttle**: arXiv calls share `arxiv_runtime_state` so all workers respect one cooldown/interval clock.
- **Query cache**: Identical request parameters are fingerprinted and cached in `arxiv_query_cache_entries`.
- **In-flight coalescing**: Duplicate concurrent misses join one outbound request.
- **Load shedding**: arXiv lookups are skipped when high-confidence DOI/arXiv evidence already exists, or when title quality is below threshold.

### Observability Events

| Event | Description |
|-------|-------------|
| `arxiv.request_scheduled` | Emitted before a gated request. Includes `wait_seconds`, `cooldown_remaining_seconds`, `source_path`. |
| `arxiv.request_completed` | Emitted after response. Includes `status_code`, `wait_seconds`, `source_path`. |
| `arxiv.cooldown_activated` | Emitted when status `429` triggers cooldown. |
| `arxiv.cache_hit` / `arxiv.cache_miss` | Emitted on query cache lookup with `source_path`. |
