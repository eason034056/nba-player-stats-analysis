# SPO-126 — OddsProvider abstract method and LA Clippers team code

- Ticket: SPO-126
- Branch: `feature/SPO-126-provider-abc-lac` (from `origin/dev` at `4bfb2ec`)
- Base: `dev`

## Summary

`get_event_odds` was indented inside the `QuotaUsage` dataclass, so `OddsProvider` only required `get_events`. The method is back on `OddsProvider`. `QuotaUsage` is a frozen dataclass of `remaining`, `used`, and `last` again, with the `total` and `remaining_ratio` properties and no abstract members. The only concrete provider, `TheOddsAPIProvider`, already implements `get_event_odds`.

`canonical_team_code` strips spaces and punctuation, then looks the token up. `Los Angeles Clippers` was already `LAC`. `LA Clippers` and `L.A. Clippers` became `LACLIPPERS`, which was not in the table, so the function returned that token. ESPN records the club as `LA Clippers` (event `401910304`, Boston Celtics at LA Clippers). `team_on_event` compares codes, so a CSV club of `Clippers` (`LAC`) did not match that side and the label was blank. `LACLIPPERS` now maps to `LAC`. `LA Lakers` and `L.A. Lakers` (`LALAKERS`) map to `LAL` the same way. WNBA still uses the WNBA table.

## Changes

| Area | File | Change |
|---|---|---|
| Provider | `backend/app/services/odds_provider.py` | `get_event_odds` is an abstract method of `OddsProvider`, next to `get_events`. `QuotaUsage` no longer carries it. |
| Team codes | `backend/app/services/daily_analysis.py` | `LACLIPPERS` → `LAC`. `LALAKERS` → `LAL`. Existing Clippers and Lakers spellings are unchanged. |
| Tests | `backend/tests/test_spo126_provider_and_clippers.py` | Provider contract, quota dataclass, both LA spellings, WNBA codes, and `team_on_event` on the recorded Clippers game. |
| Docs | `docs/task-summaries/SPO-126-provider-abc-lac.md` | This summary. |

## Why

`QuotaUsage` is the header triple from The Odds API (`x-requests-remaining`, `x-requests-used`, `x-requests-last`). It is constructed in the gateway and in `TheOddsAPIProvider._build_quota_usage`. An abstract HTTP method does not belong on that value. Leaving it there meant a new provider could be instantiated without `get_event_odds`, and the dataclass looked like it fetched odds.

The alias table already had the long city form (`LOSANGELESCLIPPERS`, `LOSANGELESLAKERS`) and the nicknames. The short city form is a different token after the same normalizer, so it needed its own key. A prefix strip of leading `LA` would also rewrite `LA Sparks` on the NBA path. The Sparks are not an NBA alias: `canonical_team_code("LA Sparks")` stays `LASPARKS`, and `league="wnba"` still returns `LAS`.

`team_on_event` does not have its own name table. It calls `canonical_team_code` for the home club, the away club, the projection candidate, and the log club. Once `LA Clippers` is `LAC`, Kawhi Leonard's shipped rows (latest club `Clippers`, 2026-04-15) stay `Clippers` on event `401910304`. A Bulls log (Anfernee Simons) on that same game stays blank. `LAC` as a candidate is kept because it is a side of the game.

## Tests

- `cd backend && python3 -m pytest --tb=line -q` → **1215 passed, 26 skipped, 6 xfailed, 0 failed** (14.66s).
- New cases: `OddsProvider` is abstract and names `get_event_odds`; a subclass that only implements `get_events` cannot be constructed; `QuotaUsage` has fields `remaining`, `used`, `last` and no abstract members; every `app.*` subclass that is still abstract for `get_event_odds` is reported (none); Clippers spellings including `LA Clippers` and `L.A. Clippers` map to `LAC`; Lakers spellings including `LA Lakers` and `L.A. Lakers` map to `LAL`; WNBA Lynx, Wings, and Sparks are unchanged; `team_on_event` keeps `Clippers` for Kawhi Leonard on recorded event `401910304` and keeps `Lakers` for LeBron James when the side is `LA Lakers`.
- No live Odds API, SportsData, RotoWire, or RotoGrinders call. The Clippers game is the recorded ESPN team schedule. The logs are the shipped NBA CSV.
- WNBA code paths were not edited. The new test asserts the existing WNBA results.

## Follow-ups

- None for this ticket. A new odds provider still has to implement `get_event_odds`; the suite names any `app.*` subclass that does not.
