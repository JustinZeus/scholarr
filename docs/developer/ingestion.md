# Ingestion System & Backoff Strategies

The `ScholarIngestionService` drives the primary data acquisition loop. Since Google Scholar utilizes heavy bot protection and rate limits, this package contains nuanced backoffs to protect user networks from automated IP bans.

## Ingestion Overview
The underlying ingestion process:
1. Receives an explicit request or background cron trigger to resolve a `scholar_profile_id`.
2. Connects asynchronously using configured HTTPX adapters with strict browser headers.
3. Downloads the paginated HTML feed for a user across multiple page iterations.
4. Uses `regex` and DOM-invariants (e.g. `gsc_vcd_cib`) to pull individual publication blocks.

## Handling 429 Too Many Requests
Google Scholar aggressively throws HTTP 429 responses if multiple concurrent tabs or rapidly sequential commands query the same IP address for specific API endpoints (like `citations?view_op=view_citation...`). 

Scholarr treats these distinct from random network timeouts.
- **Network Error Retries**: Handled via `ingestion_network_error_retries` with a base backoff of `ingestion_retry_backoff_seconds` (Default 1.0s).
- **Rate Limit 429 Retries**: When `ParseState.BLOCKED_OR_CAPTCHA` captures `blocked_http_429_rate_limited`, the system applies a dedicated cooldown. It respects `ingestion_rate_limit_retries` multiplied by `ingestion_rate_limit_backoff_seconds` (Default 30.0s). This prevents the pipeline from fatalizing a user's job completely, pausing operations seamlessly instead.

## Publication Identifiers Loop
Once a publication is built, the `gather_identifiers_for_publication` module isolates keys explicitly.
- **Local Parsing**: Searches for direct identifiers within the HTML parameters (DOI patterns, arXiv regexes).
- **API Fetching**: Queries secondary bibliographic platforms sequentially:
  - `export.arxiv.org/api/query` (Queries by Title and Author strings).
  - `crossref.restful` APIs (Queries by Title and Author strings).

These identifiers are accumulated in `publication_identifiers` instead of being bound as hard-coded properties, maximizing matching resilience in the automated Unpaywall PDF acquisition stage.

## arXiv Request Controls
- **Global throttle state**: arXiv calls share `arxiv_runtime_state` so all workers respect one cooldown/interval clock.
- **Query cache**: identical request parameters map to a stable fingerprint and are stored in `arxiv_query_cache_entries`.
- **In-flight coalescing**: duplicate concurrent misses join one outbound request instead of fan-out.
- **Caller load-shedding**: arXiv lookups are skipped when high-confidence DOI/arXiv evidence already exists, or when title quality is below threshold.

## arXiv Observability Events
- `arxiv.request_scheduled`: emitted before a gated request; includes `wait_seconds`, `cooldown_remaining_seconds`, `source_path`.
- `arxiv.request_completed`: emitted after response; includes `status_code`, `wait_seconds`, `cooldown_remaining_seconds`, `source_path`.
- `arxiv.cooldown_activated`: emitted when status `429` triggers cooldown.
- `arxiv.cache_hit` / `arxiv.cache_miss`: emitted on query cache lookup with `source_path`.
