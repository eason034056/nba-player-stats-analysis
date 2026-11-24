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
| Slip | `BetSlipContext` still uses `betslip_picks` and still deletes `wnba_betslip_picks`. On load it drops only an event id matching `/^[0-9a-f]{32}$/i`. It does not call `getEvents` and does not remove a pick because that game is missing from today's slate. A pick for tomorrow stays. An empty slate does not clear the slip. `api.ts`, event links, and the event page are unchanged. |
| Method | `frontend/app/about/page.tsx` credits BALLDONTLIE at `https://www.balldontlie.io`. |
| Tests | Book key order, display names, featured order, the `ballybet` click, the About credit, and the hydrate cases: a 32-hex id is dropped, a non-hex id that is not on today's slate is kept, a digit-only id is kept, and `wnba_betslip_picks` is removed. The slip tests do not mock `getEvents`. |

## Why

A slip saved under The Odds API uses a 32-hex event id. BALLDONTLIE game ids are not that shape, so those stored ids are removed on load. A pick for a later game is still a real pick, and a day with no games must not wipe the slip, so the load step does not read `/api/nba/events`.

The book keys match the BALLDONTLIE vendor allow-list. The request key for Bally Bet is `ballybet`. `bally_bet` is not sent.

## Tests

`cd frontend && npm test` (`TZ=America/Chicago vitest run`): **91 files, 677 tests, all passed.**

`npx tsc --noEmit`: passed, no output.

`npm run lint` (`next lint`): no ESLint warnings or errors.

No frontend test hard-coded a 32-hex event id as a valid pick. The hydrate tests use `07361a8381206817e27bd2697fad7479` only as an id that must be removed. They do not mock `getEvents`.

### Mutation check

After the green suite, `isLegacyOddsApiEventId` was changed to always return false (the 32-hex filter off). `npx vitest run contexts/BetSlipContext.test.tsx`: **1 failed, 3 passed.**

- **Red:** "drops a 32-hex event id". The slip still showed `07361a8381206817e27bd2697fad7479` and `ABCDEF0123456789abcdef0123456789` next to `184729`.
- **Still green:** "keeps a non-hex pick for an event that is not on today's slate", "keeps a digit-only event id", and "removes the retired wnba slip key". Those three do not need the hex filter to drop a pick.

The function was restored. The same file was re-run: **4 passed.**

## /metrics

Search of `frontend/` for `odds_api_quota`: no matches. Nothing in the frontend reads that field. No file was changed for it.

## Progress note

- Book list, featured books, slip load, and the Method credit now follow BALLDONTLIE.
- On load the slip drops only a 32-hex event id. It does not fetch today's games.
- Ship this with Backend's 130i. Do not merge it first.
- `docs/progress.md`, the repo context doc, backend, data, scripts, and CI were not edited.
- No new route. No Zod shape change. `betslip_picks` was not renamed.
