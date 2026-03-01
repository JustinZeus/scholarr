---
title: Getting Started
sidebar_position: 2
---

# Getting Started

## Prerequisites

- Docker and Docker Compose v2+
- A machine with at least 512 MB RAM

## Installation

1. Clone the repository:

```bash
git clone https://github.com/JustinZeus/scholarr.git
cd scholarr
```

2. Copy the example environment file:

```bash
cp .env.example .env
```

3. Edit `.env` and set the required secrets:

```bash
# Required: database password
POSTGRES_PASSWORD=your-secure-password

# Required: session signing key (32+ random characters)
SESSION_SECRET_KEY=your-random-secret-key
```

4. Start the stack:

```bash
docker compose up -d
```

5. Verify the service is healthy:

```bash
docker compose ps
curl http://localhost:8000/healthz
```

The app is now available at `http://localhost:8000`.

## First Run

### Bootstrap an Admin User

Set these environment variables before first start (or add them to `.env`):

```bash
BOOTSTRAP_ADMIN_ON_START=1
BOOTSTRAP_ADMIN_EMAIL=admin@example.com
BOOTSTRAP_ADMIN_PASSWORD=your-admin-password
```

Restart the app container. The admin account is created on startup.

### Add Your First Scholar

1. Log in at `http://localhost:8000`.
2. Navigate to the Scholars page.
3. Click **Add Scholar**.
4. Enter a Google Scholar profile URL (e.g., `https://scholar.google.com/citations?user=XXXXXXXXXX`) or a Scholar ID.
5. The scheduler will begin fetching publications on the next tick (default: 60 seconds).

### Manual Run

To trigger an immediate ingestion run, use the **Manual Run** button on the Runs page. This respects the minimum run interval (`INGESTION_MIN_RUN_INTERVAL_MINUTES`, default 15 minutes).

## Updating

```bash
docker compose pull
docker compose up -d
```

Database migrations run automatically on startup when `MIGRATE_ON_START=1` (the default).
