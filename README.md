# Finance App

A personal finance app built on UK/EU Open Banking. Connect bank accounts through a secure consent flow, see every balance and transaction in one place, get spending auto-categorized, and stay on top of monthly budgets.

> Status: Weeks 1–5 of 6 done. Backend (BR-01..BR-11), React PWA dashboard, append-only audit log, CI/CD. Build journal: [docs/development-log.md](docs/development-log.md).

[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)

## Documents

- [Business requirements (BRD)](docs/BRD.md)
- [Technical design](docs/technical-design.md)
- [Architecture decision records](docs/adr/)
- [Development log](docs/development-log.md): every step, decision and fix

## Stack

Python 3.12 · FastAPI · SQLAlchemy 2.0 · PostgreSQL 16 · Redis + arq · React PWA · Docker · GitHub Actions · AWS

## Run locally

Prerequisites: Docker Desktop and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env          # then set POSTGRES_PASSWORD, JWT_SECRET and TOKEN_ENCRYPTION_KEY
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
| GET | /api/v1/institutions?country=GB | Bearer | Banks to connect |
| POST | /api/v1/connections | Bearer | Start bank consent → `authorisation_url` (BR-02) |
| GET | /api/v1/connections/callback | `state` | Bank redirect target; 303 to the web app |
| GET | /api/v1/connections | Bearer | Connected banks, renew banner flag, last sync status |
| POST | /api/v1/connections/{id}/renew | Bearer | Re-consent (BR-03) |
| POST | /api/v1/connections/{id}/sync | Bearer | Queue a sync now (202) |
| DELETE | /api/v1/connections/{id} | Bearer | Disconnect: revoke and delete data (BR-04) |
| GET | /api/v1/accounts | Bearer | All accounts, balances, totals per currency (BR-05) |
| GET | /api/v1/transactions | Bearer | Filter by account, dates, status, text; paged (BR-06) |
| PATCH | /api/v1/transactions/{id} | Bearer | Change category; `apply_to_similar` creates a rule (BR-08) |
| GET / POST / DELETE | /api/v1/categories | Bearer | 12 built-in plus own categories (BR-07) |
| GET / POST / DELETE | /api/v1/category-rules | Bearer | Own categorisation rules (BR-08) |
| GET / PUT / DELETE | /api/v1/budgets?month=YYYY-MM | Bearer | Monthly budgets with spend and status (BR-09) |
| GET | /api/v1/notifications | Bearer | Budget alerts at 80 % and 100 % (BR-10) |
| GET | /api/v1/dashboard/summary?month=YYYY-MM | Bearer | Spending by category, 6-month trend (BR-11) |
| GET | /api/v1/audit-log | Bearer | Own consent, sync and deletion events (NFR-06) |

The full schema is in [docs/openapi.json](docs/openapi.json) (also served at `/docs`).
| GET | /api/v1/health, /health/ready | — | Liveness / readiness |

### Try the bank connection offline

With `BANK_PROVIDER=mock` (the default), `POST /api/v1/connections` with
`{"institution_id": "mock-bank-uk"}` returns an `authorisation_url` to a demo bank
page. Open it in a browser and click **Approve**: you are redirected through the
callback, the worker fetches accounts, and `GET /api/v1/accounts` shows them.
Set `BANK_PROVIDER=yapily` with sandbox credentials from console.yapily.com to use
real sandbox banks. See [ADR 0003](docs/adr/0003-bank-consent-flow.md) for the flow.

### Web app (React PWA)

```bash
cd web
npm install
npm run dev            # http://localhost:5173, proxies /api to the backend on :8000
```

Register, connect **Mock Bank (UK)**, approve on the demo bank page, and the
dashboard fills in. `npm test`, `npm run lint`, `npm run typecheck`, `npm run build`.
After changing the API: `uv run python scripts/export_openapi.py` (in `backend/`)
then `npm run gen:api` (in `web/`).

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
- Bank consent tokens are encrypted with AES-256-GCM (versioned keys, bound to their row) and never appear in URLs: the callback carries a one-time token exchanged server-side, and a single-use `state` stops CSRF and replay ([ADR 0003](docs/adr/0003-bank-consent-flow.md)).
- Only the last 4 characters of account numbers are stored; bank I/O runs in the background worker.
- Append-only audit log: a database trigger rejects UPDATE, DELETE and TRUNCATE ([development log 5.1](docs/development-log.md)).
- Web app: access token in memory only, refresh token in sessionStorage, service worker never caches API data ([ADR 0005](docs/adr/0005-web-app-auth-and-api-types.md)).
- No secrets in the repo: `.env` is git-ignored; `.env.example` holds placeholders.
- The DB password is a `SecretStr` and is masked in logs and reprs.
- Validation errors never echo submitted values; unexpected errors never leak internals.
- Containers run as a non-root user; Postgres and Redis bind to localhost only.
