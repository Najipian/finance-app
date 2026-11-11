# 5. Web app: token storage, generated API types, no API caching

Date: 2026-11-11 · Status: Accepted

## Context

The React PWA (`web/`) needs to hold the user's session, call a typed API, and work
offline as an installable app, without putting financial data at risk.

## Decision

- **Tokens.** The 15-minute access token lives only in memory. The single-use
  refresh token is kept in `sessionStorage`: it survives a reload and the full-page
  redirect back from the bank, and is cleared when the tab closes. On a 401 the
  client refreshes **once**, shared by concurrent requests (a second refresh with
  the same token would trip the API's reuse detection and end the session), then
  retries.
- **Types from the API.** `backend/scripts/export_openapi.py` writes
  `docs/openapi.json`; `openapi-typescript` generates `web/src/api/schema.d.ts`. CI
  regenerates both and fails if they differ from what is committed, so frontend and
  backend can't drift silently. This needs TypeScript 5.9: `openapi-typescript` uses
  the TypeScript JavaScript API, which TypeScript 7 (native) no longer ships.
- **Service worker caches the app shell only.** API responses contain personal
  financial data and are never cached; `/api/` is excluded from the navigation
  fallback.
- **Money stays decimal strings** from API to screen; the UI only formats them.
- **Same origin.** Vite proxies `/api` in development, so no CORS is needed; the
  production deployment (Week 6) serves the web app and API under one origin.

## Consequences

- `sessionStorage` is readable by scripts on the page, so an XSS bug could steal the
  refresh token. Mitigations today: React escapes output, no `dangerouslySetInnerHTML`,
  single-use rotating refresh tokens with reuse detection, 15-minute access tokens.
  Week 6 hardening: move the refresh token to an `HttpOnly; Secure; SameSite=Strict`
  cookie scoped to `/api/v1/auth`, with CSRF protection, plus a strict
  Content-Security-Policy.
- Signing in again is needed after closing the tab (acceptable for a finance app).
- The `npm audit` findings are in build-time tooling (`workbox-build` via
  `vite-plugin-pwa`); production dependencies have none. CI fails on high-severity
  issues in production dependencies only.
