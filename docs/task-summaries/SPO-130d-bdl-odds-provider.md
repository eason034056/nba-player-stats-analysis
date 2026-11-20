# SPO-130d — BALLDONTLIE odds provider (not wired)

- Ticket: SPO-130d
- Branch: `feature/SPO-130d-bdl-odds-provider` (from `feature/SPO-130c-odds-provider-registry` `69670d9`, PR #92)

## Summary

`BdlOddsProvider` implements the odds-provider protocol for NBA. It uses the existing `BdlClient`, a props adapter, and a player directory. `nba_odds_provider` now accepts `balldontlie`. The default stays `theoddsapi`, and no route or job imports the new modules, so NBA and WNBA still read The Odds API.

BetParx and Bally Bet are one book. On points, when that pair posts more than one total for a player, every total below the highest is removed before the main-line vote. That drops OKC at Portland's Bally Bet line and keeps BetParx's real total. Milestone rows other than double-double are dropped, so Betway never votes. Double-double is Yes only. A row whose `updated_at` is after the game's `datetime` is dropped. The Clippers code is `LAC`. An id missing from the alias file uses the BALLDONTLIE first and last name and logs one counted line.

## Changes

| Area | File | Change |
|---|---|---|
| Adapter | `backend/app/services/bdl_props_adapter.py` | `BdlPropsAdapter.to_bookmakers` emits the Odds API bookmaker list. Allow-list, paired-book dedupe, fake low points, milestone and quarter drops, post-tip drop. `bally_bet` maps to `ballybet`. |
| Directory | `backend/app/services/bdl_player_directory.py` | `BdlPlayerDirectory.names_for`. Redis `bdl:player:v1:{id}` for 24 hours, then the alias file, then `GET /v1/players?player_ids[]=`. |
| Aliases | `backend/app/services/bdl_player_aliases.json` | Empty object. An id with no entry uses the BALLDONTLIE name. |
| Provider | `backend/app/services/bdl_odds_provider.py` | `BdlOddsProvider`. `list_events` is one `dates[]` call, then a UTC window filter. `slate_date` is the game's Eastern `date`. `games_match` joins on that date plus team codes, not commence time. |
| Registry | `backend/app/services/odds_gateway.py` | NBA accepts `balldontlie` and returns `BdlOddsProvider`. The import is inside the lookup. Default and WNBA stay `TheOddsAPIProvider`. |
| Setting | `backend/app/settings.py` | Comment only. Default remains `theoddsapi`. |
| Recorder | `scripts/record_bdl_odds_fixtures.py` | Writes the missing captures from live responses. Strips `apiKey` and `Authorization`. Saves a 429 only when one happens. `--bdl-only` records the BALLDONTLIE files and needs only `BALLDONTLIE_API_KEY`. |
| Tests | `backend/tests/test_spo130d_bdl_odds_provider.py` | Adapter, directory, provider, registry, the four copied captures, and the same-slate parity check (skipped until the pair exists). |
| Fixtures | `backend/tests/fixtures/bdl/` | Copied byte-for-byte: OKC at Portland post-tip props, Orlando at Sacramento in progress, Milwaukee at New York final, and the `player_ids[]` page. Recorded 2026-11-10/11 from `/v2/odds/player_props` and `/v1/players`. |
| Fixtures note | `backend/tests/fixtures/README.md` | Provenance for the four copied files, and the captures that are still not in the tree. |
| Docs | `docs/task-summaries/SPO-130d-bdl-odds-provider.md` | This file. |

## Why

The later NBA tickets need a provider that already speaks the bookmaker shape `rows_from_bookmakers` and `_main_line_vote` read. Building that shape here, while the registry still defaults to The Odds API, keeps the cutover as a setting flip instead of a parser rewrite.

BetParx and Bally Bet post the same prices. Counting them as two books would let the low points total vote. The snapshot writer stores every two-sided rung, so the low total has to be removed in the adapter, not only ignored by the vote. The rule is: when the pair has two or more points totals for one player, keep the highest. On the recorded OKC at Portland board that highest total is the one the other books post, and the lower total is the one Bally Bet posts alone. A player with a single total is unchanged. No book is added that did not post a surviving row.

Games are not matched on commence time. Boston at Philadelphia is `2026-11-11T01:10:00Z` on The Odds API and `2026-11-11T01:00:00.000Z` on BALLDONTLIE. Both are `2026-11-10` in New York, and the team codes are BOS and PHI. `ProviderEvent.slate_date` is the BALLDONTLIE `date` field. `home_team` for the Clippers is `Los Angeles Clippers` so `canonical_team_code` returns `LAC`. The recorded abbreviation is already `LAC`.

`get_event_odds_with_usage` returns no Odds API quota. BALLDONTLIE's remaining count stays on `rate_status`, so it is not written into `odds:quota_usage:v1`.

## Tests

```
cd backend && REDIS_URL=redis://localhost:6379 DATABASE_URL=postgresql://novig:novig@localhost:5432/novig_nba pytest --tb=line -q
```

`1640 passed, 30 skipped, 7 xfailed` on this machine, where `REQUIRE_DOCKER_TESTS` is unset and the real-docker verify skips. `d4b08e6` CI was `1639 passed, 31 skipped` with that docker test running. This commit turns the empty-players and empty-props skips into passes. Redis and Postgres were local, same URLs as CI.

The copied captures are in the tree. Every row in the OKC at Portland post-tip file, the Orlando at Sacramento in-progress file, and the Milwaukee at New York final file has `updated_at` after that game's `datetime`, so the adapter drops them all. `players_ids_v2.json` resolves Shai Gilgeous-Alexander, Pascal Siakam, and Andrew Nembhard.

`players_empty.json` and `props_empty.json` were recorded live on 2026-11-13 at about 04:30Z with `--bdl-only`. The props file is game `21718193`. Both `data` arrays are empty, and the adapter emits no books. A 429 was not returned, so that test still skips.

Skips that remain for this ticket:

- `player_props_429.json` (only if a live 429 happens)
- `tests/fixtures/same_slate/` parity pair, until `ODDS_API_KEY` is available

Post-tip removal is also tested on the pregame file: every recorded `updated_at` is before the game `datetime`, and a cutoff taken from the latest recorded stamp drops the rows after it. The same-slate test reports the agreement rate and fails only below 90%. It stays skipped until `ODDS_API_KEY` is available.

Integration test: SKIPPED. `BALLDONTLIE_API_KEY` and `ODDS_API_KEY` are not set here, so the recorder was not run. Fabrication scan: PASS. Tests load `tests/fixtures/bdl/` and the recorded Boston at Philadelphia odds file. The unknown-vendor case copies one recorded row and changes `vendor` to `bovada`. No response body was typed by hand.

WNBA tests stayed green. `api/`, `scheduler.py`, `daily_analysis.py`, `odds_snapshot_service.py`, and `nba_injuries.py` do not mention the new modules.

## Follow-ups

- Run `scripts/record_bdl_odds_fixtures.py` without `--bdl-only` once `ODDS_API_KEY` is available. That records the same-slate pair. A 429 file is still written only if a live 429 happens.
- SPO-130f is the ticket that serves NBA routes from this provider when the setting is `balldontlie`.
- The alias file is empty. A spelling that should differ from `first_name` + `last_name` (the plan's example is Alex Sarr) gets an entry there. Until then every resolved id logs `bdl_player_unaliased` once per process.
