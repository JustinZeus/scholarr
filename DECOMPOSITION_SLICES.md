# Scholarr Decomposition Slices

## How to use this file

This file contains self-contained decomposition prompts ("slices") to bring the codebase into compliance with `agents.md` file size rules. Each slice is an independent task for an LLM executor.

**Rules from `agents.md`:**
- File length: 400 lines target, 600 lines hard ceiling
- Slightly exceeding the 600-line ceiling is acceptable when the excess is driven by verbose keyword-argument signatures (named parameters), not by business logic density
- Function length: 50 lines max
- All business logic in `app/services/<domain>/`
- Read `agents.md` fully before starting any slice

**Execution protocol:**
1. Pick the next incomplete slice in order (slices depend on prior ones)
2. Read the prompt section — it contains everything you need
3. Read all source files mentioned before making changes
4. Make the changes described — no business logic changes, only file reorganization
5. Verify: all imports resolve, all tests pass
6. Commit with the specified message

---

## Progress

| # | Slice | Status |
|---|-------|--------|
| 1 | Schema split | **DONE** |
| 2 | Ingestion: pagination + publication upsert | **DONE** |
| 3 | Ingestion: enrichment + scholar processing + run completion | **DONE** |
| 4 | Scholars service + PDF queue | **DONE** |
| 5 | Routers + scheduler | pending |

---

## Slice 1: Split `app/api/schemas.py` into domain packages — DONE

Completed. The 945-line `app/api/schemas.py` was split into `app/api/schemas/` package:

| File | Lines | Contents |
|---|---|---|
| `common.py` | 39 | `ApiMeta`, `ApiErrorData`, `ApiErrorEnvelope`, `MessageData`, `MessageEnvelope` |
| `auth.py` | 73 | `SessionUserData`, `AuthMe*`, `CsrfBootstrap*`, `Login*`, `ChangePasswordRequest` |
| `scholars.py` | 153 | `ScholarItem*`, `ScholarSearch*`, `ScholarExport*`, `DataExport*`, `DataImport*` |
| `publications.py` | 151 | `DisplayIdentifierData`, `PublicationItem*`, `MarkAll*`, `MarkSelected*`, `RetryPublication*`, `TogglePublication*` |
| `runs.py` | 226 | `RunListItem*`, `RunSummary*`, `RunDebug*`, `RunScholarResult*`, `RunDetail*`, `ManualRun*`, `Queue*`, `ScrapeSafety*` |
| `admin.py` | 289 | All `Admin*` models including PDF queue, repair, near-duplicate schemas |
| `settings.py` | 54 | `SettingsPolicy*`, `Settings*`, `SettingsUpdateRequest` |
| `__init__.py` | 7 | Wildcard re-exports — all `from app.api.schemas import X` imports unchanged |

---

## Slice 2: Decompose `app/services/ingestion/application.py` — pagination + publication upsert — DONE

Completed. Extracted three modules from `application.py` (2,955 → 2,084 lines):

| File | Lines | Contents |
|---|---|---|
| `app/services/ingestion/page_fetch.py` | 219 | `PageFetcher` class — single-page fetch, parse-or-layout-error, retry with backoff |
| `app/services/ingestion/pagination.py` | 486 | `PaginationEngine` class — multi-page orchestration, loop state, short-circuit, fingerprint checks |
| `app/services/ingestion/publication_upsert.py` | 239 | Module-level functions — `resolve_publication`, `upsert_profile_publications`, find/create/update helpers |

Also fixed two external import paths (`portability/normalize.py`, `portability/publication_import.py`) that imported `normalize_title`/`build_publication_url` from `application.py` — now correctly sourced from `fingerprints.py`. Updated one integration test to monkeypatch the new module-level function instead of the old instance method.

---

## Slice 3: Decompose `app/services/ingestion/application.py` — enrichment, scholar processing, run completion — DONE

Completed. Extracted four logical chunks from `application.py` (2,085 → 635 lines):

| File | Lines | Contents |
|---|---|---|
| `app/services/ingestion/enrichment.py` | 323 | `EnrichmentRunner` class — OpenAlex enrichment, identifier discovery, dedup sweep |
| `app/services/ingestion/scholar_processing.py` | 614 | `process_scholar`, `run_scholar_iteration`, continuation queue, outcome resolution |
| `app/services/ingestion/run_completion.py` | 417 | `complete_run_for_user`, failure summary, alert summary, safety outcome, progress tracking |

Also updated two tests (`test_ingestion_arxiv_rate_limit.py`, `test_ingestion_progress_reporting.py`) and one integration test (`test_deferred_enrichment.py`) to import from new modules.

**Why:** Three remaining logical chunks. Extracting all three brings `application.py` down to ~500 lines (the orchestration spine).

**Files to create:** `app/services/ingestion/enrichment.py`, `app/services/ingestion/scholar_processing.py`, `app/services/ingestion/run_completion.py`

**Files to modify:** `app/services/ingestion/application.py`

**Prompt:**

You are working on the scholarr repository. Read `agents.md` for project conventions. Continue decomposing `app/services/ingestion/application.py` (slice 2 is complete — `page_fetch.py`, `pagination.py`, and `publication_upsert.py` already extracted). Extract three remaining chunks.

**A. `app/services/ingestion/enrichment.py` (~300 lines)**

Move these methods (post-run OpenAlex enrichment):

- `_run_is_canceled`, `_enrich_pending_publications`, `_discover_identifiers_for_enrichment`
- `_publish_identifier_update_event`, `_enrich_publications_with_openalex`

Create an `EnrichmentRunner` class that receives service dependencies (OpenAlex client, identifier service, dedup service, DB session factory) in its constructor.

**B. `app/services/ingestion/scholar_processing.py` (~400 lines)**

Move these methods (per-scholar outcome resolution):

- `_assert_valid_paged_parse_result`, `_apply_first_page_profile_metadata`, `_build_result_entry`
- `_skipped_no_change_outcome`, `_upsert_publications_outcome`, `_upsert_success_or_exception`
- `_upsert_success`, `_upsert_exception_outcome`, `_parse_failure_outcome`
- `_sync_continuation_queue`, `_process_scholar`, `_process_scholar_inner`
- `_fetch_and_prepare_scholar_result`, `_resolve_scholar_outcome`, `_unexpected_scholar_exception_outcome`

These become methods on a `ScholarProcessor` class or module-level functions.

**C. `app/services/ingestion/run_completion.py` (~300 lines)**

Move these methods (run finalization + alerting):

- `_classify_failure_bucket` (standalone function)
- `_summarize_failures`, `_build_alert_summary`, `_apply_safety_outcome`, `_finalize_run_record`
- `_resolve_run_status`, `_resolve_continuation_queue_target`, `_build_failure_debug_context`
- `_complete_run_for_user`

These become module-level functions accepting explicit parameters.

**After all extractions, `application.py` should contain only:**

- `ScholarIngestionService.__init__` and config helpers
- Run lifecycle: `initialize_run`, `execute_run`, `run_for_user`
- Scholar iteration orchestration: `_run_scholar_iteration`
- Progress tracking: `_result_counters`, `_adjust_progress_counts`
- Safety gate integration, background task management

Target: `application.py` ≤ 500 lines. No new file exceeds 400 lines. All tests must pass unchanged.

Commit message: `refactor: extract enrichment, scholar processing, and run completion from ingestion service`

---

## Slice 4: Decompose `app/services/scholars/application.py` (996 lines) and `app/services/publications/pdf_queue.py` (969 lines) — DONE

Completed. Extracted four modules from two oversized service files:

| File | Lines | Contents |
|---|---|---|
| `app/services/scholars/author_search_cache.py` | 239 | Serialize/deserialize cache entries, cache get/set/prune |
| `app/services/scholars/author_search.py` | 580 | Cooldown, throttle, retry, circuit breaker, `search_author_candidates` |
| `app/services/scholars/application.py` | 221 | Scholar CRUD only (list, create, get, toggle, delete, image ops) |
| `app/services/publications/pdf_queue_queries.py` | 395 | SQL builders, row hydration, listing/counting/pagination, retry item builders |
| `app/services/publications/pdf_queue_resolution.py` | 311 | Task execution, outcome persistence, scheduling (`schedule_rows`) |
| `app/services/publications/pdf_queue.py` | 364 | Dataclasses, constants, enqueueing logic, public API |

Also updated one test file (`test_publication_pdf_queue_policy.py`) to monkeypatch `pdf_queue_resolution` instead of `pdf_queue` for the 4 resolution-related tests, and updated `publications/application.py` and `publication_identifiers/application.py` imports.

**Prompt:**

You are working on the scholarr repository. Read `agents.md` for project conventions. Two service files exceed the 600-line ceiling. Decompose both.

**A. `app/services/scholars/application.py` (996 lines)**

This file mixes scholar CRUD (~350 lines) with the entire author search pipeline (~650 lines). Split them:

Create `app/services/scholars/author_search_cache.py` (~150 lines): Move all `_serialize_*` and `_deserialize_*` functions. Move `_cache_get_author_search_result`, `_cache_set_author_search_result`, `_prune_author_search_cache`. These are pure functions operating on the DB cache table.

Create `app/services/scholars/author_search.py` (~500 lines): Move remaining author search functions — cooldown management, throttle logic, retry wrappers, circuit breaker, lock acquisition, and `search_author_candidates`. Import cache functions from `author_search_cache.py`. Accept DB session and settings as explicit parameters.

Update `application.py`: Keep only scholar CRUD methods. Import and delegate to `search_author_candidates` from `author_search.py`. Target: ≤ 350 lines.

**B. `app/services/publications/pdf_queue.py` (969 lines)**

Three concerns in one file. Split by concern:

Create `app/services/publications/pdf_queue_queries.py` (~330 lines): Move SQL query builders (`_tracked_queue_select_base`, `_tracked_queue_select`, etc.), result hydration (`_queue_item_from_row`, `_hydrated_queue_items`), listing/counting/pagination (`list_pdf_queue_items`, `count_pdf_queue_items`, `list_pdf_queue_page`), retry item builders and missing-PDF candidate queries.

Create `app/services/publications/pdf_queue_resolution.py` (~300 lines): Move task execution (`_mark_attempt_started`, `_failed_outcome`, `_fetch_outcome_for_row`), outcome persistence (`_apply_publication_update`, `_apply_job_outcome`, `_persist_outcome`), scheduling (`_resolve_publication_row`, `_run_resolution_task`, `_register_task`, `_drop_finished_task`, `_schedule_rows`).

Keep in `pdf_queue.py` (~340 lines): dataclasses, constants, enqueueing logic, public API.

No file should exceed 500 lines. All tests must pass unchanged.

Commit message: `refactor: decompose scholars service and pdf_queue into focused modules`

---

## Slice 5: Decompose router files and scheduler

**Why:** Three files slightly over the 600-line ceiling. Each needs helper extraction.

**Files to create:** `app/api/routers/run_serializers.py`, `app/api/routers/run_manual.py`, `app/api/routers/scholar_helpers.py`, `app/services/ingestion/queue_runner.py`

**Files to modify:** `app/api/routers/runs.py` (875 → ~405), `app/api/routers/scholars.py` (616 → ~396), `app/services/ingestion/scheduler.py` (622 → ~280)

**Prompt:**

You are working on the scholarr repository. Read `agents.md` for project conventions. Three files are slightly over the 600-line ceiling. Extract helpers from each.

**A. `app/api/routers/runs.py` (875 lines) → 3 files**

Create `app/api/routers/run_serializers.py` (~250 lines): Move all `_serialize_*`, `_normalize_*`, `_int_value`, `_str_value`, `_bool_value` helper functions. Move `_manual_run_payload_from_run` and `_manual_run_success_payload`.

Create `app/api/routers/run_manual.py` (~220 lines): Move `_load_safety_state`, `_raise_manual_runs_disabled`, `_reused_manual_run_payload`, `_run_ingestion_for_manual`, `_recover_integrity_error`, `_execute_manual_run`, `_raise_manual_blocked_safety`, `_raise_manual_failed`.

Keep in `runs.py` (~405 lines): only route handler functions + imports.

**B. `app/api/routers/scholars.py` (616 lines) → 2 files**

Create `app/api/routers/scholar_helpers.py` (~220 lines): Move `_needs_metadata_hydration`, `_is_create_hydration_rate_limited`, `_auto_enqueue_new_scholar_enabled`, `_enqueue_initial_scrape_job_for_scholar`, `_uploaded_image_media_path`, `_serialize_scholar`, `_hydrate_scholar_metadata_if_needed`, `_search_kwargs`, `_search_response_data`, `_read_uploaded_image`, `_require_user_profile`.

Keep in `scholars.py` (~396 lines): only route handlers.

**C. `app/services/ingestion/scheduler.py` (622 lines) → 2 files**

Create `app/services/ingestion/queue_runner.py` (~350 lines): Move all continuation-queue job processing — `_drain_continuation_queue`, `_drop_queue_job_if_max_attempts`, `_mark_queue_job_retrying`, `_queue_job_has_available_scholar`, all `_reschedule_*` methods, `_run_ingestion_for_queue_job`, `_finalize_queue_job_after_run`, `_run_queue_job`. Create a `QueueJobRunner` class receiving config params in constructor.

Keep in `scheduler.py` (~280 lines): auto-run scheduling, `_run_loop`, `_tick_once`, candidate loading.

All tests must pass unchanged after each extraction.

Commit message: `refactor: extract helpers from oversized router and scheduler files`

---

## Verification (after all slices)

```bash
# No Python file exceeds 600 lines
find app/ -name "*.py" -exec wc -l {} + | awk '$1 > 600 && !/total/ {print "FAIL:", $0}'

# All tests pass
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app python -m pytest

# Linting
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app ruff check .
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app ruff format --check .
```
