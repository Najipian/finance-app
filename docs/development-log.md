# Development log

A step-by-step record of how the Finance App was built: what was done, why, the
decisions taken, and the problems found along the way and how they were fixed.
Requirements are referenced by ID (`BR-xx`, `NFR-xx`) from [BRD.md](BRD.md); the
architecture is in [technical-design.md](technical-design.md); significant
decisions have ADRs in [adr/](adr/).

---

## Week 1: Foundations (BR-01)

### 1.1 Repository and git

- Created the monorepo at `D:\finance-app`, copied in the planning docs.
- `git init` on `main`. Added:
  - `.gitignore`: `.env`, virtualenvs and tool caches stay out of the repo.
  - `.gitattributes`: LF line endings everywhere. Development is on Windows but
    containers and CI run Linux; CRLF breaks shell entrypoints and pollutes diffs.
  - `.editorconfig`: consistent indentation and line endings across editors.
- Commits use a repo-local identity with the owner's GitHub *noreply* address, so no
  personal email lands in public history.

### 1.2 Backend project (uv)

- Installed uv (via pip; it was not on the machine). uv resolves dependencies,
  writes `uv.lock` so CI and Docker install identical versions, and manages `.venv`.
- `backend/pyproject.toml` holds the package metadata and all tool config:
  - ruff (line length 100; rules E, F, I, B, UP, S, N, SIM, RUF, ASYNC, BLE, D with
    Google docstrings),
  - `mypy --strict` with the pydantic plugin,
  - pytest with asyncio mode and a **70% coverage gate** on `src/`.
- Dependencies are added only when the code that uses them is written.

### 1.3 Application skeleton

Layered as in the technical design: `api/` (HTTP only) → `modules/<domain>/service.py`
(business logic) → `repository.py` (queries).

- `core/config.py`: typed settings (pydantic-settings). The Postgres password is a
  `SecretStr` and the DB URL is assembled in code, so the password never appears in
  logs or reprs.
- `core/logging.py`: structlog; readable output locally, JSON in production.
- `core/errors.py`: every error becomes an RFC 9457 `application/problem+json`
  response in one place. Validation errors never echo submitted values (they could
  be passwords); unexpected errors never leak internals.
- `db/base.py`: declarative base with a constraint naming convention (stable Alembic
  diffs), timezone-aware datetimes and `NUMERIC(18,2)` for `Decimal`.
- `db/session.py`: async engine and session factories, created by the app at startup
  (no module-level globals).
- `main.py`: `create_app()` factory; uvicorn runs it with `--factory`, so importing
  the module has no side effects and tests build apps with their own settings.
- Health: `/api/v1/health` (liveness, no dependencies) and `/api/v1/health/ready`
  (checks Postgres and Redis, 503 if either fails). Readiness logic lives in
  `modules/health/service.py`, so routes never run queries.
- `worker/settings.py`: an arq worker stub with a `ping` job.

### 1.4 Docker

- Multi-stage `backend/Dockerfile`: uv installs the locked dependencies in a builder
  stage (cached until `uv.lock` changes); the runtime image contains only the
  virtualenv, runs as a non-root user and has a healthcheck. One image serves both
  the API and the worker.
- `docker-compose.yml`: api, worker, Postgres 16, Redis 7 with healthchecks; the app
  waits for healthy dependencies. Database and Redis ports bind to `127.0.0.1` only.
- `.env.example` documents every setting with placeholders; the real `.env` is
  generated locally with random secrets and is git-ignored.

**Problems and fixes**

- *Docker Desktop would not start.* Its log showed it shutting down because it could
  not delete a stale socket file (`userAnalyticsOtlpHttp.sock`), a known bug in
  Docker Desktop 4.30 that recurs on every restart. Workaround: delete the file; real
  fix: update Docker Desktop (done later, to 4.99).
- *testcontainers' Ryuk helper failed on Windows* ("port mapping not available"): it
  reads the port before Docker Desktop publishes it. Ryuk is disabled on Windows only;
  fixtures stop their containers themselves, and CI on Linux keeps Ryuk.
- `readme = "../README.md"` in `pyproject.toml` broke the Docker build (the build
  context is `backend/` only); removed.

**Verified:** the stack starts in the right order; readiness reports 503 when Postgres
is stopped and recovers by itself; liveness stays 200.

### 1.5 Migrations (Alembic)

- Async `alembic/env.py` that takes the database URL from settings (no credentials in
  `alembic.ini`) or from the test suite, and imports every model via
  `db/registry.py` so autogenerate sees the whole schema.
- Migration file names are date-prefixed; new migrations are lint-fixed and
  formatted by ruff automatically (post-write hooks).
- Compose has a one-shot `migrate` service; api and worker start only after it exits
  successfully, so the app never runs against an old schema.
- Each migration is checked with upgrade → downgrade → upgrade.

### 1.6 Authentication (BR-01)

- `core/security.py`:
  - Passwords hashed with **Argon2id**, in a worker thread (hashing is deliberately
    slow and would otherwise block the event loop). Hashes are upgraded on login if
    parameters change.
  - **Access tokens:** 15-minute HS256 JWTs; decoding pins the algorithm and requires
    `sub`, `exp`, `iat` and `type` (an unsigned `alg: none` token is rejected).
  - **Refresh tokens:** random 256-bit strings stored as SHA-256 (a fast hash is
    enough for high-entropy secrets; Argon2 is for passwords).
- Tables `users` (email unique, lower-case) and `refresh_tokens` (with a `family_id`
  per login).
- `AuthService`:
  - Login gives the **same response and timing** for an unknown email and a wrong
    password (it verifies against a dummy hash), so emails can't be enumerated.
  - Refresh **rotates** the token; the row is locked so concurrent refreshes can't
    both succeed. Presenting an already-used token is treated as theft and **revokes
    the whole family**.
  - Logout revokes the session and is idempotent.
- Endpoints: `POST /auth/register|login|refresh|logout`, `GET /me`.

**Problems and fixes**

- Integration tests failed at teardown with "Event loop is closed": async fixtures ran
  on a session-wide event loop while tests ran on per-test loops, so connections were
  opened on one loop and closed on another. Fixed by running tests on the session loop.
- A test using the password `"short"` failed its "password never echoed" check
  because the error code is `too_short`; the test now uses a distinctive value.

### 1.7 Rate limiting (BR-01, NFR-02) — [ADR 0002](adr/0002-rate-limiting-on-async-redis.md)

- slowapi (named in the original stack) was replaced: it makes *blocking* Redis calls
  in async handlers and needs a module-level limiter, both against the project rules.
- `core/rate_limit.py`: a fixed-window limiter on the async Redis client (one atomic
  `INCR` + `EXPIRE NX` + `TTL` per check), injected with `Depends`.
- Limits: 10 requests/minute per IP per auth endpoint; 5 login attempts per 15
  minutes per account from any IP, keyed on a SHA-256 of the email. Over the limit:
  429 with `Retry-After`. Fails open if Redis is down.
- uvicorn runs with `--proxy-headers` so per-IP limits see real client IPs behind a
  reverse proxy (the proxy must be listed in `FORWARDED_ALLOW_IPS`).

### 1.8 CI/CD and GitHub

- `.github/workflows/ci.yml` on every push and pull request:
  1. ruff, ruff format check, `mypy --strict`;
  2. the full test suite with real Postgres and Redis (testcontainers) and the
     coverage gate;
  3. `pip-audit` on the locked dependencies;
  4. a Docker Compose smoke test that migrates, checks readiness, registers and
     logs in;
  5. on `main` only: publish the image to GHCR tagged with the commit SHA
     (continuous delivery; the AWS deploy in Week 6 will deploy that image).
- CodeQL (security-extended) and Dependabot (uv, Actions, Docker); pre-commit runs
  the project's own pinned ruff and mypy.
- Created the public repository `Najipian/finance-app`; before the first push the
  history was checked for secrets (none) and author emails (noreply only).

**Problems and fixes**

- Dependabot opened nine PRs. Each was checked (CI plus release notes for breaking
  changes) and eight were merged. Actions used only in the publish job were verified
  on the `main` run, since that job doesn't run on PRs. The Python 3.15 base-image bump
  was declined with an ignore rule (the project targets 3.12).
- Dependabot's Python update job kept failing: it tried `redis` 6, which `arq`
  doesn't support. Ignored `redis` major bumps until `arq` catches up.

---

## Week 2: Bank connection (BR-02, BR-05) — [ADR 0003](adr/0003-bank-consent-flow.md)

### 2.1 Research

Read Yapily's API reference for the exact request and response shapes (authorisation
requests, one-time-token exchange, accounts, balances, institutions, consent
deletion). Key facts: HTTP Basic auth, consent token in a `consent` header, amounts
as JSON numbers, cancel reported as `error=access_denied` on the callback.

### 2.2 Token encryption (NFR-01)

`core/crypto.py`: AES-256-GCM with a random nonce per value, a key-version prefix for
rotation, and the connection ID as associated data (a ciphertext copied to another
row fails to decrypt). Moved up from Week 5 because tokens are first stored now.
The key is validated at startup; the `.env.example` placeholder is invalid on purpose
so the app refuses to start until a real key is set.

**Problem and fix:** a garbage value like `v1:%%%` decoded to empty bytes (Python's
base64 decoder skips invalid characters) and crashed AES-GCM with a raw error. The
cipher now checks the decoded length first.

### 2.3 Provider layer

- `providers/base.py`: the `BankProvider` protocol and frozen DTOs: `Decimal`
  amounts, account numbers masked to the last 4 characters inside the adapter,
  `SecretStr` consent token; typed errors for cancel, expired consent and outages.
- `providers/mock.py` plus a demo bank page (`api/v1/mock_bank.py`) with Approve and
  Cancel that redirects exactly like a real provider. It never redirects outside our
  own callback (no open redirect) and is not mounted in production.
- `providers/yapily.py`: one-time-token flow, JSON parsed with `Decimal`, GETs
  retried with exponential backoff, consent POSTs never retried, 401/403 → "needs
  renewal", errors never include response bodies. Contract-tested with respx.

### 2.4 Data model

Tables `bank_connections` (status, encrypted token, consent expiry), `accounts`
(unique per connection and provider ID) and `balances` (latest value per type).
Deleting a connection cascades to its data.

### 2.5 Consent flow

- `POST /connections`: creates a *pending* connection and a random single-use `state`
  in Redis (10-minute TTL) bound to the user and connection; returns the bank URL.
- `GET /connections/callback`: consumes the state with `GETDEL` (stops CSRF and
  replay), completes the consent, encrypts the token, activates the connection and
  queues `sync_accounts`. Cancel deletes the pending row (nothing stored). Always
  303-redirects to the web app with the outcome.
- The arq job upserts accounts and balances (idempotent); an expired consent marks the
  connection `needs_renewal`.
- `GET /accounts`: every account with its headline balance (available preferred over
  booked) and totals **per currency** (never mixing GBP and EUR).

**Problem and fix (found only in Docker):** the worker container crashed on every
sync with `NoReferencedTableError`. The worker process never imported the `User`
model; in tests the worker ran inside the test process, where every model was already
loaded. The worker now imports the model registry, and a regression test imports the
worker in a fresh interpreter (verified to fail without the fix).

**Verified:** in Docker, two demo banks connected through the real flow; the worker
synced four accounts; totals GBP 9,477.57 and EUR 642.10; tokens stored only as
ciphertext.

**Open:** run the Yapily adapter against the real sandbox (needs credentials) to
confirm the one-time-token callback parameter name and that our `state` query
parameter survives the redirect.

---

## Week 3: Transactions, renewal, disconnect (BR-03, BR-04, BR-06)

### 3.1 Research

Read Yapily's transactions endpoint: `GET /accounts/{id}/transactions` with `from` /
`before` (ISO date-times), `limit` (≤ 1000) and `offset` paging, `meta.pagination.
totalCount`; transactions have `id`, `bookingDateTime`, `status` (`BOOKED` /
`PENDING`), signed `amount` (debits negative in the examples), `currency`,
`description` and `merchant.merchantName`.

### 3.2 Provider protocol: transactions and revocation

- `ProviderTransaction` DTO: optional provider ID, booking date, signed `Decimal`
  amount (debits negative), currency, description, merchant, `booked`/`pending`.
- `BankProvider` gained `get_transactions(token, account, from, to)` and
  `revoke_consent(consent_id)`.
- Yapily: pages through `GET /accounts/{id}/transactions` (`limit` 1000, `offset`)
  until `meta.pagination.totalCount`; dates formatted as Yapily expects
  (`yyyy-MM-dd'T'HH:mm:ss.SSSZ`, UTC); `DELETE /consents/{id}` for revocation. The
  HTTP helpers now return the whole document (`data` + `meta`), and DELETE is retried
  like GET because it is idempotent.
- Mock: deterministic transactions per account and day (salary on the 25th, card
  spending, a monthly savings transfer). The last two days are **pending** with a
  `p-` ID that changes to `b-` when it books, mimicking real UK banks; this is what
  the sync's pending cleanup has to handle.

### 3.3 Transactions table and deduplication (BR-06)

- `transactions`: account, optional provider ID, `dedup_key`, booking date,
  `NUMERIC(18,2)` amount, currency, description, merchant, status; unique
  `(account_id, dedup_key)` and an index on `(account_id, booking_date)`.
- `dedup_key` (`modules/transactions/dedup.py`): SHA-256 of the provider ID when
  present; otherwise of account, date, amount and description **plus an occurrence
  number**, because two genuinely identical transactions on one day (two identical
  coffees) would otherwise collide and one would be silently dropped.
- No `raw_json` column, unlike the original design: raw bank payloads hold personal
  data the app doesn't need (NFR-05, data minimisation).
- `bank_connections` gained `last_sync_status` (`ok` / `retrying` / `failed`),
  `last_sync_error` (a short code, never a provider message) and
  `last_sync_attempt_at`, so a failing sync is visible to the user (NFR-07).
- Migration checked up → down → up, and the database has CHECK constraints for every
  status column (`add_column` doesn't always create them for non-native enums, so this
  was verified in Postgres).

### 3.4 Sync service with retries (BR-06, NFR-07)

`modules/connections/sync.py` replaces Week 2's accounts-only sync:

1. Window: the first sync fetches 12 months; later syncs fetch from
   `last_synced_at` minus 3 days to catch late-posted transactions.
2. Accounts and balances are upserted; transactions are upserted in batches with
   `INSERT … ON CONFLICT (account_id, dedup_key) DO UPDATE`.
3. **Pending cleanup:** pending rows in the window that the bank no longer returns
   are deleted, because a pending transaction often books under a *new* ID. Without
   this the old pending row would stay alongside the booked one (a duplicate).
4. One commit at the end: a provider failure halfway leaves the previous state.

The arq job `sync_connection` retries transient provider errors with exponential
backoff (30 s, 60 s, 120 s, 240 s; 5 tries). Between tries the connection shows
`last_sync_status = retrying`, and `failed` after the last. An expired consent stops
immediately and marks the connection `needs_renewal`. Job IDs follow the design,
`sync:<connection_id>:<window>`: one minute for user-triggered syncs, six hours for
scheduled ones, so duplicate triggers collapse.

### 3.5 Schedules and consent expiry (BR-03)

- Cron `schedule_syncs` at 00:00, 06:00, 12:00 and 18:00 UTC queues a sync for every
  active connection.
- Cron `check_consent_expiry` daily at 06:00 UTC marks expired consents
  `needs_renewal`, which stops syncing (US-02).
- The renew banner needs no stored flag: `GET /connections` computes `renewal_due`
  (expires within 7 days) and `days_until_expiry` at read time.

### 3.6 Renew, disconnect, manual sync (BR-03, BR-04)

- `POST /connections/{id}/renew`: the consent flow on the existing connection. The
  `state` records that it is a renewal, so cancelling at the bank **keeps** the
  connection and its data (a new connection would be deleted). On success the
  superseded consent is revoked in the background.
- `DELETE /connections/{id}`: revokes the consent at the provider, then deletes the
  connection; accounts, balances and transactions cascade. If the provider is down,
  data is still deleted immediately and the revocation is queued as a retried job:
  privacy shouldn't wait on a third party.
- `POST /connections/{id}/sync`: 202 Accepted; rate-limited to 5 per minute per user.
- Another user's connection is always 404, never 403.

### 3.7 Transactions API (BR-06)

`GET /transactions`: newest first, scoped to the user through account → connection;
filters for account, booking date range, status and text (description or merchant,
case-insensitive, bound parameter); `limit` (1–100) and `offset` paging with a total.

### 3.8 Tests

- Unit: dedup keys (stable, identical transactions both kept), renewal boundaries
  (exactly 7 days is due, 7 days + 1 s is not), Yapily transaction paging and field
  mapping and consent deletion (respx), the mock's pending → booked ID change, worker
  backoff (30/60/120/240 s), retry then give-up marking `failed`, revoke retries.
- Integration (real Postgres and Redis): a year of transactions imported and two
  re-syncs add nothing; pending → booked under a **new** ID leaves one booked row per
  account; same-ID booking updates in place; filters and paging; owner scoping (even
  with another user's `account_id`); failed sync rolls back and shows
  `retrying`/`failed`; manual sync merges within a minute; the scheduler skips
  connections that need renewal; renew banner at 5 days, expiry → `needs_renewal`
  → manual sync 409; renewal replaces the token and keeps data; cancelled renewal
  keeps the connection; disconnect deletes connection, accounts, balances and
  transactions; another user's connection is 404 for delete, renew and sync; revoke
  now, or queue it when the provider is down.

**Problem and fix:** one new test expected a single booked row, but the scripted bank
returns the transaction on both of its accounts. The sync was right (one booked row
per account, no pending left); the assertion now checks per account.

**Result:** 144 tests passing, 92% coverage; ruff and `mypy --strict` clean.

### 3.9 Documentation

- [ADR 0004](adr/0004-transaction-dedup-and-pending.md): pending cleanup, occurrence
  numbers, no raw payload storage.
- Technical design, README (endpoints, status), CLAUDE.md status updated.
