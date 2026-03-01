---
title: Operations Overview
sidebar_position: 1
---

# Operations Overview

This section covers production deployment, database administration, and scrape safety operations.

## Quick Links

| Guide | Description |
|-------|-------------|
| [Deployment](deployment.md) | Production Docker setup, scaling, health checks |
| [Database Runbook](database-runbook.md) | Backup, restore, integrity checks, repair procedures |
| [Scrape Safety Runbook](scrape-safety-runbook.md) | Rate limiting, cooldowns, CAPTCHA handling |
| [arXiv Runbook](arxiv-runbook.md) | arXiv rate limits, cache tuning, query patterns |

## Health Check

The app exposes `GET /healthz` for container orchestration:

```bash
curl -fsS http://localhost:8000/healthz
```

Docker Compose healthcheck config:
- Interval: 10s
- Timeout: 5s
- Retries: 12
