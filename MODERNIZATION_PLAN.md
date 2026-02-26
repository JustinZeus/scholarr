# Scholarr Modernization Plan — Slices 2-10

> **Slice 1 is complete** (commit `7736cab`): removed 114 stale `build/` files, fixed `.gitignore`, committed pending deletions, replaced `npm install` with `npm ci` in CI.
>
> Each slice below is a self-contained prompt designed for an LLM executor. Execute in order — each slice depends on the prior ones being complete.

---

## Slice 2: Create `structured_log()` Utility

**Why:** The codebase has 19 `_log_*` helper functions (422 lines) and 138 instances of duplicated `"event"` keys in logging calls. A single utility eliminates all of it.

**Files to create:**
- `app/logging_utils.py`

**Files to modify:**
- `tests/unit/test_logging.py`

**Context files (read but don't modify):**
- `app/logging_config.py` — line 88 has `"event": getattr(record, "event", record.getMessage())` which means when no `event` key is in `extra`, it falls back to `getMessage()`. This is the mechanism that makes `structured_log()` work without duplicating the event name.
- `app/logging_context.py`

**Prompt:**
```
You are working on the scholarr repository. The current logging pattern has a DRY problem:

1. Every log call duplicates the event name as both the message and in extra["event"]:
   `logger.info("event.name", extra={"event": "event.name", "key": value})`

2. There are 19 `_log_*` helper functions (422 lines total) that just wrap logger calls with typed signatures to build extra dicts.

3. Metrics data (metric_name/metric_value) is mixed into log extra dicts but has no consumer.

Create `app/logging_utils.py`:

```python
"""Structured logging utility — eliminates boilerplate across domain services."""

from __future__ import annotations

import logging
from typing import Any


def structured_log(
    logger: logging.Logger,
    level: str,
    event: str,
    /,
    **fields: Any,
) -> None:
    """Emit a structured log entry.

    The event name is passed as the log message. The JsonLogFormatter in
    logging_config.py extracts it via record.getMessage() when no explicit
    'event' key exists in extra — so we do NOT duplicate it.

    Usage:
        structured_log(logger, "info", "ingestion.run_started", user_id=1, scholar_count=5)
    """
    fields.pop("metric_name", None)
    fields.pop("metric_value", None)

    log_method = getattr(logger, level.lower())
    log_method(event, extra=fields)
```

Verify that `app/logging_config.py` line 88 already handles this correctly — when no `event` key is in extra, it falls back to getMessage() which returns the event string passed as the first argument. No changes to logging_config.py should be needed.

Add tests in `tests/unit/test_logging.py` (append to existing file):
- Test that `structured_log()` produces a log record where the JsonLogFormatter outputs the event name correctly
- Test that `structured_log()` works with ConsoleLogFormatter
- Test that metric_name/metric_value fields are stripped from output
- Test that extra fields (user_id, scholar_id, etc.) appear in the formatted output

Commit message: "refactor: add structured_log utility to eliminate logging boilerplate"
```

---

## Slice 3: Migrate Ingestion Logging to `structured_log()`

**Why:** `app/services/domains/ingestion/application.py` is 3,089 lines. 8 `_log_*` helpers consume ~239 lines. 34 inline logger calls duplicate event names and include dead metric fields. This slice removes ~300 lines.

**Files to modify:**
- `app/services/domains/ingestion/application.py`

**Context files:**
- `app/logging_utils.py` (created in Slice 2)

**Prompt:**
```
You are working on the scholarr repository. The file `app/services/domains/ingestion/application.py` (3,089 lines) has 8 `_log_*` helper functions consuming ~239 lines, plus 34 inline logger calls with duplicated `"event":` keys and mixed `metric_name`/`metric_value` fields.

Migrate ALL logging in this file to use `structured_log()` from `app.logging_utils`.

1. Add `from app.logging_utils import structured_log` at the top.

2. Delete these 8 helper methods entirely:
   - `_log_request_delay_coercion` (line ~123, 21 lines)
   - `_log_run_started` (line ~310, 36 lines)
   - `_log_scholar_parsed` (line ~383, 28 lines)
   - `_log_alert_thresholds` (line ~1013, 47 lines)
   - `_log_safety_transition` (line ~1093, 42 lines)
   - `_log_run_completed` (line ~1178, 28 lines)
   - `_attempt_log_entry` (line ~1837, 16 lines)
   - `_page_log_entry` (line ~1999, 21 lines)

3. Replace every call to these deleted helpers with an inline `structured_log()` call. Example:

   Before:
   ```python
   self._log_run_started(
       user_id=user_id,
       trigger_type=trigger_type,
       scholar_count=scholar_count,
       ...
   )
   ```

   After:
   ```python
   structured_log(
       logger, "info", "ingestion.run_started",
       user_id=user_id,
       trigger_type=trigger_type.value,
       scholar_count=scholar_count,
       ...
   )
   ```

4. For ALL remaining inline `logger.info/warning/debug/exception()` calls:
   - Replace with `structured_log()` where the call uses `extra={"event": ..., ...}` pattern
   - Do NOT convert `logger.exception()` calls — keep them but remove the duplicated `"event"` key from their extra dict
   - Remove `metric_name` and `metric_value` from all calls

5. Do NOT change any business logic. Only logging call sites.

Expected outcome: ~300 lines removed. All existing tests must pass unchanged.

Commit message: "refactor: migrate ingestion service logging to structured_log"
```

---

## Slice 4: Migrate All Remaining Services to `structured_log()`

**Why:** 11 more `_log_*` helpers remain across 8 files (183 lines total), plus inline logger calls with the same duplication pattern in ~20 files.

**Files to modify (all have `_log_*` helpers to delete):**
- `app/services/domains/ingestion/scheduler.py` — `_log_queue_item_resolved` (line ~518, 21 lines)
- `app/services/domains/arxiv/rate_limit.py` — `_log_request_scheduled` (199), `_log_request_completed` (216), `_log_cooldown_activated` (235)
- `app/services/domains/arxiv/client.py` — `_log_cache_event` (283), `_log_request_skipped_for_cooldown` (299)
- `app/services/domains/publications/pdf_resolution_pipeline.py` — `_log_arxiv_skip` (148)
- `app/services/domains/unpaywall/application.py` — `_log_resolution_summary` (194)
- `app/api/routers/publications.py` — `_log_retry_pdf_result` (343)
- `app/api/routers/settings.py` — `_log_settings_update` (103)
- `app/main.py` — `_log_startup_build_marker` (53)

**Files to modify (inline `extra={"event":...}` pattern only — no helpers to delete):**
- `app/http/middleware.py`
- `app/db/session.py`
- `app/auth/runtime.py`
- `app/security/csrf.py`
- `app/api/routers/scholars.py`
- `app/api/routers/runs.py`
- `app/api/routers/admin_dbops.py`
- `app/api/routers/admin.py`
- `app/api/routers/auth.py`
- `app/api/routers/publications.py`
- `app/services/domains/scholars/application.py`
- `app/services/domains/runs/events.py`
- `app/services/domains/openalex/client.py`
- `app/services/domains/openalex/matching.py`
- `app/services/domains/crossref/application.py`
- `app/services/domains/publications/dedup.py`
- `app/services/domains/publications/enrichment.py`
- `app/services/domains/publications/pdf_queue.py`
- `app/services/domains/scholar/source.py`
- `app/services/domains/arxiv/gateway.py`

**Prompt:**
```
You are working on the scholarr repository. Slice 3 migrated `ingestion/application.py` to `structured_log()`. Now do the same for ALL remaining files.

1. Delete these `_log_*` helper functions and replace their call sites with inline `structured_log()`:

   - `app/services/domains/ingestion/scheduler.py:~518` — `_log_queue_item_resolved` (21 lines)
   - `app/services/domains/arxiv/rate_limit.py:~199` — `_log_request_scheduled` (17 lines)
   - `app/services/domains/arxiv/rate_limit.py:~216` — `_log_request_completed` (19 lines)
   - `app/services/domains/arxiv/rate_limit.py:~235` — `_log_cooldown_activated` (13 lines)
   - `app/services/domains/arxiv/client.py:~283` — `_log_cache_event` (16 lines)
   - `app/services/domains/arxiv/client.py:~299` — `_log_request_skipped_for_cooldown` (13 lines)
   - `app/services/domains/publications/pdf_resolution_pipeline.py:~148` — `_log_arxiv_skip` (11 lines)
   - `app/services/domains/unpaywall/application.py:~194` — `_log_resolution_summary` (21 lines)
   - `app/api/routers/publications.py:~343` — `_log_retry_pdf_result` (24 lines)
   - `app/api/routers/settings.py:~103` — `_log_settings_update` (15 lines)
   - `app/main.py:~53` — `_log_startup_build_marker` (13 lines)

2. In ALL files under `app/` that have inline `logger.info/warning/debug("event.name", extra={"event": "event.name", ...})` calls:
   - Replace with `structured_log(logger, "level", "event.name", key=value, ...)`
   - Add `from app.logging_utils import structured_log` import
   - Remove `metric_name`/`metric_value` from all calls
   - Keep `logger.exception()` calls but remove the duplicated `"event"` key from their extra dicts

3. In `app/services/domains/openalex/client.py`, the lines that log `response.text` (lines ~87, ~137):
   - Truncate: `response.text[:500]`

4. Do NOT change any business logic. Only logging call sites.

Verify: `grep -rn '"event":' app/ --include="*.py" | grep -v __pycache__` should return 0 matches.
Verify: `grep -rn 'def _log_' app/ --include="*.py"` should return 0 matches.

Commit message: "refactor: migrate all remaining logging to structured_log, remove boilerplate helpers"
```

---

## Slice 5: Logging Relevance Audit — Reduce Noise, Improve Readability

**Why:** Self-hosted users need clear, actionable logs. Current logging has verbose debug noise (per-HTTP-request, per-publication), overly long event names, and no console display optimization.

**Files to modify:**
- `app/services/domains/scholar/source.py`
- `app/services/domains/ingestion/application.py`
- `app/logging_config.py`
- Any files with event names longer than ~40 chars

**Prompt:**
```
You are working on the scholarr repository. The logging has been migrated to `structured_log()` (slices 2-4). Now audit log RELEVANCE and READABILITY for self-hosted users running this in Docker.

1. **Remove redundant debug logs:**
   - `app/services/domains/scholar/source.py`: Remove the 3 debug-level HTTP fetch events (fetch_started, search_fetch_started, publication_fetch_started). Keep only `fetch_succeeded` at DEBUG. The HTTP middleware already logs request.started/completed.
   - `app/services/domains/ingestion/application.py`: Remove per-publication `publication.discovered` and `publication.created` DEBUG logs. The run_completed summary already reports totals.

2. **Shorten overly long event names** (search all structured_log calls in app/):
   - `ingestion.request_delay_coerced_to_policy_floor` → `ingestion.delay_coerced`
   - `ingestion.safety_cooldown_cleared` → `ingestion.cooldown_cleared`
   - Any other names longer than ~40 chars — shorten while preserving meaning

3. **Improve console readability** in `app/logging_config.py` `ConsoleLogFormatter.format()`:
   - Add a short-name mapping for common context fields in console output ONLY (JSON keeps full names):
     ```python
     _CONSOLE_SHORT_KEYS = {
         "user_id": "user",
         "scholar_id": "scholar",
         "crawl_run_id": "run",
         "run_id": "run",
     }
     ```
   - Apply in the `for key in sorted(payload.keys())` loop

4. Do NOT remove any WARNING or ERROR level logs. Only remove/demote DEBUG/INFO that are redundant.
5. Do NOT change business logic.

Commit message: "refactor: reduce log noise, improve event naming and console readability"
```

---

## Slice 6: Add Ruff + Mypy to CI

**Why:** No Python linting or type checking in CI. Code quality regressions go undetected.

**Files to modify:**
- `pyproject.toml`
- `.github/workflows/ci.yml`

**Prompt:**
```
You are working on the scholarr repository. Add Python linting and type checking to CI.

1. In `pyproject.toml`, add ruff configuration:
   ```toml
   [tool.ruff]
   target-version = "py312"
   line-length = 120

   [tool.ruff.lint]
   select = ["E", "F", "W", "I", "UP", "B", "SIM", "RUF"]
   ignore = ["E501"]

   [tool.ruff.lint.isort]
   known-first-party = ["app"]
   ```

2. In `pyproject.toml`, add mypy configuration:
   ```toml
   [tool.mypy]
   python_version = "3.12"
   ignore_missing_imports = true
   check_untyped_defs = false
   warn_unused_ignores = true
   ```

3. In `.github/workflows/ci.yml`, add a `lint` job after `repo-hygiene` and before `test`:
   ```yaml
   lint:
     runs-on: ubuntu-latest
     needs: [repo-hygiene]
     steps:
       - uses: actions/checkout@v4
       - uses: actions/setup-python@v5
         with:
           python-version: "3.12"
       - uses: astral-sh/setup-uv@v4
       - run: uv sync --extra dev
       - name: Ruff check
         run: uv run ruff check .
       - name: Ruff format check
         run: uv run ruff format --check .
       - name: Mypy
         run: uv run mypy app/ --ignore-missing-imports
   ```

4. Update the `test` job's `needs` to include `lint`.

5. Add `ruff` and `mypy` to dev dependencies in `pyproject.toml` under `[project.optional-dependencies]`.

6. Run `ruff check .` locally and fix auto-fixable issues with `ruff check --fix .`. For unfixable issues, add targeted `noqa` comments only if fixing would change behavior.

Commit message: "ci: add ruff linting and mypy type checking"
```

---

## Slice 7: Add CodeQL + Dependabot

**Why:** No security scanning. Missed vulnerabilities, no automated dependency updates.

**Files to create:**
- `.github/workflows/codeql.yml`
- `.github/dependabot.yml`

**Prompt:**
```
You are working on the scholarr repository. Add security scanning.

1. Create `.github/workflows/codeql.yml`:
   ```yaml
   name: CodeQL

   on:
     push:
       branches: [main]
     pull_request:
       branches: [main]
     schedule:
       - cron: "30 5 * * 1"

   jobs:
     analyze:
       runs-on: ubuntu-latest
       permissions:
         security-events: write
         contents: read
       strategy:
         matrix:
           language: [python, javascript]
       steps:
         - uses: actions/checkout@v4
         - uses: github/codeql-action/init@v3
           with:
             languages: ${{ matrix.language }}
         - uses: github/codeql-action/autobuild@v3
         - uses: github/codeql-action/analyze@v3
   ```

2. Create `.github/dependabot.yml`:
   ```yaml
   version: 2
   updates:
     - package-ecosystem: pip
       directory: /
       schedule:
         interval: weekly
     - package-ecosystem: npm
       directory: /frontend
       schedule:
         interval: weekly
     - package-ecosystem: github-actions
       directory: /
       schedule:
         interval: weekly
   ```

Commit message: "ci: add CodeQL security scanning and Dependabot"
```

---

## Slice 8: Fix Version Remnants + Adopt Semantic Release

**Why:** Version `0.1.0` is hardcoded in 5 places (including `crossref/application.py:294`). `0.0.1` exists in `docs/website/package.json`. No CHANGELOG, no GitHub Releases.

**Files to modify:**
- `pyproject.toml`
- `app/services/domains/crossref/application.py`

**Files to create:**
- `.github/workflows/release.yml`

**Prompt:**
```
You are working on the scholarr repository. Set up automated versioning with python-semantic-release.

1. Fix hardcoded version in `app/services/domains/crossref/application.py` (line ~294):
   ```python
   # Before:
   etiquette = Etiquette(settings.app_name, "0.1.0", "https://scholarr.local", email)

   # After:
   from importlib.metadata import version as pkg_version
   _APP_VERSION = pkg_version("scholarr")
   # then in function:
   etiquette = Etiquette(settings.app_name, _APP_VERSION, "https://scholarr.local", email)
   ```

2. In `pyproject.toml`, add semantic-release config:
   ```toml
   [tool.semantic_release]
   version_toml = ["pyproject.toml:project.version"]
   version_variables = ["frontend/package.json:version"]
   branch = "main"
   build_command = ""
   commit_message = "chore(release): v{version}"
   ```

3. Create `.github/workflows/release.yml`:
   ```yaml
   name: Release

   on:
     push:
       branches: [main]

   jobs:
     release:
       runs-on: ubuntu-latest
       if: github.repository == 'JustinZeus/scholarr'
       permissions:
         contents: write
         id-token: write
       steps:
         - uses: actions/checkout@v4
           with:
             fetch-depth: 0
             token: ${{ secrets.GITHUB_TOKEN }}
         - uses: actions/setup-python@v5
           with:
             python-version: "3.12"
         - run: pip install python-semantic-release
         - name: Semantic Release
           id: release
           run: semantic-release publish
           env:
             GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
   ```

4. Add `python-semantic-release` to dev dependencies in `pyproject.toml`.

Note: `docs/website/package.json` version (`0.0.1`) is addressed in Slice 9 (docs rebuild). `frontend/package-lock.json` and `uv.lock` versions auto-update on next `npm install`/`uv sync`.

Commit message: "ci: adopt python-semantic-release, fix hardcoded version strings"
```

---

## Slice 9: Docs — Delete and Rebuild from Scratch

**Why:** Current docs have split authority (two api-contract.md files), orphaned pages, stale version (`0.0.1`), and missing critical docs (testing, deployment, configuration reference). Clean slate is faster than migration.

**Files to delete:**
- `docs/` (entire directory)

**Files to create:**
- Complete new `docs/` tree

**Prompt:**
```
You are working on the scholarr repository. Delete the entire `docs/` directory and rebuild from scratch.

Target IA:

docs/
├── index.md                          # Landing page: what is scholarr, quick links
├── user/
│   ├── overview.md                   # What scholarr does, key concepts
│   ├── getting-started.md            # Install (docker compose), first run, add first scholar
│   └── configuration.md              # ALL env vars from .env.example, organized by category
├── developer/
│   ├── overview.md                   # Dev quickstart
│   ├── architecture.md               # FastAPI + SQLAlchemy + Vue 3, domain service boundaries
│   ├── local-development.md          # docker-compose.dev.yml, hot reload, running tests
│   ├── contributing.md               # PR process, conventional commits, code standards from agents.md
│   ├── ingestion.md                  # Ingestion pipeline: parsing, rate limiting, safety gates
│   ├── frontend-theme-inventory.md   # Theme tokens, Tailwind integration
│   └── testing.md                    # Test tiers (unit/integration/smoke), markers, fixtures, how to run
├── operations/
│   ├── overview.md                   # Ops quickstart
│   ├── deployment.md                 # Production Docker, scaling, health checks
│   ├── database-runbook.md           # Backup, restore, integrity checks, migration procedures
│   ├── scrape-safety-runbook.md      # Rate limiting, cooldowns, CAPTCHA handling
│   └── arxiv-runbook.md              # ArXiv rate limits, cache, query patterns
├── reference/
│   ├── overview.md                   # Reference index
│   ├── api.md                        # CANONICAL: envelope spec + endpoints + DTO contract
│   ├── environment.md                # Env var quick-reference (links to user/configuration.md)
│   └── changelog.md                  # Placeholder: "auto-generated by semantic-release"
└── website/
    ├── docusaurus.config.js
    ├── sidebars.js                   # ALL pages listed, no orphans
    ├── package.json                  # version: "0.1.0"
    └── src/css/custom.css

Content guidelines:
- Self-contained, scannable docs (headers, bullets, tables)
- Frontmatter: `title`, `sidebar_position`
- `configuration.md`: read `.env.example`, organize every variable with description, type, default, example
- `testing.md`: pytest markers from pyproject.toml (`integration`, `db`, `migrations`, `schema`, `smoke`), container-based runner from agents.md, fixture org under tests/fixtures/
- `api.md`: merge old `developer/api-contract.md` (DTO structure) and `reference/api-contract.md` (envelope spec). Include exact envelope shapes:
  - Success: `{"data": ..., "meta": {"request_id": "..."}}`
  - Error: `{"error": {"code": "...", "message": "...", "details": ...}, "meta": {"request_id": "..."}}`
  - Publication semantics (modes, pagination, identifiers)
  - Scholar portability endpoints
- `deployment.md`: practical Docker commands from docker-compose.yml
- `database-runbook.md`: reference scripts/db/ (backup_full.sh, restore_dump.sh, check_integrity.py, repair_publication_links.py)

Docusaurus config:
- url: "https://justinzeus.github.io"
- baseUrl: "/scholarr/"
- organizationName: "JustinZeus"
- projectName: "scholarr"
- onBrokenLinks: "throw"
- docs path: ".." (reads from docs/ parent)
- Exclude: "website/**", "README.md"

Commit message: "docs: rebuild documentation from scratch with clean IA"
```

---

## Slice 10: Begin `ingestion/application.py` Decomposition

**Why:** After logging cleanup (slices 3+5), the file is ~2,700-2,800 lines. Still the largest source file by 3x. This begins decomposition with the safest extract: safety gate logic.

**Files to modify:**
- `app/services/domains/ingestion/application.py`

**Files to create:**
- `app/services/domains/ingestion/safety.py`

**Prompt:**
```
You are working on the scholarr repository. `app/services/domains/ingestion/application.py` is ~2,700-2,800 lines (after logging cleanup). It contains the entire ingestion orchestration in a single class.

Extract the FIRST logical chunk: safety gate logic.

1. Read `app/services/domains/ingestion/application.py` fully.

2. Identify safety/cooldown methods:
   - `_enforce_safety_gate`
   - `_raise_safety_blocked_start`
   - Cooldown activation/clearing methods
   - Alert threshold evaluation methods

3. Create `app/services/domains/ingestion/safety.py`:
   - Move identified methods to standalone functions or a small class
   - Accept explicit parameters (no implicit self.xxx state)
   - Keep same function signatures where possible

4. Update `application.py` to import from `safety.py`.

5. Run full test suite: `docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app pytest tests/`
   All tests must pass unchanged.

Constraints from `agents.md`:
- Max 50 lines per function
- No flat files in `app/services/` root — all within `app/services/domains/ingestion/`
- Fail fast, early returns, guard clauses

Commit message: "refactor: extract ingestion safety gate logic to dedicated module"
```

---

## Verification (after all slices)

Run these checks to confirm everything is clean:

```bash
# 1. No tracked build artifacts
git ls-files build/ | wc -l  # expect: 0

# 2. No duplicated event keys in logging
grep -rn '"event":' app/ --include="*.py" | grep -v __pycache__ | wc -l  # expect: 0

# 3. No _log_ helper functions remain
grep -rn 'def _log_' app/ --include="*.py" | wc -l  # expect: 0

# 4. No stale version strings
grep -rn '0\.0\.1' . --include="*.py" --include="*.json" --include="*.toml" \
  | grep -v node_modules | grep -v .venv | grep -v uv.lock | wc -l  # expect: 0

# 5. Docs build
npm --prefix docs/website run build  # expect: success, no broken links

# 6. All tests pass
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app pytest tests/
```

---

## Slice Summary

| # | Slice | Files Changed | Estimated Impact |
|---|-------|---------------|------------------|
| ~~1~~ | ~~Repo hygiene~~ | ~~120 files~~ | ~~-18,380 lines~~ **DONE** |
| 2 | `structured_log()` utility | 2 files | +50 lines |
| 3 | Migrate ingestion logging | 1 file | -300 lines |
| 4 | Migrate remaining logging | ~20 files | -180 lines |
| 5 | Logging noise/readability | ~5 files | -30 lines, better output |
| 6 | Ruff + mypy in CI | 2 files | +50 lines config |
| 7 | CodeQL + Dependabot | 2 files | +40 lines config |
| 8 | Version fix + semantic-release | 3 files | +40 lines config |
| 9 | Docs rebuild | full replacement | ~20 new files |
| 10 | Ingestion decomposition | 2 files | net zero (move) |
