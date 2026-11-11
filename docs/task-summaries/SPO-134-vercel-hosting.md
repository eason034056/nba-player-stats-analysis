# SPO-134 — Vercel-ready frontend build

- Ticket: SPO-134
- Branch: `feature/SPO-134-vercel-hosting` (from `origin/dev` @ `4bfb2ec`)
- Base: `dev`

## Summary

The Next.js 14 frontend can be hosted on Vercel while the API stays on an HTTPS backend whose domain is not chosen yet. The browser calls the same origin at `/api/backend/:path*`. `next.config.js` rewrites that path to `BACKEND_API_URL`. That variable is server-only. A Vercel build that does not have it fails. Local `next dev` and a local `next build` still default to `http://localhost:8000`.

## Changes

| File | Change |
|---|---|
| `frontend/lib/browser-api-prefix.js` | Same-origin prefix `/api/backend`. No environment read. |
| `frontend/lib/backend-origin.js` | Resolves `BACKEND_API_URL`. Local default is localhost. A Vercel build without the variable throws. |
| `frontend/lib/api.ts` | `fetchApi` uses the prefix. It no longer reads `NEXT_PUBLIC_API_URL`. |
| `frontend/next.config.js` | Removes the `env:` localhost bake. Adds the rewrite and a 120s local `proxyTimeout`. |
| `frontend/next.config.test.ts` | Dev default, rewrite destination, missing Vercel variable, and a non-origin URL. |
| `frontend/lib/player-dd-routes.test.ts` | Expects `/api/backend` instead of `http://localhost:8000`. |
| `frontend/lib/spo122.qa.test.ts` | Parses the relative URL with a dummy base. NBA and WNBA query strings are unchanged. |
| `frontend/.env.example` | `BACKEND_API_URL=https://api.example.com` plus comments. No real host. |
| `docs/deployment/vercel.md` | zh-TW steps for the owner: import, Root Directory `frontend`, env vars, Production branch `master`, Preview branch `dev`. |

No `vercel.json`. With Root Directory set to `frontend` in the Vercel project, the dashboard already selects Next.js, npm, and `next build`. The rewrite lives in `next.config.js`.

`docs/progress.md` is not changed.

## Why

Two ways were on the table.

(a) The browser calls `NEXT_PUBLIC_API_URL` directly. The backend must allow the Vercel origins in CORS, and the origin is visible in the client bundle.

(b) A server-only `BACKEND_API_URL` plus `rewrites()`, so the browser calls `/api/backend/:path*` and Vercel proxies to the backend.

(b) is the one this change uses.

What the frontend actually calls:

- Every backend request goes through `fetchApi` in `frontend/lib/api.ts`, then `response.json()`.
- The Agent Widget calls `sendAgentChat`, which is `POST /api/nba/agent/chat` and parses JSON. The backend handler returns `AgentChatResponse`. It is not a `StreamingResponse`.
- There is no `EventSource`, no `ReadableStream` consumer, and no `text/event-stream` caller.
- There is no `frontend/app/api` route and no server component that fetches the backend. Call sites are `"use client"` components using TanStack Query. `useQuery` does not prefetch during server render unless `experimental_prefetchInRender` is set, and it is not.
- Team logos use `a.espncdn.com`, already listed in `images.remotePatterns`. They are not built from the API origin.
- `frontend/public/sw.js` only handles navigations and static assets. A `GET` to `/api/backend/...` is not intercepted.

Streaming check, against a local upstream that writes four SSE chunks 250ms apart:

| Hop | `next dev` | `next start` |
|---|---|---|
| `GET /api/backend/api/health` | 200, upstream saw `/api/health` | same |
| `GET /api/backend/api/nba/events?date=2026-01-14` | query kept, prefix stripped | same |
| `GET /api/backend/api/wnba/events?date=2026-01-14` | WNBA path kept | same |
| `POST /api/backend/api/nba/agent/chat` with `{"message":"hi"}` | body arrived intact | same |
| SSE with `Cache-Control: no-cache, no-transform` | 4 chunks, ~250ms apart | 4 chunks, ~250ms apart |
| SSE without that header | one chunk after ~1000ms (buffered) | one chunk after ~1000ms (buffered) |

The Node `fetch` in that probe is a server-side HTTP client hitting the Next server. The app itself has no server-side backend fetch to send through the rewrite. `next build` still prerendered all 10 pages, including `/wnba`, `/wnba/picks`, `/wnba/betslip`, `/wnba/event/[eventId]`, and `/wnba/player/[name]`, with no backend running.

Vercel documents a 120 second limit for a rewrite to an external host (`ROUTER_EXTERNAL_TARGET_ERROR`). `experimental.proxyTimeout` is 120000 ms so local `next dev` / `next start` match that cap instead of Next's 30 second default. Vercel does not read `proxyTimeout`. A cold daily-picks refresh or a slow agent reply can still hit the platform limit. That is a follow-up, not a reason to put the origin in the browser: nothing in the client streams today, and (a) would not raise the Vercel cap for a request that still has to be proxied.

`NEXT_PUBLIC_` search under `frontend/`: the only hit is a comment in `frontend/.env.example` saying `BACKEND_API_URL` has no `NEXT_PUBLIC_` prefix. No public variable is assigned. None of them is an API key or token.

Production branch is `master`. Preview for this repo is `dev`. There is no `main` branch, and this change does not create one. Other non-production branches also get Preview deployments; that is Vercel's default.

## Tests / Verification

- `npx vitest run` — 56 files, 396 tests, passed.
- `npx tsc --noEmit` — passed.
- `npm run lint` — passed, 0 warnings.
- `next build` with `VERCEL`, `VERCEL_ENV`, and `BACKEND_API_URL` unset — passed (exit 0). Static pages 10/10, WNBA routes included.
- `VERCEL=1 VERCEL_ENV=production BACKEND_API_URL=https://api.example.com next build` — passed (exit 0). `routes-manifest.json` destination is `https://api.example.com/:path*`. `api.example.com` and `localhost:8000` are absent from `.next/static`.
- `VERCEL=1` with `BACKEND_API_URL` unset — failed (exit 1) with `BACKEND_API_URL is required when VERCEL or VERCEL_ENV is set` and `will not fall back to http://localhost:8000`.
- Integration test: SKIPPED. No new external API client.
- A Vercel project was not created. `vercel login` and `vercel link` were not run.

## Follow-ups

- Put the real HTTPS origin in the Vercel Production and Preview environments when the EC2 domain exists, then redeploy without the old build cache.
- Requests longer than 120 seconds need a different path than this rewrite. Raising `proxyTimeout` does not change the Vercel platform limit.
- A future SSE endpoint must send `Cache-Control: no-cache, no-transform`, or the Next proxy buffers the body.
- Browser CORS stays unnecessary while the rewrite is the only client path.
