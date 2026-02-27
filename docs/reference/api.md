---
title: API Contract
sidebar_position: 2
---

# API Contract

## Envelope Invariant

All API responses under `/api/v1` use one of these envelopes:

### Success

```json
{
  "data": "...",
  "meta": {
    "request_id": "..."
  }
}
```

### Error

```json
{
  "error": {
    "code": "...",
    "message": "...",
    "details": "..."
  },
  "meta": {
    "request_id": "..."
  }
}
```

`meta.request_id` is present on both success and error responses.

### Binary Assets

Binary media assets are served outside `/api/v1`:

```
GET /scholar-images/{scholar_profile_id}/upload
```

## DTO Structure

Scholarr uses strictly typed Pydantic V2 models serialized through OpenAPI v3 via FastAPI.

- `PublicationListItem` exposes a `.display_identifier` property that resolves the highest-confidence identifier regardless of backend origin, rather than a hardcoded `.doi`.
- Frontend TypeScript types are compiled from the OpenAPI spec to ensure type safety across the stack.

## Endpoints

### Auth

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/auth/login` | Login (rate-limited sliding window) |
| `GET` | `/api/v1/auth/me` | Current session user |
| `GET` | `/api/v1/auth/csrf` | Bootstrap CSRF token |
| `POST` | `/api/v1/auth/change-password` | Change password |
| `POST` | `/api/v1/auth/logout` | Logout |

### Scholars

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/scholars` | List tracked scholars |
| `POST` | `/api/v1/scholars` | Create scholar (auto-enqueue, metadata hydration) |
| `GET` | `/api/v1/scholars/search` | Search author candidates by name |
| `PATCH` | `/api/v1/scholars/{id}/toggle` | Toggle enabled status |
| `DELETE` | `/api/v1/scholars/{id}` | Delete scholar |
| `PUT` | `/api/v1/scholars/{id}/image/url` | Update image URL |
| `POST` | `/api/v1/scholars/{id}/image/upload` | Upload image |
| `DELETE` | `/api/v1/scholars/{id}/image` | Clear image customization |

### Scholar Portability

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/scholars/export` | Export tracked scholars and publication link state |
| `POST` | `/api/v1/scholars/import` | Import scholars with global publication deduplication |

The export payload includes scholar metadata, tracked publication data, and link state (read/unread, favorites). Import preserves global deduplication.

### Publications

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/publications` | List publications (filtered, paginated) |
| `POST` | `/api/v1/publications/mark-all-read` | Mark all as read |
| `POST` | `/api/v1/publications/mark-read` | Mark selected as read |
| `POST` | `/api/v1/publications/{id}/retry-pdf` | Retry PDF resolution |
| `POST` | `/api/v1/publications/{id}/favorite` | Toggle favorite |

#### Publication Modes

`GET /api/v1/publications` supports a `mode` parameter:

| Mode | Description |
|------|-------------|
| `all` | All publications |
| `unread` | Publications with `is_read=false` |
| `latest` | Publications first seen in the latest completed run |

`mode=new` is accepted as a compatibility alias for `latest`.

#### Pagination

Query parameters: `page`, `page_size` (with backward-compatible `limit`/`offset` support).

Response pagination fields:

```json
{
  "page": 1,
  "page_size": 20,
  "has_prev": false,
  "has_next": true,
  "total_count": 142
}
```

#### Publication Payload Fields

| Field | Description |
|-------|-------------|
| `pub_url` | Canonical scholar detail URL |
| `doi` | Normalized DOI |
| `pdf_url` | Resolved open-access PDF URL (when available) |
| `display_identifier` | Highest-confidence identifier regardless of source |

### Runs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/runs` | List runs with safety state |
| `GET` | `/api/v1/runs/{run_id}` | Run detail with scholar results |
| `POST` | `/api/v1/runs/{run_id}/cancel` | Cancel active run |
| `POST` | `/api/v1/runs/manual` | Trigger manual run (idempotent, safety-checked) |
| `GET` | `/api/v1/runs/queue/items` | List queue items |
| `POST` | `/api/v1/runs/queue/{id}/retry` | Retry queue item |
| `POST` | `/api/v1/runs/queue/{id}/drop` | Drop queue item |
| `DELETE` | `/api/v1/runs/queue/{id}` | Clear queue item |
| `GET` | `/api/v1/runs/{run_id}/stream` | Stream run events (SSE) |

### Settings

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/settings` | Get user settings (with cooldown expiry check) |
| `PUT` | `/api/v1/settings` | Update settings (interval, delay, nav, API keys) |

### Admin - User Management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/admin/users` | List all users |
| `POST` | `/api/v1/admin/users` | Create user |
| `PATCH` | `/api/v1/admin/users/{id}/active` | Set user active status |
| `POST` | `/api/v1/admin/users/{id}/reset-password` | Reset password |

### Admin - Database Operations

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/admin/db/integrity` | Get integrity report |
| `GET` | `/api/v1/admin/db/repair-jobs` | List repair jobs |
| `GET` | `/api/v1/admin/db/pdf-queue` | List PDF queue |
| `POST` | `/api/v1/admin/db/pdf-queue/{id}/requeue` | Requeue single PDF |
| `POST` | `/api/v1/admin/db/pdf-queue/requeue-all` | Bulk requeue missing PDFs |
| `POST` | `/api/v1/admin/db/repairs/publication-links` | Trigger link repair |
| `POST` | `/api/v1/admin/db/repairs/publication-near-duplicates` | Trigger dedup repair |
| `POST` | `/api/v1/admin/db/drop-all-publications` | Drop all publications (destructive) |
