---
title: Database Runbook
sidebar_position: 3
---

# Database Runbook

## Backup

Use `scripts/db/backup_full.sh` to create logical backups from the running `db` compose service.

### Custom-Format Backup (Default)

```bash
scripts/db/backup_full.sh
```

Creates a `.dump` file in `./backups/` (e.g., `scholarr_20260227T120000Z.dump`).

### Plain SQL Backup

```bash
scripts/db/backup_full.sh --plain
```

Creates a `.sql` file.

### Options

| Option | Description |
|--------|-------------|
| `--plain` | Write plain SQL instead of custom-format dump |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKUP_DIR` | `<repo>/backups` | Destination directory |
| `BACKUP_PREFIX` | `scholarr` | File prefix |
| `USE_DEV_COMPOSE` | `0` | Set to `1` to include `docker-compose.dev.yml` |

## Restore

Use `scripts/db/restore_dump.sh` to restore a backup into the running `db` service.

### Restore a Custom-Format Dump

```bash
scripts/db/restore_dump.sh --file backups/scholarr_20260227T120000Z.dump
```

### Restore with Schema Wipe

```bash
scripts/db/restore_dump.sh --file backups/scholarr_20260227T120000Z.dump --wipe-public
```

This drops and recreates the `public` schema before restoring. Use with caution.

### Options

| Option | Description |
|--------|-------------|
| `--file <path>` | Required. Path to `.dump` or `.sql` backup file |
| `--wipe-public` | Drop and recreate `public` schema before restore |

## Integrity Checks

Use `scripts/db/check_integrity.py` to run database integrity checks.

### Run Inside Container

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app \
  python scripts/db/check_integrity.py
```

### With Strict Warnings

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app \
  python scripts/db/check_integrity.py --strict-warnings
```

Returns non-zero exit code if any warning is present.

### Output Format

JSON report:

```json
{
  "status": "passed",
  "failures": [],
  "warnings": []
}
```

Exit codes:
- `0` - All checks passed
- `1` - Check failure
- `2` - Warnings present (with `--strict-warnings`)

### Via Admin API

```
GET /api/v1/admin/db/integrity
```

Returns the same integrity report through the API (admin auth required).

## Publication Link Repair

Use `scripts/db/repair_publication_links.py` to repair scholar-publication links with audit logging.

### Dry Run (Default)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app \
  python scripts/db/repair_publication_links.py --user-id 1
```

### Apply Changes

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app \
  python scripts/db/repair_publication_links.py --user-id 1 --apply \
  --requested-by "admin@example.com"
```

### Options

| Option | Description |
|--------|-------------|
| `--user-id <int>` | Required. Target user ID |
| `--scholar-profile-id <int>` | Optional. Filter by scholar profile ID (repeatable) |
| `--apply` | Apply changes (default is dry-run) |
| `--gc-orphan-publications` | Delete publications with zero links after cleanup |
| `--requested-by <string>` | Operator identifier for audit logs |

### Via Admin API

```
POST /api/v1/admin/db/repairs/publication-links
```

## Near-Duplicate Repair

Detect and merge near-duplicate publications via the admin API:

```
POST /api/v1/admin/db/repairs/publication-near-duplicates
```

## PDF Queue Management

### List Queue

```
GET /api/v1/admin/db/pdf-queue
```

### Requeue Single Item

```
POST /api/v1/admin/db/pdf-queue/{id}/requeue
```

### Bulk Requeue

```
POST /api/v1/admin/db/pdf-queue/requeue-all
```

## Migration Procedures

Alembic migrations run automatically on startup when `MIGRATE_ON_START=1`.

To run manually:

```bash
docker compose exec app alembic upgrade head
```

To check current migration status:

```bash
docker compose exec app alembic current
```

Recommended procedure for production:
1. Backup the database before upgrading.
2. Pull the new image.
3. Start the container; migrations run on startup.
4. Verify via `GET /healthz` and check logs for migration output.
