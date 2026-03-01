---
title: arXiv Runbook
sidebar_position: 5
---

# arXiv Operations Runbook

Use this runbook when arXiv lookups are slow, rate-limited, or behaving unexpectedly.

## Signals to Check

- Logs for `arxiv.request_scheduled`, `arxiv.request_completed`, `arxiv.cooldown_activated`, `arxiv.cache_hit`, `arxiv.cache_miss`
- `arxiv_runtime_state` row for cooldown and next-allowed timestamps
- `arxiv_query_cache_entries` size and expiry churn

## Event Field Guide

| Field | Description |
|-------|-------------|
| `wait_seconds` | Enforced pre-request delay from the global limiter |
| `status_code` | Upstream response code from arXiv |
| `cooldown_remaining_seconds` | Remaining cooldown when blocked or after 429 |
| `source_path` | Caller path (`search` or `lookup_ids`) |

## Quick SQL Checks

### Runtime State

```sql
SELECT state_key, next_allowed_at, cooldown_until, updated_at
FROM arxiv_runtime_state;
```

### Cache Status

```sql
SELECT count(*) AS cache_rows,
       min(expires_at) AS earliest_expiry,
       max(expires_at) AS latest_expiry
FROM arxiv_query_cache_entries;
```

## Common Scenarios

### 1. Repeated `arxiv.cooldown_activated` Events

- Confirm recent `429` statuses in `arxiv.request_completed` logs.
- Reduce caller pressure (check title-quality/identifier guards are active).
- Temporarily raise `ARXIV_RATE_LIMIT_COOLDOWN_SECONDS` if upstream remains strict.

### 2. High Request Latency with Few Completions

- Inspect `wait_seconds` in `arxiv.request_scheduled`.
- Verify only one process path is repeatedly hitting arXiv (`source_path`).
- Confirm cache is enabled (`ARXIV_CACHE_TTL_SECONDS > 0`) and effective (`cache_hit` appears).

### 3. Low Cache Effectiveness

- Validate normalized query behavior and caller churn.
- Increase `ARXIV_CACHE_TTL_SECONDS` for stable workloads.
- Increase `ARXIV_CACHE_MAX_ENTRIES` if heavy eviction is observed.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ARXIV_ENABLED` | `1` | Enable arXiv lookups |
| `ARXIV_TIMEOUT_SECONDS` | `3.0` | Request timeout |
| `ARXIV_MIN_INTERVAL_SECONDS` | `4.0` | Min interval between requests |
| `ARXIV_RATE_LIMIT_COOLDOWN_SECONDS` | `60.0` | Cooldown after 429 |
| `ARXIV_DEFAULT_MAX_RESULTS` | `3` | Max results per query |
| `ARXIV_CACHE_TTL_SECONDS` | `900` | Cache TTL (15 min) |
| `ARXIV_CACHE_MAX_ENTRIES` | `512` | Max cached queries |
| `ARXIV_MAILTO` | *(empty)* | Contact email for API headers |

## Safe Recovery

1. Pause automated ingestion if rate-limit storms persist.
2. Let cooldown expire naturally; avoid manual burst retries.
3. Resume and monitor event rates before restoring full load.
