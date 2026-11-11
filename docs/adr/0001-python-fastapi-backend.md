# 1. Python + FastAPI backend instead of NestJS

Date: 2026-11-10 · Status: Accepted

## Context

The backend needs async I/O against an Open Banking provider, typed request and
response models, generated OpenAPI docs, background jobs and a strong testing story.
It is built solo, part time, in six weeks, and is read by hiring teams at UK, EU,
Australian and New Zealand fintechs.

The two candidates were Python with FastAPI and TypeScript with NestJS. Both are
credible fintech choices.

## Decision

Use Python 3.12 with FastAPI, Pydantic v2, SQLAlchemy 2.0 (async) and arq.

- Python is common at fintechs for data, integration and risk work, and it leaves
  room for future ML categorization (see the technical design's future extensions).
- FastAPI plus Pydantic gives validation and OpenAPI from the same type hints.
  `mypy --strict` gives type safety comparable to TypeScript.
- SQLAlchemy 2.0 with Alembic is mature for the Postgres features this design
  depends on: `ON CONFLICT` upserts, constraints and `NUMERIC` money columns.
- arq is async-native and small. Celery is the heavier, better-known
  alternative, and the job code would port to it easily.

## Consequences

- Front end (React + TypeScript) and backend are in different languages, so DTOs
  are shared through the OpenAPI schema rather than a shared package.
- NestJS's built-in module and DI structure has to be replaced by convention.
  We use layered modules (routes → services → repositories) and FastAPI `Depends`,
  documented in `CLAUDE.md`.
- Strict typing must be enforced by tooling (ruff, mypy --strict in CI), because
  Python does not enforce it at runtime.
