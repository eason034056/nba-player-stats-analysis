# SPO-156 — slip id and bookmaker follow-ups

## Summary

Frontend follow-up to #126. A stored bookmaker key `bally_bet` is rewritten to `ballybet` before it is posted. An event id made only of digits is never treated as a retired Odds API id, including a 32-digit id. Comments that describe current BALLDONTLIE behavior no longer call it the Odds API. The legacy-id cleanup still names the retired Odds API.

## Changes

| Area | What changed |
|---|---|
| Book key | `canonicalBookmakerKey` / `canonicalBookmakerList` in `frontend/lib/schemas.ts`. `bally_bet` becomes `ballybet`. Other keys stay. `null` and `undefined` stay an empty filter. |
| Read sites | `calculateNoVig` maps the list before `JSON.stringify`. `EventDetail` maps the form value before `mutate`. `BookmakerSelect` reads `value` through the same function, and writes the canonical list back when an alias is present. `getBookmakerDisplayName("bally_bet")` is still "Bally Bet". |
| Slip ids | `isLegacyOddsApiEventId` returns false for any all-digit string, then keeps the 32-hex check. A 32-character id with a letter a-f is still dropped. |
| Comments | `schemas.ts` top-read market, `today-board.ts` `marketShort`, and `use-player-dd.ts` now say BALLDONTLIE. The FGM note and the slip filter say they mean the retired Odds API. |
| Tests | QA patch applied, then renamed off `*.qa.test.*`. Two expectations updated for the new behavior. One new case in `BetSlipContext.test.tsx`. |

## Why

BALLDONTLIE's vendor key is `ballybet`, and its game ids are digits. The old regex `/^[0-9a-f]{32}$/i` also matches 32 digits, so a long numeric id would be deleted on slip load. Posting `bally_bet` would ask for a key that is not in `BOOKMAKERS`.

No `localStorage` key stores a bookmaker. `betslip_picks` has no bookmaker field. The stored selection is the string list a caller already holds (the select value, the event form, or the no-vig request). One function maps that list. Display stays a separate map.

## Tests

`cd frontend && npx vitest run`: **96 files, 690 tests, all passed.**

`npx tsc --noEmit`: passed, no output.

`npm run lint` (`next lint`): no ESLint warnings or errors.

### Mutation check

Fix 1 undone by making `canonicalBookmakerKey` return the key unchanged. `npx vitest run components/BookmakerSelect.request.test.tsx lib/bookmakers.allow-list.test.ts lib/bookmakers.test.ts`: **1 failed, 7 passed.**

- **Red:** "posts ballybet when the stored value is bally_bet". The body was `["bally_bet"]`.
- **Still green:** featured order, the Bally Bet click (that path already sends `ballybet`), and the display-alias tests.

The function was restored.

Fix 2 undone by removing the all-digit early return, so `/^[0-9a-f]{32}$/i` applied again. `npx vitest run contexts/BetSlipContext.test.tsx contexts/BetSlipContext.hydrate.test.tsx`: **2 failed, 7 passed.**

- **Red:** "keeps an all-digit id that is 32 characters". The slip was empty.
- **Red:** "drops a 32-character id only when it contains a letter a-f". The 32 ones were missing. The 31-digit and 33-digit ids stayed.
- **Still green:** the short digit id, the recorded BALLDONTLIE id, tomorrow's pick, the empty slate, the retired wnba key, and "drops a 32-hex event id".

The digit check was restored. The same three files were re-run: **12 passed.**

## Follow-ups

- `EventDetail` starts the bookmaker form at `[]` and does not mount `BookmakerSelect`. A saved alias still cannot be chosen on that page today. The request rewrite covers any caller that passes one.
- `docs/progress.md` was not edited.
