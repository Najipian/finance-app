# Onesum — web (React PWA)

React 19 + Vite + TypeScript (strict), Tailwind CSS v4, TanStack Query, Chart.js,
installable as a PWA. See the [root README](../README.md) and
[ADR 0005](../docs/adr/0005-web-app-auth-and-api-types.md).

```bash
npm install
npm run dev        # http://localhost:5173; /api is proxied to the backend on :8000
npm test           # Vitest + Testing Library
npm run lint       # oxlint, warnings fail
npm run typecheck  # tsc --strict
npm run build      # production build + service worker
npm run gen:api    # regenerate src/api/schema.d.ts from ../docs/openapi.json
```

`src/api/schema.d.ts` is generated: don't edit it by hand. CI fails if it is out of
date with the backend's OpenAPI schema.
