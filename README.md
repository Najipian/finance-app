# Finance App

A personal finance app built on UK/EU Open Banking. Connect bank accounts through a secure consent flow, see every balance and transaction in one place, get spending auto-categorized, and stay on top of monthly budgets.

> Status: Week 1 of 6 complete. Backend, Docker stack, migrations, auth (BR-01) with rate limiting, and CI/CD in place.

[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)

## Documents

- [Business requirements (BRD)](docs/BRD.md)
- [Technical design](docs/technical-design.md)
- [Architecture decision records](docs/adr/)

## Stack

Python 3.12 · FastAPI · SQLAlchemy 2.0 · PostgreSQL 16 · Redis + arq · React PWA · Docker · GitHub Actions · AWS

## Run locally

Prerequisites: Docker Desktop and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env          # then set POSTGRES_PASSWORD and JWT_SECRET
docker compose up --build
```

- API docs: <http://localhost:8000/docs>
- Liveness: <http://localhost:8000/api/v1/health>
- Readiness (checks Postgres + Redis): <http://localhost:8000/api/v1/health/ready>

Compose runs `alembic upgrade head` (the `migrate` service) before the API and worker start.

## API so far

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | /api/v1/auth/register | — | Create account (BR-01) |
| POST | /api/v1/auth/login | — | Email + password → access + refresh token |
| POST | /api/v1/auth/refresh | — | Rotate tokens (single-use refresh token) |
| POST | /api/v1/auth/logout | — | Revoke the session |
| GET | /api/v1/me | Bearer | Current user |
| GET | /api/v1/health, /health/ready | — | Liveness / readiness |

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

## CI/CD

GitHub Actions (`.github/workflows/ci.yml`) on every push and PR: ruff + mypy, full test suite with real Postgres/Redis (testcontainers) and a 70% coverage gate, `pip-audit`, and a Docker Compose smoke test that registers and logs in. Green commits on `main` publish `ghcr.io/<owner>/<repo>/backend:<sha>`; the AWS deploy (Week 6) will deploy that image. CodeQL and Dependabot run alongside.

## Security notes

- Passwords hashed with Argon2id (off the event loop). 15-minute JWT access tokens with a pinned algorithm.
- Refresh tokens are opaque, stored as SHA-256, single-use, and rotated; replaying a used token revokes the whole session.
- Login gives the same response and timing for an unknown email and a wrong password.
- Rate limits on auth endpoints: 10/min per IP, and 5 login attempts per 15 min per account from any IP (429 + `Retry-After`). See [ADR 0002](docs/adr/0002-rate-limiting-on-async-redis.md).
- No secrets in the repo: `.env` is git-ignored; `.env.example` holds placeholders.
- The DB password is a `SecretStr` and is masked in logs and reprs.
- Validation errors never echo submitted values; unexpected errors never leak internals.
- Containers run as a non-root user; Postgres and Redis bind to localhost only.
