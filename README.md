# scholarr

<div align="center">

Self-hosted scholar tracking with a single app image (API + frontend).

[![CI](https://img.shields.io/github/actions/workflow/status/justinzeus/scholarr/ci.yml?style=for-the-badge)](https://github.com/JustinZeus/scholarr/actions/workflows/ci.yml)
[![Docker Pulls](https://img.shields.io/docker/pulls/justinzeus/scholarr?style=for-the-badge&logo=docker)](https://hub.docker.com/r/justinzeus/scholarr)
[![Docker Image](https://img.shields.io/badge/docker-justinzeus%2Fscholarr-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://hub.docker.com/r/justinzeus/scholarr)

</div>

## Quick Start

1. Copy env template:

```bash
cp .env.example .env
```

2. Set required values in `.env`:
- `POSTGRES_PASSWORD`
- `SESSION_SECRET_KEY`

3. Start stack:

```bash
docker compose pull
docker compose up -d
```

Open:
- App/API: `http://localhost:8000`
- Health: `http://localhost:8000/healthz`

## Documentation

Complete documentation is published at:

- https://justinzeus.github.io/scholarr/

Source markdown and docs tooling live under `docs/`.

## Quality Gates

Backend:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app uv run pytest tests/unit
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app uv run pytest -m integration
```

Frontend:

```bash
cd frontend
npm install
npm run typecheck
npm run test:run
npm run build
```

Contract and env checks:

```bash
python3 scripts/check_frontend_api_contract.py
python3 scripts/check_env_contract.py
./scripts/check_no_generated_artifacts.sh
```
