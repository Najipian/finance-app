# 3. Bank consent flow: one-time tokens, single-use state, encrypted at rest

Date: 2026-11-11 · Status: Accepted

## Context

BR-02 connects a bank through a redirect to the bank and back. The callback is a
browser navigation, so it carries no access token. Done naively, three things go
wrong: the long-lived consent token ends up in a URL (browser history, proxy logs),
an attacker can forge or replay the callback (CSRF), and bank secrets sit in the
database in plain text. Planning put token encryption in Week 5, but tokens are
first stored in Week 2.

## Decision

- **One-time token exchange.** The authorisation request sets `oneTimeToken: true`.
  The callback receives a short-lived (about 3 minutes) one-time token, which the API
  exchanges server-side (`POST /consent-one-time-token`). The consent token never
  appears in a URL.
- **Single-use `state` in Redis.** Starting a connection creates a *pending* row and a
  random 256-bit `state` stored as `state → (user_id, connection_id)` with a
  10-minute TTL. The callback consumes it atomically with `GETDEL`; unknown, expired
  or reused states are rejected. The state rides in our callback URL's query string.
- **Outcomes are redirects.** The callback always answers `303` to the web app with
  `status=connected|cancelled|error|invalid_state`, so users get a clear page.
  A cancelled or failed consent deletes the pending row: nothing is stored.
- **Encrypt now (AES-256-GCM).** Consent tokens are encrypted before storage in
  Week 2 rather than Week 5, with a random nonce, a key version prefix for rotation,
  and the connection ID as associated data, so a ciphertext copied to another row
  fails to decrypt. Provider consent IDs are stored in plain text: they are useless
  without the application credentials and are needed for revocation lookups.
- **Bank I/O in the worker.** The callback only stores the consent and queues
  `sync_accounts` (arq). Accounts and balances are fetched by the worker.

## Consequences

- **Verified against the Yapily sandbox on 2026-11-11 (Modelo Sandbox):** the state
  survives the redirect and the parameter is `one-time-token`; see the development
  log. Originally open, before sandbox credentials: the exact name of the one-time-token callback parameter (assumed
  `one-time-token`, matching Yapily's other callback parameters), and that Yapily
  preserves our `state` query parameter when appending its own. If it does not,
  switch to `forwardParameters` or carry the state in the callback path.
- The mock provider implements the same redirect contract with a demo bank page, so
  the whole flow is testable and demo-able offline.
- Key rotation: add the old key to `TOKEN_ENCRYPTION_RETIRED_KEYS`, bump
  `TOKEN_ENCRYPTION_KEY_VERSION`; a later job can re-encrypt values that
  `needs_reencryption`.
