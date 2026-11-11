# Finance App

A personal finance app built on UK/EU Open Banking. Connect bank accounts through a secure consent flow, see every balance and transaction in one place, get spending auto-categorized, and stay on top of monthly budgets.

> Status: Week 1 of 6 (foundations). Backend skeleton, health checks and Docker stack in place; auth next.

## Documents

- [Business requirements (BRD)](docs/BRD.md)
- [Technical design](docs/technical-design.md)
- [Architecture decision records](docs/adr/)

## Stack

Python 3.12 · FastAPI · SQLAlchemy 2.0 · PostgreSQL 16 · Redis + arq · React PWA · Docker · GitHub Actions · AWS

## Run locally

Prerequisites: Docker Desktop and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env          # then set POSTGRES_PASSWORD
docker compose up --build
```

- API docs: <http://localhost:8000/docs>
- Liveness: <http://localhost:8000/api/v1/health>
- Readiness (checks Postgres + Redis): <http://localhost:8000/api/v1/health/ready>

### Without Docker for the API (faster reloads)

```bash
docker compose up -d postgres redis
cd backend
uv sync
uv run uvicorn finance_app.main:create_app --factory --reload
```

## Test and check

From `backend/`:

```bash
uv run pytest                        # unit + API + integration (needs Docker running), 70% coverage gate
uv run pytest -m "not integration"   # fast, no Docker
uv run ruff check . && uv run ruff format --check .
uv run mypy src
```

## Project layout

```text
backend/src/finance_app/
  main.py          app factory (create_app)
  core/            settings, logging, RFC 9457 errors
  db/              declarative base, async engine/session
  api/v1/          HTTP routes only
  modules/<domain> service (business logic), repository (queries), schemas, models
  worker/          arq background jobs
```

## Security notes

- No secrets in the repo: `.env` is git-ignored; `.env.example` holds placeholders.
- The DB password is a `SecretStr` and is masked in logs and reprs.
- Validation errors never echo submitted values; unexpected errors never leak internals.
- Containers run as a non-root user; Postgres and Redis bind to localhost only.
