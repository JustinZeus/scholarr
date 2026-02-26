# arXiv Operations Runbook

Use this runbook when arXiv lookups are slow, rate-limited, or behaving unexpectedly.

## Signals To Check
- logs for `arxiv.request_scheduled`, `arxiv.request_completed`, `arxiv.cooldown_activated`, `arxiv.cache_hit`, `arxiv.cache_miss`
- `arxiv_runtime_state` row for cooldown and next-allowed timestamps
- `arxiv_query_cache_entries` size and expiry churn

## Event Field Guide
- `wait_seconds`: enforced pre-request delay from the global limiter.
- `status_code`: upstream response code from arXiv.
- `cooldown_remaining_seconds`: remaining cooldown when blocked or after 429.
- `source_path`: caller path (`search` or `lookup_ids`).

## Quick SQL Checks
```sql
SELECT state_key, next_allowed_at, cooldown_until, updated_at
FROM arxiv_runtime_state;
```

```sql
SELECT count(*) AS cache_rows, min(expires_at) AS earliest_expiry, max(expires_at) AS latest_expiry
FROM arxiv_query_cache_entries;
```

## Common Scenarios
1. Repeated `arxiv.cooldown_activated` events:
- Confirm recent `429` statuses in `arxiv.request_completed`.
- Reduce caller pressure (check new title-quality/identifier guards are active).
- Temporarily raise `ARXIV_RATE_LIMIT_COOLDOWN_SECONDS` if upstream remains strict.

2. High request latency with few completions:
- Inspect `wait_seconds` in `arxiv.request_scheduled`.
- Verify only one process path is repeatedly hitting arXiv (`source_path`).
- Confirm cache is enabled (`ARXIV_CACHE_TTL_SECONDS > 0`) and effective (`cache_hit` appears).

3. Low cache effectiveness:
- Validate normalized query behavior and caller churn.
- Increase `ARXIV_CACHE_TTL_SECONDS` for stable workloads.
- Increase `ARXIV_CACHE_MAX_ENTRIES` if heavy eviction is observed.

## Safe Recovery
1. Pause automated ingestion if rate-limit storms persist.
2. Let cooldown expire naturally; avoid manual burst retries.
3. Resume and monitor event rates before restoring full load.
