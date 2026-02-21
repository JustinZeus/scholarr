# Developer Local Development

## Start the Dev Stack

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

Open:
- API: `http://localhost:8000`
- Frontend dev server: `http://localhost:5173`

Stop:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
```

## Backend Validation

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app uv run pytest tests/unit
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm app uv run pytest -m integration
```

## Frontend Validation

```bash
cd frontend
npm install
npm run typecheck
npm run test:run
npm run build
```

## Repository Gates

```bash
python3 scripts/check_frontend_api_contract.py
python3 scripts/check_env_contract.py
./scripts/check_no_generated_artifacts.sh
```

## Docs Site (Contributor Workflow)

Docs tooling is colocated in `docs/website/`:

```bash
cd docs/website
npm install
npm run build
```
