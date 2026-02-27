---
title: Overview
sidebar_position: 1
---

# What is Scholarr?

Scholarr is a self-hosted service that tracks academic publications from Google Scholar. It runs as a Docker container with a PostgreSQL database and serves a Vue 3 frontend.

## Key Concepts

- **Scholar** - A tracked Google Scholar profile. Scholars are user-scoped: each user manages their own list.
- **Publication** - A globally deduplicated academic work. Publications are shared across all users to avoid duplicate storage.
- **Scholar-Publication Link** - Connects a scholar to a publication for a specific user. Read/unread state, favorites, and visibility live on this link, not on the publication itself.
- **Run** - A single ingestion cycle that fetches new publications for one or more scholars.
- **Identifier** - A DOI, arXiv ID, PMID, or other external key attached to a publication. Multiple identifiers can exist per publication.

## How It Works

1. You add a Google Scholar profile (by ID, URL, or name search).
2. The scheduler periodically scrapes the profile for new publications.
3. Each publication is fingerprinted and deduplicated against the global store.
4. External APIs (arXiv, Crossref, OpenAlex) are queried for identifiers.
5. Unpaywall and arXiv resolve open-access PDF URLs when a DOI is available.
6. The dashboard shows new, unread, and all publications with filtering and search.

## Safety Model

Scholarr enforces rate limits and cooldowns to prevent IP bans from upstream sources. These are not configurable to zero; they are safety floors. See [Scrape Safety Runbook](../operations/scrape-safety-runbook.md) for details.
