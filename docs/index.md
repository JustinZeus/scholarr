---
title: Scholarr Documentation
sidebar_position: 1
---

# Scholarr

Scholarr is a self-hosted academic publication tracker. It monitors Google Scholar profiles, discovers new publications, resolves open-access PDFs, and presents everything through a clean Vue 3 dashboard.

## Quick Links

| Section | Description |
|---------|-------------|
| [User Guide](user/overview.md) | What scholarr does, installation, configuration |
| [Developer Guide](developer/overview.md) | Architecture, local development, contributing |
| [Operations](operations/overview.md) | Deployment, database runbook, scrape safety |
| [Reference](reference/overview.md) | API contract, environment variables, changelog |

## Key Features

- **Scholar Tracking** - Add Google Scholar profiles by ID, URL, or name search
- **Automated Ingestion** - Background scheduler fetches new publications on a configurable interval
- **Identifier Resolution** - Cross-references arXiv, Crossref, and OpenAlex for DOIs and metadata
- **PDF Discovery** - Resolves open-access PDFs via Unpaywall and arXiv
- **Import/Export** - Portable scholar data with full publication state
- **Multi-User** - Session-based auth with admin user management
- **Theming** - Multiple color presets with light/dark mode support
