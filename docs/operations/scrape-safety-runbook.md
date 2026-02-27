---
title: Scrape Safety Runbook
sidebar_position: 4
---

# Scrape Safety Runbook

Operational handling for scrape safety cooldowns, threshold alerts, and blocked-IP events.

## Key Signals

Use structured log `event` fields (recommended with `LOG_FORMAT=json`):

| Event | Description |
|-------|-------------|
| `ingestion.safety_policy_blocked_run_start` | Run blocked by safety policy |
| `ingestion.safety_cooldown_entered` | Cooldown activated |
| `ingestion.safety_cooldown_cleared` | Cooldown expired |
| `ingestion.alert_blocked_failure_threshold_exceeded` | Blocked failure threshold tripped |
| `ingestion.alert_network_failure_threshold_exceeded` | Network failure threshold tripped |
| `ingestion.alert_retry_scheduled_threshold_exceeded` | Retry threshold tripped |
| `api.runs.manual_blocked_policy` | Manual run blocked by policy |
| `api.runs.manual_blocked_safety` | Manual run blocked by safety cooldown |
| `scheduler.run_skipped_safety_cooldown` | Scheduled run skipped due to cooldown |
| `scheduler.run_skipped_safety_cooldown_precheck` | Scheduler precheck blocked |
| `scheduler.queue_item_deferred_safety_cooldown` | Queue item deferred due to cooldown |

Each event includes metric-style fields (`metric_name`, `metric_value`) for log-based alert rules.

## Recommended Alert Rules

- **Cooldown enters**: Trigger on `event=ingestion.safety_cooldown_entered`
- **Repeated start blocks**: High rate of `event=api.runs.manual_blocked_safety`
- **Threshold trips**: Any of the `*_threshold_exceeded` events
- **Scheduler pressure**: Sustained `scheduler.queue_item_deferred_safety_cooldown`

## If Your IP Appears Blocked

### Symptoms

- Cooldown reason: `blocked_failure_threshold_exceeded`
- Parse state: `blocked_or_captcha`
- Redirects toward Google account sign-in flows

### Actions

1. Stop manual retries immediately.
2. Let cooldown expire; do not spam retriggers.
3. Increase `INGESTION_MIN_REQUEST_DELAY_SECONDS` and user request delay values.
4. Reduce concurrency pressure (keep one scheduler instance).
5. Keep name-search disabled if login-gated responses persist.
6. Resume with a small monitored run and verify blocked rate drops.

### Avoid

- Aggressive rapid retries
- Rotating through risky scraping patterns that increase challenge rates
- Bypass/CAPTCHA-solving workflows that may violate source platform rules

## Environment Controls

Policy floors and safety controls:

| Variable | Default | Description |
|----------|---------|-------------|
| `INGESTION_MIN_REQUEST_DELAY_SECONDS` | `2` | Floor delay between requests |
| `INGESTION_MIN_RUN_INTERVAL_MINUTES` | `15` | Minimum time between runs |
| `INGESTION_ALERT_BLOCKED_FAILURE_THRESHOLD` | `1` | Blocked failures before alert |
| `INGESTION_ALERT_NETWORK_FAILURE_THRESHOLD` | `2` | Network failures before alert |
| `INGESTION_ALERT_RETRY_SCHEDULED_THRESHOLD` | `3` | Retries before alert |
| `INGESTION_SAFETY_COOLDOWN_BLOCKED_SECONDS` | `1800` | Cooldown after blocked threshold (30 min) |
| `INGESTION_SAFETY_COOLDOWN_NETWORK_SECONDS` | `900` | Cooldown after network threshold (15 min) |
| `INGESTION_MANUAL_RUN_ALLOWED` | `1` | Enable manual runs |
| `INGESTION_AUTOMATION_ALLOWED` | `1` | Enable automated runs |

Apply stricter values first, then relax slowly only after sustained healthy runs.
