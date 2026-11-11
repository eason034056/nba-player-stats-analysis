# SPO-134 — Vercel-ready frontend build

- Ticket: SPO-134
- Branch: `feature/SPO-134-vercel-hosting` (from `origin/dev` @ `4bfb2ec`)
- Base: `dev`

## Summary

The Next.js 14 frontend can be hosted on Vercel while the API stays on an HTTPS backend whose domain is not chosen yet. The browser calls the same origin at `/api/backend/:path*`. `frontend/middleware.ts` proxies that path to `BACKEND_API_URL`, sets `x-sportslab-proxy-secret` from `VERCEL_PROXY_SECRET`, and sets `x-real-ip` to the client IP Vercel provides. Both variables are server-only. A Vercel build that is missing either one fails. Local `next dev` and a local `next build` still default to `http://localhost:8000` and omit the secret header.

Do not send production traffic until the backend (SPO-133) checks `x-sportslab-proxy-secret` and keys its rate limiter on `x-real-ip`. Caddy overwrites `X-Forwarded-For`. Until that backend change, every visitor shares the slowapi limits, because the TCP peer is a Vercel egress address.

## Changes

| File | Change |
|---|---|
| `frontend/lib/browser-api-prefix.js` | Same-origin prefix `/api/backend`. No environment read. |
| `frontend/lib/backend-origin.js` | Resolves `BACKEND_API_URL`. Local default is localhost. A Vercel build without the variable throws. Invalid values are not echoed. A Vercel build rejects `http`. |
| `frontend/lib/proxy-request.js` | Builds the proxy headers. Replaces any browser `x-sportslab-proxy-secret` and `x-real-ip`. |
| `frontend/middleware.ts` | The only proxy. Rewrites `/api/backend/:path*` and returns 500 when a Vercel runtime has no secret. |
| `frontend/lib/api.ts` | `fetchApi` uses the prefix. It no longer reads `NEXT_PUBLIC_API_URL`. |
| `frontend/next.config.js` | Removes the `env:` localhost bake and the `rewrites()` entry. A production build asserts the origin and the secret. Local `proxyTimeout` stays 120s. |
| `frontend/next.config.test.ts` | Build failure for a missing origin, an `http` origin, and a missing secret. |
| `frontend/lib/backend-origin.qa.test.ts` | Origin normalization, rejected shapes, and error messages that omit the configured value. |
| `frontend/lib/proxy-request.test.ts` | Secret from the env var, browser secret replaced, browser `x-real-ip` replaced. |
| `frontend/middleware.test.ts` | Rewrite header names, including `x-middleware-request-x-real-ip`. |
| `frontend/lib/player-dd-routes.test.ts` | Expects `/api/backend` instead of `http://localhost:8000`. |
| `frontend/lib/spo122.qa.test.ts` | Parses the relative URL with a dummy base. NBA and WNBA query strings are unchanged. |
| `frontend/.env.example` | Commented placeholders for `BACKEND_API_URL` and `VERCEL_PROXY_SECRET`. |
| `frontend/package.json` | `engines.node` is `22.x`. |
| `.github/workflows/ci.yml` | Frontend jobs use Node 22. The lint job runs `next build` with placeholder env. |
| `docs/deployment/vercel.md` | zh-TW steps: import, Root Directory `frontend`, both env vars, Node 22.x, Production branch `master`, Preview branch `dev`, deployment protection. |

No `vercel.json`. `routes` transforms can set a header from an env var, and they can sit next to `rewrites`, but a missing variable is forwarded as the literal `$VAR`, a transform cannot copy the visitor IP into `x-real-ip`, and `next start` does not apply `vercel.json` routes. Middleware is the one proxy path.

`docs/progress.md` is not changed.

## Why

Two ways were on the table.

(a) The browser calls `NEXT_PUBLIC_API_URL` directly. The backend must allow the Vercel origins in CORS, and the origin is visible in the client bundle.

(b) A server-only `BACKEND_API_URL` plus a same-origin `/api/backend/:path*` proxy.

(b) is the one this change uses. The proxy is middleware, not `next.config.js` `rewrites()`, because the rewrite cannot add the secret or replace `x-real-ip`.

What the frontend actually calls:

- Every backend request goes through `fetchApi` in `frontend/lib/api.ts`, then `response.json()`.
- The Agent Widget calls `sendAgentChat`, which is `POST /api/nba/agent/chat` and parses JSON. The backend handler returns `AgentChatResponse`. It is not a `StreamingResponse`.
- There is no `EventSource`, no `ReadableStream` consumer, and no `text/event-stream` caller.
- There is no `frontend/app/api` route and no server component that fetches the backend. Call sites are `"use client"` components using TanStack Query. `useQuery` does not prefetch during server render unless `experimental_prefetchInRender` is set, and it is not.
- Team logos use `a.espncdn.com`, already listed in `images.remotePatterns`. They are not built from the API origin.
- `frontend/public/sw.js` only handles navigations and static assets. A `GET` to `/api/backend/...` is not intercepted.

Streaming check, against a local upstream that writes four SSE chunks 250ms apart, using the earlier `rewrites()` proxy. Middleware uses the same `proxyRequest` path (`router-server.js` calls it when the middleware rewrite URL has a protocol):

| Hop | `next dev` | `next start` |
|---|---|---|
| `GET /api/backend/api/health` | 200, upstream saw `/api/health` | same |
| `GET /api/backend/api/nba/events?date=2026-01-14` | query kept, prefix stripped | same |
| `GET /api/backend/api/wnba/events?date=2026-01-14` | WNBA path kept | same |
| `POST /api/backend/api/nba/agent/chat` with `{"message":"hi"}` | body arrived intact | same |
| SSE with `Cache-Control: no-cache, no-transform` | 4 chunks, ~250ms apart | 4 chunks, ~250ms apart |
| SSE without that header | one chunk after ~1000ms (buffered) | one chunk after ~1000ms (buffered) |

The Node `fetch` in that probe is a server-side HTTP client hitting the Next server. The app itself has no server-side backend fetch. `next build` still prerendered all 10 pages, including the `/wnba` routes, with no backend running.

Header check under `next start`, upstream `127.0.0.1:3999`. The browser sent `x-real-ip: 198.51.100.9`, `x-forwarded-for: 203.0.113.50, 10.0.0.8`, and `x-sportslab-proxy-secret: browser-sent-secret`. The upstream received `x-real-ip: 203.0.113.50`, `x-forwarded-for: 203.0.113.50`, and `x-sportslab-proxy-secret` equal to the env value. The spoofed IP and the browser secret were absent. A second request with `x-vercel-forwarded-for: 203.0.113.77` set both `x-real-ip` and `x-forwarded-for` to `203.0.113.77`. With `VERCEL=1` and no secret, `next start` returned 500 `The API proxy is not configured.` and the upstream was not contacted. With no Vercel env and no secret, the upstream received `x-real-ip: 203.0.113.50` and no secret header.

Vercel documents a 120 second time-to-first-byte limit for a rewrite to an external host (`ROUTER_EXTERNAL_TARGET_ERROR`). After the first byte, a response that keeps sending data at least every 120 seconds can run longer. `experimental.proxyTimeout` is 120000 ms so local `next dev` / `next start` are not cut at Next's 30 second default. Vercel does not read `proxyTimeout`.

`NEXT_PUBLIC_` under `frontend/`: the only hit is a comment in `frontend/.env.example` saying `BACKEND_API_URL` has no `NEXT_PUBLIC_` prefix. No public variable is assigned. The proxy secret is read as `process.env.VERCEL_PROXY_SECRET` inside the middleware bundle. The value is not written into `.next/static`.

Production branch is `master`. Preview for this repo is `dev`. There is no `main` branch, and this change does not create one.

## Tests / Verification

- `npx vitest run` — 59 files, 412 tests, passed.
- `npx tsc --noEmit` — passed.
- `npm run lint` — passed, 0 warnings.
- `next build` with `VERCEL`, `VERCEL_ENV`, `BACKEND_API_URL`, and `VERCEL_PROXY_SECRET` unset — passed (exit 0). Static pages 10/10, WNBA routes included.
- `VERCEL=1 VERCEL_ENV=production BACKEND_API_URL=https://api.example.com VERCEL_PROXY_SECRET` set — passed (exit 0). The placeholder secret and `api.example.com` were absent from `.next/static`.
- `VERCEL=1` with `BACKEND_API_URL` unset — failed (exit 1) with `BACKEND_API_URL is required when VERCEL or VERCEL_ENV is set` and `will not fall back to http://localhost:8000`. The log did not contain `Received:`.
- `VERCEL=1 BACKEND_API_URL=https://api.example.com` with `VERCEL_PROXY_SECRET` unset — failed (exit 1) with `VERCEL_PROXY_SECRET is required`.
- `VERCEL=1 BACKEND_API_URL=http://api.example.com` — failed (exit 1) with `BACKEND_API_URL must use https on a Vercel build.`
- `next start` echo upstream — headers listed above, including `x-real-ip`.
- Integration test: SKIPPED. No new external API client.
- A Vercel project was not created. `vercel login` and `vercel link` were not run.

## Follow-ups

- Put the real HTTPS origin in the Vercel Production and Preview environments when the EC2 domain exists, then redeploy without the old build cache.
- Put the same `VERCEL_PROXY_SECRET` in Vercel and in the backend's AWS SSM. Rotate both, then redeploy. Do not send production traffic until SPO-133 verifies the header and rates limits on `x-real-ip`.
- `master` does not contain this frontend until `dev` is merged. The first Production deployment of a new Vercel project builds `master`.
- The 120 second platform limit is time to first byte. Raising `proxyTimeout` does not change it.
- A future SSE endpoint must send `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no` (nginx in front of EC2 also buffers), and a heartbeat at least every 120 seconds.
- Browser CORS stays unnecessary while this proxy is the only client path. If the backend later sends `Cache-Control: public`, the Vercel CDN will cache the response.
