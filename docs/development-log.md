# Development log

A step-by-step record of how Onesum was built: what was done, why, the
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

---

## Week 4: Categories, rules, budgets, alerts (BR-07..BR-10)

### 4.1 Data model

- `categories`: `user_id` NULL = built-in default, otherwise the user's own; names
  unique per user with Postgres `NULLS NOT DISTINCT`, so defaults can't be duplicated
  either. No sub-categories (`parent_id` in the design) until a feature needs them.
- `category_rules`: field (`description` / `merchant`), operator (`contains` /
  `equals` / `starts_with`, always case-insensitive), value, category, priority;
  `user_id` NULL = built-in.
- `transactions` gained `category_id` (SET NULL if the category is deleted) and
  `category_source` (`rule` / `manual`): automatic re-categorisation never
  overwrites a choice the user made by hand.
- `budgets`: unique per user, category and month, with `alerted_80` / `alerted_100`
  so each alert fires once (BR-10).
- `notifications`: in-app alerts. Email has no provider yet; the BRD's fallback is
  in-app notifications only.

### 4.2 Migration and default categories

- One migration for the four new tables and the transaction columns, checked
  up → down → up; Postgres has CHECK constraints for every enum column and the
  unique constraints (budgets per user/category/month, category names per user).
- **12 default categories and 56 built-in rules** are seeded inside the migration as
  frozen literal data (a migration must give the same result forever, so it never
  imports app code). IDs are `uuid5` of the name: identical in every environment.
  Rules are case-insensitive keyword matches on the description (TESCO, SAINSBURY…
  → Groceries; PRET, DELIVEROO… → Eating out; SALARY → Income; …).

### 4.3 Rules engine and categorisation (BR-07)

- `modules/categories/engine.py` is pure: rules are ordered **user rules first**
  (a user's rule always beats a built-in one), then lower priority, then newest; the
  first case-insensitive match wins; no match = Uncategorized (US-06).
- `CategorizationService.categorize_new` runs in the worker right after every sync,
  followed by the budget alert check, so new transactions get categories and alerts
  fire promptly. `recategorize` runs when a user adds or deletes a rule and
  re-evaluates every transaction whose category came from a rule; **manual choices are
  never changed**.
- Budget spend (`modules/budgets/service.py`) is the net outflow of a category in a
  month and currency (refunds reduce it; pending counts). Each threshold alerts once;
  raising a limit so spend falls back under a threshold re-arms it, lowering it below
  current spend alerts immediately.

### 4.4 Endpoints (BR-08, BR-09, BR-10)

- `PATCH /transactions/{id}`: sets the category **manually** (rules never override
  it). With `apply_to_similar`, also creates an *exact-match* rule on the merchant
  (or description if the bank gave no merchant) and applies it to past transactions
  immediately and future ones on sync (US-06). Exact match avoids over-matching.
- `GET/POST/DELETE /categories` and `/category-rules`: built-in categories are usable
  but can't be deleted (409); deleting a user category removes its rules and leaves
  its transactions Uncategorized; adding or deleting a rule re-evaluates the user's
  non-manual transactions.
- `GET /budgets?month=YYYY-MM`, `PUT /budgets`, `DELETE /budgets/{id}`: spend,
  remaining (negative when over), percent used and status (`ok` / `warning` /
  `exceeded`).
- `GET /notifications`, `POST /notifications/{id}/read`.
- Every resource is scoped to the user; other users' IDs are 404.

### 4.5 Manual category carry-over (closes the gap in ADR 0004)

If a user sets a category on a *pending* transaction and it books under a new ID,
the pending row is deleted. Before that delete, the sync now copies the manual
category to the matching booked row (same account, amount and description, booked
within 7 days, not already set by hand) in one `UPDATE … FROM` statement.

### 4.6 Tests

- Unit: rules engine (user beats built-in even with a worse priority, priority then
  newest, every operator, case-insensitive, merchant vs description, blank values);
  budget thresholds (239.99 of 300 is not 80 %, 240.00 is; 300.00 is 100 %), percent,
  status, zero limits, month boundaries (December → January).
- Integration: synced demo transactions categorised by the defaults (Tesco →
  Groceries, Pret → Eating out, salary → Income, TfL → Transport); unmatched stay
  Uncategorized; a manual category survives re-sync and re-categorisation;
  apply-to-similar creates a `merchant equals Boots` rule, updates the other Boots
  transactions and catches future ones; a user rule overrides a built-in one and
  deleting it restores the default; category name clashes (including defaults,
  case-insensitive) are 409; built-ins can't be deleted; other users' categories,
  transactions, budgets and notifications are 404; a manual category on a pending
  transaction survives booking under a new ID; **US-07 exactly**: a 300 GBP Eating out
  budget alerts at 240 (80 %) and 300 (100 %), each once, ignoring spend in other
  currencies; refunds reduce spend; raising a limit re-arms alerts and lowering it
  below spend alerts immediately; month and amount validation.

**Problems and fixes**

- Test cleanup used `TRUNCATE users CASCADE`, which empties *whole* referencing
  tables in Postgres. Now that `categories` and `category_rules` reference `users`,
  it would have wiped the seeded defaults after the first test. Cleanup now uses
  `DELETE FROM users`, which cascades row by row and leaves built-in rows alone.
- mypy flagged a dictionary keyed by a nullable category ID that SQL had already
  filtered; the filter is now explicit in Python too, rather than silenced.

**Result:** 177 tests passing on the first full run, 91% coverage.

### 4.7 Documentation

Technical design (data model rows for categories, rules, budgets and the new
notifications table; categorisation and budget checks run inside the sync job
rather than as separate jobs, which keeps ordering simple), README endpoints and
status, CLAUDE.md status.

### 4.8 Verification in Docker, and a bug it found

Ran the flow against the real stack: the worker synced 567 transactions and
categorised all of them; a 5 GBP Eating out budget for the current month showed
46.30 spent (`exceeded`, 926 %) and produced one "Budget reached" notification;
apply-to-similar on a Boots transaction created a rule and moved the other 77 Boots
transactions.

**Bug found:** Subscriptions had zero transactions and Transport about double. The
built-in keyword `TFL` matches inside "NE**TFL**IX", so Netflix went to Transport.
Worse, built-in rules share a priority and creation time, so which rule ran first was
undefined. The same class of problem existed for `EE ` ("COFF**EE** SHOP" → Bills) and
`LIME` ("SUB**LIME**").

**Fixes:** more specific seed keywords (`TFL TRAVEL`, `EE LIMITED`, `LIME BIKE`; the
migration was not yet released, so amending it was safe), and a deterministic
tie-break in the engine: among otherwise equal rules the longer, more specific value
wins, then the ID. Regression checks: Netflix → Subscriptions and Shell → Fuel in the
integration test, and the tie-break in a unit test. Re-run in Docker: Subscriptions
69, Transport 64, every merchant correctly mapped. 178 tests passing.

---

## Week 5: Dashboard, PWA, audit log (BR-11, NFR-06)

### 5.1 Append-only audit log (NFR-06)

- `audit_log`: `seq` (identity), `user_id`, `action`, `entity`, `entity_id`,
  `details` (JSONB), `created_at`. `user_id` is deliberately **not** a foreign key so
  the trail survives deletion of the user; `details` holds IDs, outcomes and counts
  only, never personal data or secrets.
- **Append-only in the database:** a trigger rejects every UPDATE, DELETE and
  TRUNCATE, even with the application's own credentials. Verified by hand in
  Postgres and by an integration test through the ORM.
- Events are written **in the same transaction** as the change they describe:
  consent started / granted / renewed / not granted / expired / revoked, connection
  deleted, sync succeeded / failed (with counts), plus the deferred revoke job.
- `GET /audit-log`: the user's own trail, newest first (transparency).

**Problem and fix:** "consent revoked" and "connection deleted" are written in one
transaction, and Postgres `now()` is fixed per transaction, so both had the same
timestamp and their order was arbitrary. Added `seq BIGINT GENERATED ALWAYS AS
IDENTITY` (strict insertion order, and gaps become detectable) and ordered by it.
The migration was unreleased, so it was amended.

### 5.2 Dashboard endpoint (BR-11, NFR-08)

`GET /dashboard/summary?month=YYYY-MM`, per currency: spending and income for the
month, spending by category (largest first, with share), and a six-month trend. One
grouped SQL query (month by category by currency) feeds both. Definitions match
budgets: net outflow per category (refunds reduce it); the built-in Income category
is income; the built-in Transfers category is excluded (moving money between your own
accounts is neither spending nor income).

### 5.3 Backend tests

Exact dashboard figures from controlled data (refund, excluded transfer, income,
Uncategorized, shares 66.7 / 28.6 / 4.8 %); a year of demo data answered in under
2 s (NFR-08) with categories summing to total spending; per-user isolation and
validation; the full audit trail of connect → sync → disconnect in order; a cancelled
consent; private trails; tampering blocked. **186 tests passing, 90% coverage.**

### 5.4 Web app scaffold

- `npm create vite` (React 19, Vite 8, TypeScript, oxlint), plus React Router,
  TanStack Query, Chart.js, Tailwind CSS v4, vite-plugin-pwa, openapi-typescript,
  Vitest and Testing Library.
- TypeScript pinned to **5.9**: `openapi-typescript` needs the TypeScript JS API,
  which TypeScript 7 (native) no longer ships. `strict` turned on (the template had
  it off).
- `npm audit`: findings only in build-time tooling (`workbox-build`); production
  dependencies have none.

### 5.5 API contract and client — [ADR 0005](adr/0005-web-app-auth-and-api-types.md)

- `backend/scripts/export_openapi.py` → `docs/openapi.json` (26 paths) →
  `npm run gen:api` → `web/src/api/schema.d.ts`; CI fails if either is stale.
- `src/api/client.ts`: access token in memory, refresh token in `sessionStorage`; on
  401 one shared refresh then retry; RFC 9457 errors as `ApiError`.
- TanStack Query hooks per resource; mutations invalidate the data they affect.

### 5.6 Pages and accessibility (BR-11, NFR-11)

Sign in / register, Dashboard (month picker, renew banner, budget alerts, totals,
spending-by-category doughnut, 6-month trend, budget bars), Accounts (totals per
currency, grouped by bank), Transactions (search, status filter, per-row category with
"apply to similar", paging), Budgets, Banks (connect, sync, renew, disconnect with
confirmation) and the consent result page the API redirects to.

Accessibility: brand colours chosen for ≥ 4.5:1 contrast (most ≥ 7:1), visible focus
rings, skip link, labelled controls, progress bars with `aria-valuenow` /
`aria-valuetext` and the status in words (not colour alone), and a text alternative
for every chart (a list beside the doughnut, a visually hidden table for the trend).
Layout works from 360 px.

**Problem and fix:** the build failed with "Cannot apply unknown utility class
`btn`": Tailwind v4 only lets `@apply` reuse registered utilities, so the component
classes became `@utility` blocks.

### 5.7 PWA

`vite-plugin-pwa`: manifest (name, theme colour, standalone, 192/512 px icons incl.
maskable) and a generated service worker that precaches the app shell only, never API
responses. Icons are rendered by `web/scripts/make_icons.py` from the same design as
the favicon, keeping the drawing in the maskable safe zone.

### 5.8 Web tests and CI

- Vitest: money and month formatting; the API client (bearer header, **one** refresh
  for three concurrent 401s, session ended when refresh fails, problem details, 204);
  the budget bar's accessible value and "Over budget" wording; sign-in success,
  sign-in error message, password rule described to assistive tech. 14 tests.
- CI: a `web` job (lint with warnings as errors, strict type-check, tests, build,
  production-dependency audit) and an `api-contract` job (regenerate schema and types,
  fail on diff); publishing now waits for both. Dependabot watches `web/` too.

### 5.9 Verification in the browser

Ran the Vite dev server against the Docker backend and drove the app in the browser
pane: register → dashboard empty state → Banks → Mock Bank (UK) → the mock bank's
consent page → Approve → back on `/connections/result?status=connected`, **still
signed in after the full-page redirect** (session restored from the refresh token) →
dashboard with £305.86 spent across 7 categories and six months of trend (£2,850
income per month) → a £40 Eating out budget showing "£46.30 of £40.00 · Over budget ·
115.8%" and a "Budget reached" alert on the dashboard → transactions "1–25 of 567"
with pending markers and per-row category controls. No console errors.
Screenshots weren't possible because the browser pane was hidden.

### 5.10 CI fix: lock file generated on Windows

The first CI run of the new jobs failed at `npm ci`: "package.json and
package-lock.json are not in sync … Missing: @emnapi/core". These are optional,
platform-specific WebAssembly fallbacks (used by Rolldown, oxlint and Tailwind's
native engine); npm on Windows didn't record them in the lock file, and npm on Linux
requires them. Regenerated the lock file on Linux in a `node:24-slim` container
(`npm install --package-lock-only`), proved `npm ci` passes there, then reinstalled on
Windows with `npm ci` and re-ran lint, type-check, tests, build and audit. **Rule from
now on:** refresh `web/package-lock.json` in the Linux container, not on Windows:

```bash
docker run --rm -v "$PWD/web:/app" -w /app node:24-slim npm install --package-lock-only
```

### 5.11 Dependabot round for web/

Four PRs after `web/` joined Dependabot:

| PR | Change | Outcome |
| --- | --- | --- |
| #10 | actions/setup-node 5 → 7 | Merged. Its own CI failed only because it was branched before the lock-file fix (5.10); verified on the merged `main` run. v7 changes (ESM internals, removed dummy `NODE_AUTH_TOKEN`, cache outputs) don't affect us. |
| #11 | jsdom 29 → 31 | Merged. Breaking changes (canvas backend, new CSS engine, script-blocking parsing) don't touch our tests; clean `npm ci` plus lint, types, tests, build and audit pass locally and in CI. |
| #12 | @types/node 24 → 26 | Declined with an ignore rule: Node types must match the Node 24 runtime, or code could use APIs that don't exist. |
| #13 | typescript 5.9 → 7.0 | Declined with an ignore rule: its CI failed exactly as ADR 0005 predicts (openapi-typescript needs the TypeScript JS API). |

Dependabot closed #12 and #13 itself after reading the ignore rules. CI green on
every job.

---

## Naming

### Product name: Onesum

Chosen 2026-11-11 from a shortlist (Clearsum, Onesum, Tallyo, Pocketview, Moneyline):
it says "one view of all your money" (BR-05) and reads naturally in UK, EU, Australian
and New Zealand English. A web search found no finance app of that name; the nearest
are Onespend (an iOS expense tracker) and OneNumber (a net-worth app). A formal check
of the UK IPO trademark register and a domain are still to do.

Renamed everywhere users and reviewers see it: page title, PWA manifest name, header
and sign-in page, the mock bank's consent text, the API title in `/docs` and
`docs/openapi.json`, README, BRD, technical design and CLAUDE.md. **Not** renamed: the
`finance-app` repository and folder, the `finance_app` Python package and the npm
package name. Renaming those is a large, risky diff with no visible benefit (GitHub
keeps the repository URL either way).

---

## Yapily sandbox verification (closes the open item from Week 2)

Connected **Modelo Sandbox** through the real web app with Yapily credentials (in the
git-ignored `.env`), signing in at the bank's own page. Three things only the real
sandbox could show:

| Step | Found | Fix |
| --- | --- | --- |
| Setup | Yapily returned 0 institutions: a new sandbox application has none until one is added in the Console (Modelo Sandbox is a pre-configured institution, no Save button) | Console step, no code |
| Consent exchange | `POST /consent-one-time-token` succeeded but the app reported "couldn't be completed": the adapter required the usual `data` envelope | Accept the Consent object bare or wrapped; failed consents now log a reason naming response *fields* only, never values |
| Transactions | `400` "The before date cannot be in the future": `before` was end of today, and even "now" failed because our clock runs seconds ahead of Yapily's | Cap `before` at now minus 2 minutes (the next sync's 3-day overlap covers the gap) |
| Transactions | A 365-day request took 24-28 s per page and timed out at 15 s; 30 days took 1.4-3.1 s | Fetch in 31-day windows, each paged |

Confirmed against the sandbox: our `state` survives the bank redirect, and the
callback parameter is `one-time-token` (the two open questions of ADR 0003).

**Result:** consent granted; 3 accounts (current, loan, credit card) with balances and
masked numbers; 23,555 transactions for 12 months in 44 requests and 132 s; no
duplicates (rows = distinct dedup keys = distinct Yapily IDs); dashboard 32 ms,
first transactions page 48 ms and a text search 112 ms at that volume (NFR-08). Modelo's
test data marks every transaction `PENDING` and uses random descriptions, so few match
the UK keyword rules (53 categorised); real banks send merchant names.

Each fix has a contract test from the real response shape (bare Consent object,
fields-not-values error message, `before` never in the future, monthly windows):
114 unit tests passing.

## UI redesign: calm overview, header and footer (BR-11)

The first web UI worked but looked generic, and real sandbox data exposed problems:
the trend axis read "£30,000,000.00", the doughnut was one solid ring (99.8%
uncategorised), EUR appeared before GBP, and pages flashed a bare "Loading…". Three
directions were mocked up; the owner chose **A (calm overview)** with **header 1**
(top bar, underline tabs) and **footer A** (full footer).

| Area | Change | Why |
| --- | --- | --- |
| Header | White sticky bar with logo mark, underline tabs, sync status ("Synced 4 min ago", links to Banks, turns red on a failed sync), alerts bell with a count, avatar menu (email from `/me`, sign out; closes on Escape or outside click) | Lighter than the dark-green bar; status a user cares about is always visible |
| Mobile | Below `md` the tabs move to a fixed bottom tab bar (safe-area aware); the header keeps logo, sync icon, bell and avatar | Thumb reach in the installed PWA |
| Footer | Product, Trust and Project link columns, "read-only, never moves your money", "portfolio project, sandbox data only", app version | Tells a reviewer what the app is and where the code, API docs and security notes are |
| Overview | Net worth, spent this month vs last month, budget status; ranked category bars; 6-month trend with the selected month highlighted; recent activity; accounts summary; budgets | Numbers first, one screen |
| Charts | Doughnut replaced by horizontal bars (top 5, rest grouped, "Over budget" in words); axis labels compact ("£1.2k", "£30m") | Lengths compare better than slices; an outlier can no longer make the axis unreadable |
| Currency | GBP first, then alphabetical; other currencies get their own section only if they had spending that month | UK-first product |
| Loading | Skeleton placeholders shaped like the content (`role="status"`, no pulse with reduced motion) | No layout jump, no bare text flash |

Money stays exact: the month-on-month difference and the grouped "N more categories"
total are computed in integer pence (`toMinor`/`subtractMoney`, BigInt), never in
floating point; `Number()` is used only for bar widths and chart heights. Icons are
inline SVG (no icon library). `/docs` and `/openapi.json` are proxied in development
and excluded from the service worker's navigation fallback, so the footer's API docs
link works. Tests: exact subtraction (0.30 − 0.10), compact labels, currency order,
relative times, category grouping and the over-budget label (20 web tests).
Checked in the browser at 1280 px and 375 px with Yapily sandbox data.

### Demo video

A walkthrough video (`docs/media/onesum-demo.mp4`, 1 min 37 s, 1280×800) and a poster
frame (`docs/media/onesum-overview.png`) are linked from the README. Recorded with
Playwright driving local Chrome against the Docker stack with `BANK_PROVIDER=mock`
(a throwaway demo user with a random password), desktop then a 390 px phone viewport,
joined with ffmpeg (H.264, `+faststart` so it streams). The first take showed no budget
alert: recategorising one Tesco row with "apply to similar" moved all Tesco spending
out of Groceries, so the script budgets Eating out instead.

A second, phone-only take (`docs/media/onesum-demo-mobile.mp4`, 60 s) runs the full flow
at 390×844 with touch input. Playwright pads rather than upscales when the video size
exceeds the viewport, so the clip is cropped to the viewport and scaled 2× with ffmpeg.
