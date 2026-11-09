# SPO-102 — Wire PlayerDDTile to /player-dd-history and the yes/no no-vig branch

## Summary

`PlayerDDTile` no longer documents double-double props as pending. It loads history from `GET /api/{nba|wnba}/player-dd-history` and Yes/No prices from `POST /api/{nba|wnba}/props/no-vig` with `market=player_double_double`. The tile reads the explicit binary fields only. A missing, null, or empty payload stays on an explicit unavailable state, including loading and error. NBA and WNBA both expose these routes, and the event page passes the matching client.

## Changes

| File | Change |
|---|---|
| `frontend/lib/schemas.ts` | `bookmakerResultSchema` accepts `yes_price`, `no_price`, `p_yes_imp`, `p_no_imp`, `yes_fair_prob`, `no_fair_prob` (nullable, optional). `consensusSchema` accepts `p_yes_fair`, `p_no_fair`. New `playerDDHistoryResponseSchema` / `PlayerDDHistoryRequest` match `PlayerDDHistoryResponse`. |
| `frontend/lib/api.ts` | `getPlayerDDHistory` → `GET /api/nba/player-dd-history`. `getWNBAPlayerDDHistory` → `GET /api/wnba/player-dd-history`. Query params are `player` and optional `season`. No `threshold`. |
| `frontend/lib/player-dd.ts` | Selects a book only when `yes_price` is a posted number. Ignores `over_*` / `under_*` and the `line` sentinel. History is shown only when `prob_dd` is present and `n_games` > 0. |
| `frontend/lib/use-player-dd.ts` | TanStack Query hook. League `wnba` calls the WNBA clients; `nba` calls the NBA clients; any other league does not fetch. Odds stale time is 30s. |
| `frontend/components/PlayerDDTile.tsx` | Fetches through the hook. Renders book Yes/No prices, implied and fair probabilities, consensus fair probability, historical `prob_dd`, and the edge against fair Yes. Empty, null, loading, and error states are explicit. |
| `frontend/components/PlayerHistoryStats.tsx` | Passes `eventId`, league from `cacheNamespace`, and the DD history client into the tile. The continuous `/player-history` query stays disabled for `dd`. The 0.5 line is not copied into the threshold box. |
| `frontend/components/EventDetail.tsx` | NBA config uses `getPlayerDDHistory`; WNBA config uses `getWNBAPlayerDDHistory`. |
| `frontend/components/PlayerDDTile.test.tsx` | Populated yes/no odds, null yes/no fields, empty history, history error, odds error, loading, missing event, WNBA route selection, unsupported league. |
| `frontend/components/PlayerHistoryStats.dd.test.tsx` | WNBA event page path calls the DD clients and does not call continuous history. |
| `frontend/lib/player-dd-schema.test.ts` | Zod parse of the SPO-26 history body, a null `prob_dd`, binary yes/no rows, and an Over/Under row that omits the new fields. |
| `frontend/test/test-utils.tsx` | Mounts `WnbaBetSlipProvider` beside the NBA slip, matching `app/providers.tsx`. Navbar and the pick menu call `useWnbaBetSlip`. |
| `frontend/package.json`, `frontend/vitest.config.mts` | Pin the test clock to `America/Chicago` so existing local-date assertions hold on a UTC runner. |
| `docs/task-summaries/SPO-102-screenshots/` | Populated and empty tile screenshots from the dev server against a mocked API. |
| `docs/progress.md` | SPO-102 entry. |

## Why

SPO-26 already returns the binary shape. The tile was still hard-coded to null and told the user the endpoint did not exist. Wiring it means the event page can show a real historical rate next to posted Yes/No prices.

The route also fills legacy `over_*` / `under_*` fields (`over` = Yes, `under` = No, `line` = 0.5). On a single-leg quote, `under_odds` is a copy of the Yes price so the non-null legacy schema still validates, while `no_price` stays null. Reading `over_odds` when `yes_price` is null would display a number the binary contract did not publish. The tile therefore uses only `yes_*` / `no_*` and `consensus.p_yes_fair` / `p_no_fair`. It does not average American prices, does not compute `1 - p_yes` on the client, and does not turn `dd_games / n_games` into a rate when `prob_dd` is null.

Both `backend/app/api/nba.py` and `backend/app/api/wnba.py` register `/player-dd-history` and dispatch `player_double_double` through `_build_binary_no_vig_response`. The WNBA event page passes `getWNBAPlayerDDHistory` and `calculateWNBANoVig`. An unrecognized league renders the unavailable state and does not call either API.

The edge bar compares historical `prob_dd` to fair Yes probability (consensus when the route sent `p_yes_fair`, otherwise the single book's `yes_fair_prob`). Implied probability stays labeled vig-laden and is not used as the edge reference.

## Tests / Verification

- Frontend: `npm test` — 18 files, 55 tests, passed. The script sets `TZ=America/Chicago`.
- `npx tsc --noEmit` — passed.
- `npm run lint` — passed.
- Integration test: SKIPPED (no new external API client; the tile calls the existing backend routes).
- Manual: dev server with a mocked `/player-dd-history` and `/props/no-vig`. Populated tile shows Jokic 80.0%, DraftKings -250 / +200, FanDuel No price unavailable, consensus 68.0% / 32.0%, edge +12.0 pts. Empty tile shows the history message and the empty-odds message, with no 0.0% and no odds numbers.

Screenshots:

![Populated double-double tile](SPO-102-screenshots/populated.png)

![Empty double-double tile](SPO-102-screenshots/empty.png)

## Follow-ups

- `NoVigResponse` also returns `fetched_at`, `data_age_seconds`, `cache_state`, and `source`. The shared Zod schema still strips them, so the tile cannot show line age. Add those fields to `noVigResponseSchema` if the event page should warn on a stale snapshot.
- Single-leg rows keep `no_price` and `p_no_imp` null, but `under_odds` is copied from the Yes price and `p_under_imp` is the complement. `BookmakerResult.under_odds` is a required float, which is why the route does this. A later schema change could make the legacy No leg optional for binary markets so other clients cannot mistake that copy for a posted No price.
- When the vig prior cannot be applied, the route omits the row and explains it in `message` instead of returning `yes_fair_prob: null`. The tile shows that message. No frontend change is required unless Backend starts emitting the row with null fair fields; the null path is already an unavailable state.
- `/wnba/player/[name]` is still the continuous-metric page. It does not mount `PlayerDDTile` because that page has no event id for live odds. History-only DD on that page is a separate slice.
- There is no season control on the tile. The client omits `season`, which the route treats as all seasons.

## Backend fields used

History (`PlayerDDHistoryResponse`): `player`, `season`, `n_games`, `dd_games`, `prob_dd`, `message`.

No-vig request: `event_id`, `player_name`, `market` = `player_double_double`, `regions` = `us`, `bookmakers` = null, `odds_format` = `american`.

No-vig response: `results[].bookmaker`, `results[].yes_price`, `results[].no_price`, `results[].p_yes_imp`, `results[].p_no_imp`, `results[].yes_fair_prob`, `results[].no_fair_prob`, `consensus.p_yes_fair`, `consensus.p_no_fair`, `message`. `results` length distinguishes an empty board from a row whose Yes fields are null.

Not displayed: `line` (0.5 sentinel), `over_odds`, `under_odds`, `p_over_imp`, `p_under_imp`, `p_over_fair`, `p_under_fair`, `vig`.
