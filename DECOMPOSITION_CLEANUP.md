# Decomposition Cleanup — 3-Pass Fix Prompt

You are working on the scholarr repository (`feat/decomposition` branch). A decomposition refactor split oversized files into focused modules. An audit found residual issues. Fix them in 3 sequential passes.

**Read `agents.md` before starting.** Key rules:
- Function length: 50 lines max
- File length: 400 target, 600 hard ceiling (kwargs-heavy signatures are acceptable overage)
- No dead code, no duplicate boilerplate, no backward-compatibility shims
- All business logic in `app/services/<domain>/`
- Use `structured_log()` for domain logging

**Constraints for every pass:**
- Pure refactoring — no behavioral changes
- All tests must pass after each pass: `docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app python -m pytest`
- Commit after each pass using conventional commit format

---

## Pass 1: Naming, DRY, and Dead Code

**1a. Rename `_int_or_default` → `int_or_default`**

This function in `app/services/ingestion/run_completion.py:38` is imported externally by `app/services/ingestion/application.py:25`, making it public API with a private-convention name.

- Rename the definition in `run_completion.py` (line 38)
- Update all internal call sites in `run_completion.py` (lines 71, 350, 375)
- Update the import in `application.py` (line 25) and call sites (lines 138, 336, 342)

**1b. Consolidate duplicate functions between `pdf_queue.py` and `pdf_queue_resolution.py`**

Three functions exist with identical signatures in both files:

| Function | `pdf_queue.py` | `pdf_queue_resolution.py` |
|---|---|---|
| `_utcnow()` | line 46 | line 33 |
| `_event_row()` | line 150 | line 39 |
| `_queued_job()` | line 165 | line 60 |

Fix: Keep these in `pdf_queue.py` (the parent module). Have `pdf_queue_resolution.py` import them from `pdf_queue.py`. Since `pdf_queue.py` already imports from `pdf_queue_resolution.py`, check for circular imports — if importing `_utcnow`, `_event_row`, `_queued_job` from `pdf_queue` into `pdf_queue_resolution` would create a cycle, extract them to a shared `pdf_queue_common.py` instead.

Also deduplicate the PDF status constants (`PDF_STATUS_QUEUED`, `PDF_STATUS_RUNNING`, `PDF_STATUS_RESOLVED`, `PDF_STATUS_FAILED`) that are duplicated between `pdf_queue.py` (lines 23-27) and `pdf_queue_resolution.py` (lines 20-23). Keep them in `pdf_queue.py` only.

**1c. Consolidate `_effective_request_delay_seconds` duplication**

`scheduler.py` (lines 32-42) and `queue_runner.py` (line 23-28) both define `_effective_request_delay_seconds` with slightly different signatures. The `queue_runner.py` version takes an explicit `floor` parameter (cleaner). Keep the `queue_runner.py` version. In `scheduler.py`, delete `_request_delay_floor_seconds()` and `_effective_request_delay_seconds()`, and instead import from `queue_runner`:

```python
from app.services.ingestion.queue_runner import _effective_request_delay_seconds
```

At the call site in `scheduler.py`, pass `floor=_request_delay_floor_seconds_value` where needed (inline the floor computation or keep it as a one-liner).

Actually — since `_effective_request_delay_seconds` would now be imported externally, rename it to `effective_request_delay_seconds` (drop the underscore) in `queue_runner.py`.

Commit message: `refactor: fix naming, remove duplicate code from decomposition`

---

## Pass 2: Function length — ingestion core (6 worst offenders)

All 6 functions are >75 lines. Extract helpers to bring each under 50 lines. Below is specific guidance for each.

**2a. `EnrichmentRunner.enrich_pending_publications` — 133 lines → ≤50** (`enrichment.py:47-179`)

This function does 4 things: load publications, set up client, batch-loop with API calls, run dedup sweep. Extract:

1. `_load_unenriched_publications(db_session, *, run_id) → list[Publication]` — lines 66-87 (query + return)
2. `_enrich_batch(self, db_session, *, batch, run_id, client, openalex_works, now) → bool` — lines 142-166 (per-publication enrichment loop; return False if canceled). This inner loop iterates `batch`, calls `_discover_identifiers_for_enrichment`, and applies the match. The caller handles the outer batch loop and API call.
3. `_flush_and_sweep_duplicates(db_session, *, run_id)` — lines 167-179 (flush + dedup sweep)

The main function becomes: load pubs → early return → create client → batch loop (API call + `_enrich_batch`) → `_flush_and_sweep_duplicates`.

**2b. `EnrichmentRunner.enrich_publications_with_openalex` — 64 lines → ≤50** (`enrichment.py:260-323`)

Extract:
1. `_sanitize_titles(publications) → list[str]` — lines 279-286 (title cleaning loop)

The outer batch loop + match logic stays in the main method, which should now fit in ~45 lines.

**2c. `ScholarIngestionService.run_for_user` — 99 lines → ≤50** (`application.py:525-623`)

This function calls `initialize_run`, builds paging/threshold kwargs, calls `run_scholar_iteration`, `complete_run_for_user`, handles enrichment, commits, and logs. Extract:

1. `_run_iteration_and_complete(self, db_session, *, run, scholars, user_id, start_cstart_map, paging, thresholds, auto_queue_continuations, queue_delay_seconds, idempotency_key) → tuple[RunProgress, RunFailureSummary, RunAlertSummary]` — lines 579-599 (the iteration + completion block). This calls `run_scholar_iteration` and `complete_run_for_user` and returns their results.
2. `_inline_enrich_and_finalize(self, db_session, *, run, user_settings, intended_final_status) → None` — lines 604-614 (enrichment + status fixup + commit). This calls `enrich_pending_publications`, handles the exception, fixes status, and commits.

**2d. `ScholarIngestionService.execute_run` — 88 lines → ≤50** (`application.py:374-461`)

Extract:
1. `_execute_run_body(self, db_session, session_factory, *, run_id, user_id, scholars, start_cstart_map, paging, thresholds, auto_queue_continuations, queue_delay_seconds, idempotency_key) → None` — lines 411-457 (the try-body: prepare, iterate, complete, commit, log, spawn enrichment task). The outer `execute_run` handles kwargs resolution and the `async with session_factory()` + `except`.

Or alternatively, the `_resolve_paging_kwargs` / `_threshold_kwargs` calls can be lifted into the caller or inlined since they're trivial dict builders — this alone may shave enough lines. Consider whether the kwargs signature itself is the bulk (it is — 22 lines of signature). If so, this function may be acceptable as-is per the kwargs-exception rule. Use your judgment: if the function body (excluding signature and kwargs resolution) is ≤50 lines, document it as acceptable and move on.

**2e. `run_scholar_iteration` — 84 lines → ≤50** (`scholar_processing.py:531-614`)

This has two clear phases: pass 1 (breadth-first, lines 560-584) and pass 2 (depth, lines 586-614). Extract:

1. `_run_first_pass(db_session, *, scholars, pagination, run, user_id, start_cstart_map, scholar_kwargs, request_delay_seconds, queue_delay_seconds, progress) → dict[int, int]` — the breadth-first loop (lines 560-584), returns `first_pass_cstarts`
2. `_run_depth_pass(db_session, *, scholars, first_pass_cstarts, pagination, run, user_id, scholar_kwargs, request_delay_seconds, remaining_max, auto_queue_continuations, queue_delay_seconds, progress) → None` — the depth loop (lines 591-613)

The main function becomes: build kwargs → call pass 1 → compute remaining → call pass 2 → return progress.

**2f. `QueueJobRunner._finalize_queue_job_after_run` — 79 lines → ≤50** (`queue_runner.py:284-362`)

Two branches: success path (lines 287-311) and failure path (lines 312-362). Extract:

1. `_finalize_successful_queue_job(self, session, job, run_summary) → None` — success path
2. `_finalize_failed_queue_job(self, session, job, run_summary) → None` — failure path

The main function opens a session, branches on `failed_count`, and delegates.

Commit message: `refactor: extract helpers from long functions in ingestion core`

---

## Pass 3: Function length — remaining violations (10 functions, 58-75 lines)

**3a. `run_manual` — 105 lines → ≤50** (`app/api/routers/runs.py:183-287`)

This route handler has a large try block. Extract:

1. `_start_manual_run(db_session, *, current_user, ingest_service, idempotency_key) → tuple[CrawlRun, list, dict]` — lines 205-221 (initialize_run call with all the settings kwargs)
2. `_spawn_background_execution(ingest_service, *, run, current_user, scholars, start_cstart_map, user_settings, idempotency_key) → None` — lines 226-249 (create_task + background_tasks management)
3. `_manual_run_success_response(request, *, run, idempotency_key, db_session, current_user) → dict` — lines 251-265 (build success payload)

The route handler becomes: load safety → check disabled → check idempotency → try: start → spawn → respond; except: handle errors.

**3b. `PaginationEngine._paginate_loop` — 75 lines → ≤50** (`pagination.py:276-350`)

Extract:
1. `_upsert_page_publications(self, db_session, *, run, scholar, publications, seen_canonical, state, upsert_publications_fn)` — the dedup + upsert block (appears twice: lines 294-302 and 339-347). Deduplicate by extracting a single helper called from both places.

This should bring the loop body under 50 lines.

**3c. `PaginationEngine.fetch_and_parse_all_pages` — 72 lines → ≤50** (`pagination.py:415-486`)

Most of the length is the kwargs-heavy calls. Check if the function body (excluding the 17-line signature) is ≤50 lines — it should be ~55. Extract:
1. Move the `_short_circuit_initial_page` + `_build_loop_state` + `_paginate_loop` + `_result_from_pagination_state` sequence into a helper `_paginate_from_initial_page(self, *, scholar, run, db_session, state, ...) → PagedParseResult` if needed. Or accept this as kwargs-acceptable overage and document why.

**3d. `PageFetcher.fetch_and_parse_with_retry` — 70 lines → ≤50** (`page_fetch.py:148-217`)

Extract:
1. `_classify_attempt(parsed_page, *, network_attempts, rate_limit_attempts) → tuple[int, int, int]` — lines 173-183 (attempt counter logic, returns updated network_attempts, rate_limit_attempts, total_attempts)

This plus the existing `_should_retry` and `_sleep_backoff` helpers should bring the loop under 50 lines.

**3e. `complete_run_for_user` — 66 lines → ≤50** (`run_completion.py:265-330`)

Extract:
1. `_log_alert_threshold_warnings(*, user_id, run, failure_summary, alert_summary) → None` — lines 284-313 (the 3 if-blocks that log threshold warnings)

The main function becomes: summarize → build alerts → log warnings → apply safety → resolve status → finalize → return. ~35 lines.

**3f. `process_scholar` — 61 lines → ≤50** (`scholar_processing.py:343-403`)

The function body is mostly kwargs pass-through. Check if the actual body (excluding the 18-line signature) is ≤50 lines — it's ~43 lines of body. If so, this is acceptable under the kwargs exception. Document and move on.

**3g. `_fetch_and_prepare_scholar_result` — 59 lines → ≤50** (`scholar_processing.py:406-464`)

Same analysis: 16-line signature, 43-line body. If the body alone is ≤50, this is kwargs-acceptable. Document and move on.

**3h. `_perform_live_author_search` — 60 lines → ≤50** (`author_search.py:459-518`)

18-line signature, 42-line body. Kwargs-acceptable. Document and move on.

**3i. `search_author_candidates` — 60 lines → ≤50** (`author_search.py:521-580`)

19-line signature, 41-line body. Kwargs-acceptable. Document and move on.

**3j. `ScholarIngestionService.initialize_run` — 58 lines → ≤50** (`application.py:315-372`)

20-line signature, 38-line body. Kwargs-acceptable. Document and move on.

Commit message: `refactor: extract helpers from remaining long functions`

---

## Verification (after all 3 passes)

```bash
# No function exceeds 50 lines (body, excluding kwargs signatures that exceed the limit)
# Run the AST checker from the audit to verify

# All tests pass
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app python -m pytest

# Linting
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app ruff check .
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app ruff format --check .

# Type checking
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app mypy app/
```
