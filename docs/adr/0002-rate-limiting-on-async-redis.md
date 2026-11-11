# 2. Rate limiting with a small async Redis limiter instead of slowapi

Date: 2026-11-11 · Status: Accepted

## Context

The technical design calls for throttling auth endpoints (and later sync endpoints)
and names slowapi. Two of slowapi's properties clash with rules in `CLAUDE.md`:

- **Blocking I/O.** slowapi calls the synchronous API of the `limits` library, so
  every check against a Redis backend is a blocking network call inside an async
  request handler. The project rule is "no blocking I/O in async functions".
- **Global state.** Its `@limiter.limit(...)` decorators bind to a module-level
  `Limiter` instance created at import time, before settings (Redis URL, limits)
  are known. The project rule is dependencies through FastAPI `Depends`, no
  module-level clients. It also requires a `request: Request` parameter on every
  limited route.

## Decision

Implement a small fixed-window limiter (`core/rate_limit.py`) on the async Redis
client the app already owns:

- One Redis transaction per check: `INCR` the window key, `EXPIRE ... NX` (so the
  window doesn't slide), `TTL` for `Retry-After`.
- Created in the app lifespan, injected with `Depends`; per-IP limits are a
  reusable dependency (`limit_per_ip("login")`).
- Over the limit → `RateLimitedError` → RFC 9457 problem, HTTP 429, `Retry-After`.
- Limits come from settings: 10 requests/minute per IP per auth endpoint, and
  5 login attempts per 15 minutes per account (any IP). Account keys use a SHA-256
  of the normalised email, so no personal data is stored in Redis or logged.
- **Fails open**: if Redis is unreachable the request is allowed and a warning is
  logged. Readiness already reports Redis as down.

## Consequences

- No new dependency; fully async; easy to test against real Redis (testcontainers).
- Fixed windows allow up to 2× the limit across a window boundary. Acceptable for
  slowing brute force; a sliding-window or token-bucket variant can replace the
  internals without touching routes.
- Per-IP limits need the real client IP. Behind a reverse proxy, uvicorn runs with
  `--proxy-headers` and the proxy must be listed in `FORWARDED_ALLOW_IPS`;
  otherwise all clients share the proxy's IP. To be configured in Week 6.
- Failing open trades strict throttling for availability during a Redis outage.
  Revisit (fail closed for login only) if the app ever handles real customers.
- `CLAUDE.md` and the technical design list this limiter instead of slowapi.
