# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

Finance App: a personal finance app built on UK/EU Open Banking (read-only AIS). Users connect bank accounts through a consent flow, see balances and transactions in one place, get transactions auto-categorized, and track monthly budgets.

It is a **portfolio project** for the owner (Amr Najip, integration engineer in banking) to show production-grade fintech engineering to employers in the UK, Europe, Australia and New Zealand. Code quality, tests, security and documentation matter as much as features: reviewers will read this code.

## Source of truth

- `docs/BRD.md` — what to build: requirements BR-01..BR-12, user stories with acceptance criteria, NFRs, scope and the Won't list.
- `docs/technical-design.md` — how to build it: architecture, stack, repo layout, modules, data model, API, security, jobs, testing, CI/CD.

Read both before starting a milestone. If a change contradicts them, update the doc in the same change (or write an ADR in `docs/adr/`) rather than silently diverging. Reference requirement IDs (e.g. `BR-06`) in commit messages, PR descriptions and test names.

## Current status

**Week 2 done (pending Yapily sandbox check).** Repo: `D:\finance-app`, GitHub `Najipian/finance-app`. Week 1: skeleton, Docker, Alembic, auth BR-01 + rate limiting (ADR 0002), CI/CD, CodeQL, Dependabot. Week 2: AES-256-GCM `TokenCipher` (moved up from Week 5), `BankProvider` protocol, mock provider + demo bank page, Yapily adapter (contract-tested with respx from the API reference, not yet run against the sandbox: needs credentials), consent flow with one-time token + single-use Redis state (ADR 0003), `sync_accounts` arq job, `GET /accounts` with per-currency totals (BR-02, BR-05). Next: Week 3.

1. Week 1 — repo skeleton, `pyproject.toml` (uv), ruff/mypy/pytest config, pre-commit, Docker + Compose (api, Postgres, Redis), settings, DB session, Alembic, health endpoint, auth (BR-01), CI workflow, README.
2. Week 2 — `BankProvider` protocol, mock provider, Yapily sandbox adapter, consent flow, accounts and balances (BR-02, BR-05).
3. Week 3 — arq worker, transaction sync + dedup, consent renewal and disconnect (BR-03, BR-04, BR-06).
4. Week 4 — categories, rules engine, budgets, alerts (BR-07..BR-10).
5. Week 5 — React PWA dashboard, token encryption hardening, audit log, coverage (BR-11).
6. Week 6 — AWS deploy, README polish, architecture diagram, demo video.

Keep this section updated as milestones complete.

## Stack (backend)

Python 3.12+, FastAPI, Pydantic v2 + pydantic-settings, SQLAlchemy 2.0 async + asyncpg, Alembic, PostgreSQL 16, Redis + arq, httpx + tenacity, PyJWT, argon2-cffi, cryptography (AESGCM), structlog, rate limiting via `core/rate_limit.py` on async Redis (ADR 0002, replaces slowapi). Tooling: uv, ruff, mypy --strict, pytest (+ pytest-asyncio, respx, testcontainers), pre-commit. Front end later: React + Vite + TypeScript PWA in `web/`.

Do not swap core libraries without an ADR.

## Commands

Run from `backend/` (keep this list accurate). Config comes from `../.env` (copy `.env.example`).

```bash
uv sync                          # install deps
uv run uvicorn finance_app.main:create_app --factory --reload   # needs postgres + redis up
uv run arq finance_app.worker.settings.WorkerSettings           # worker
uv run pytest                    # all tests + coverage (integration tests need Docker running)
uv run pytest -m "not integration"   # fast, no Docker
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe change"
docker compose up --build        # from repo root: api + worker + postgres + redis
docker compose up -d postgres redis   # just the infra, for running the API with uv
uv run pre-commit install --config ../.pre-commit-config.yaml   # once, enables git hooks
```

The app has no module-level `app`; uvicorn uses the `create_app` factory (`--factory`).

The owner develops on **Windows** with Docker Desktop. Keep commands cross-platform (no bash-only scripts as the only way to do something; prefer `uv run`, Python scripts, or Make-free docs).

## Coding standards

**Structure**

- Layering: `api/v1` routes (HTTP concerns only) → `modules/<domain>/service.py` (business logic) → `repository.py` (SQLAlchemy queries). Routes never run queries; services never import FastAPI.
- One package per domain under `modules/` with `models.py`, `schemas.py`, `repository.py`, `service.py`.
- Dependencies injected with FastAPI `Depends`; no module-level globals for DB sessions or clients. `create_app()` app factory in `main.py`.
- All Open Banking calls go through the `BankProvider` protocol. Never call Yapily from routes or services directly.

**Python**

- Full type hints everywhere; code must pass `mypy --strict`.
- ruff for lint and format (line length 100); enable at least `E, F, I, B, UP, S, N, SIM, RUF, ASYNC`.
- Money is `Decimal` and `NUMERIC(18, 2)` plus a currency code — never `float`.
- Datetimes are timezone-aware UTC. IDs are UUIDs.
- Async all the way in request paths; no blocking I/O in async functions.
- Small functions, early returns, no bare `except`. Raise domain exceptions in services; map them to RFC 9457 problem responses in one exception handler.
- Configuration only through pydantic-settings; every setting listed in `.env.example`.

**Documentation**

- Every module, public class and public function has a docstring (Google style): what it does, args, returns, raises. Explain *why* for non-obvious logic.
- FastAPI routes set `summary`, `description`, `response_model` and documented error responses so `/docs` is useful on its own.
- Pydantic fields carry `Field(description=..., examples=[...])` where it helps API consumers.
- Significant decisions get a short ADR in `docs/adr/NNNN-title.md` (context, decision, consequences). First ADR: Python/FastAPI backend chosen over NestJS.
- Keep `README.md` current: what it is, architecture diagram, how to run, how to test, security notes.

**Testing**

- Write tests with each feature, not after. Name tests after behaviour and requirement, e.g. `test_sync_does_not_duplicate_transactions_br06`.
- Unit tests for pure logic; API tests with httpx `AsyncClient`; integration tests against real Postgres via testcontainers (SQLite is not an acceptable substitute for upsert or constraint behaviour).
- Mock the provider with the mock adapter or respx; tests never hit the real network.
- Coverage gate 70% on `src/` in CI.

**Security (non-negotiable)**

- Bank tokens encrypted with AES-256-GCM before storage; key from env/secret store, never committed.
- Passwords with Argon2id. Refresh tokens stored hashed and rotated.
- Every query scoped to the current user; return 404 for other users' resources.
- Never log tokens, passwords, full IBANs or raw provider payloads containing personal data.
- Validate the OAuth `state` on the consent callback.
- No secrets in the repo: `.env` is git-ignored; `.env.example` holds placeholders only.

## Out of scope (do not build)

Payments/PIS, real customers or production banking access, native mobile apps, ML categorization, Gulf banks. GoCardless Bank Account Data (Nordigen) is closed to new signups; use Yapily sandbox (TrueLayer as fallback).

## Workflow

- Work milestone by milestone; finish with passing lint, type-check and tests before moving on.
- Small, focused commits with clear messages (Conventional Commits, e.g. `feat(auth): add refresh token rotation (BR-01)`).
- Before finishing a task: run ruff, mypy and pytest; update docs and this file's status section if anything changed.
