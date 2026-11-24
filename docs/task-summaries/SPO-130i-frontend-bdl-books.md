# SPO-130i — frontend BALLDONTLIE books

## Summary

The site's book list, bet-slip load, and Method credit follow BALLDONTLIE. NBA odds no longer come from The Odds API once Backend's 130i is in place. This branch does not add a route and does not change a Zod shape. It must merge in the same batch as Backend's 130i, and not before it.

`frontend/` does not read `odds_api_quota`. That was checked with a search and left unchanged.

## Changes

| Area | What changed |
|---|---|
| Books | `frontend/lib/schemas.ts` `BOOKMAKERS` / `BookmakerKey` is exactly `draftkings`, `fanduel`, `betmgm`, `caesars`, `betrivers`, `fanatics`, `betparx`, `ballybet`, `betway`, `rebet`. The comment points at BALLDONTLIE (`https://www.balldontlie.io`, API `https://api.balldontlie.io`). |
| Names | `getBookmakerDisplayName` adds Fanatics, Rebet, and Bally Bet for `ballybet`. `bally_bet` stays only as a display alias. `bovada`, `betonlineag`, `espnbet`, and `williamhill_us` are gone from the map, so those keys render as themselves. |
| Selector | `FEATURED_BOOKMAKERS` is DraftKings, FanDuel, BetMGM, Caesars, BetRivers, Fanatics. ESPN Bet and Bet365 are not featured. Choosing Bally Bet sends `ballybet`. |
| Slip | `BetSlipContext` still uses `betslip_picks` and still deletes `wnba_betslip_picks`. On load it drops an event id matching `/^[0-9a-f]{32}$/i`. After today's `getEvents` call succeeds, it also drops a hydrated pick whose event is not in that list. A failed or still-loading events request does not drop picks for that second reason. Picks added after load are left alone. `api.ts`, event links, and the event page are unchanged. |
| Method | `frontend/app/about/page.tsx` credits BALLDONTLIE at `https://www.balldontlie.io`. |
| Tests | Book key order, display names, featured order, the `ballybet` click, the About credit, and the four hydrate cases. |

## Why

A slip saved under The Odds API uses a 32-hex event id. BALLDONTLIE game ids are not that shape, and today's slate is the list `GET /api/nba/events` already returns. Filtering only after a successful events response means a network blip cannot empty the slip. The 32-hex rule does not need that response, so those dead ids still leave immediately.

The book keys match the BALLDONTLIE vendor allow-list. The request key for Bally Bet is `ballybet`. `bally_bet` is not sent.

## Tests

`cd frontend && npm test` (`TZ=America/Chicago vitest run`): **91 files, 676 tests, all passed.**

`npx tsc --noEmit`: passed, no output.

`npm run lint` (`next lint`): no ESLint warnings or errors.

No frontend test hard-coded a 32-hex event id as a valid pick. The new hydrate tests use `07361a8381206817e27bd2697fad7479` only as an id that must be removed.

### Mutation check

After the green suite, `isLegacyOddsApiEventId` was changed to always return false (the 32-hex filter off). `npx vitest run contexts/BetSlipContext.test.tsx`:

- **Red:** "drops a 32-hex event id and the retired slip key". Events were still loading, so the slip still showed `07361a8381206817e27bd2697fad7479` and `ABCDEF0123456789abcdef0123456789`.
- **Red:** "does not drop a pick for missing events when the events request fails". The hex id stayed next to `not-on-slate` and `184729`.
- **Still green:** "drops a pick that is not on today's events list and keeps one that is". The mocked slate did not include the hex id, so the events-list filter removed it anyway.

The function was restored. The same file was re-run: **3 passed.**

## /metrics

Search of `frontend/` for `odds_api_quota`: no matches. Nothing in the frontend reads that field. No file was changed for it.

## Progress note

- Book list, featured books, slip load, and the Method credit now follow BALLDONTLIE.
- Ship this with Backend's 130i. Do not merge it first.
- `docs/progress.md`, the repo context doc, backend, data, scripts, and CI were not edited.
- No new route. No Zod shape change. `betslip_picks` was not renamed.
