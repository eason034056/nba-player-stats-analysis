# Decision — Event reads, and tier from combined probability

- **Ticket:** SPO-121
- **Date:** 2026-11-10
- **Status:** Accepted

> Superseded in part by SPO-135 (2026-11-11): event reads do not look up `projections:nba:{date}`. The projection signal is missing. Defense ranks come from the game log.
> Superseded in part by SPO-135c (2026-11-11): event reads omit the projection signal. The slot returns when the ML model ships.

## Context

SPO-114 serves every posted player line for one NBA event from `odds_line_snapshots`. The game page still has no side, combined probability, tier, or signals for the players who are not on the daily-picks board.

SPO-111 labels `DailyPick.tier` from the chosen side's historical hit rate. That decision says the tier is not a function of `combined_probability` (`docs/decisions/spo-111-read-data/decision_20261110_read-tier-cutoffs.md`, "What this does not decide"). SPO-112 then added the calibrated blend and left `probability` as the headline. This ticket moves the NBA tier and the published board onto that blend. It does not change the blend's math.

## Decision 1 — a separate reads route

`GET /api/nba/events/{event_id}/reads` returns one `PropRead` for every posted player in the latest snapshot. Optional query `market` is one snapshot key. Omit it to score every stored market.

`BulkPropPlayer` does not gain a `read` field.

| Criterion | What this route does |
|---|---|
| Latency | Props stay a snapshot read. The 60s props cache does not wait on per-player history or signal math. Reads do that work on their own request. |
| Odds API credits | 0. Prices come from `odds_line_snapshots`. History comes from the NBA game log. A projection is used only when Redis already holds `projections:nba:{date}`. A miss does not call SportsData and does not call the Odds API. |
| Payload size | One market tab is one request. The props body stays lines and books. Signals are not attached to every market on every props response. |
| Caching | Independent. Props stay `60s` and still store lines without roster fields. Reads use `nba:event-reads:v2:{event_id}:m={market}` (or `m=*` when the query is omitted), also 60s. v1 is not read. A one-market request is not sliced out of the all-markets document. |
| Frontend | The game page is already one market at a time and joins players by name. It can request that market's reads and join them onto the props list. |

`side` follows the stored daily-pick rule first (0.65, then the Lean floor 0.56, over wins a tie), then the higher historical rate, then the no-vig favorite at the modal line when the log has no rate. Binary markets are present with `side`, `combined_probability`, `tier`, and `signals` all null. A player with no two-sided price and no log is present the same way.

`combined_probability` is `build_nba_signals`. This ticket does not change that function.

The two paths do not see the same prices. Daily analysis passes the full bookmaker array, and `american_pairs_at_line` keeps every pair posted at the modal line. `/reads` rebuilds books from `odds_line_snapshots`. That table stores one pair per book: the last Over and the last Under in the payload (`rows_from_bookmakers`). Feeding `/reads` the daily-analysis ladder would mean storing every rung. That is the open snapshot-writer issue, not a change to the blend. On the recorded player_points capture the lines, sides, and tiers match. The largest absolute gap in `combined_probability` is 0.0069 (Nickeil Alexander-Walker, 0.6730 on the daily pick and 0.6661 on the read). The test locks that gap at or below 0.01.

## Decision 2 — NBA tier and the board use combined probability

`READ_TIER_CUTOFFS` is unchanged:

| Tier | Rule |
|---|---|
| Strong play | >= 0.70 |
| Playable | >= 0.65 and < 0.70 |
| Lean | >= 0.56 and < 0.65 |
| null | < 0.56, missing, or not finite |

For NBA, the input is now `combined_probability`, not the historical `probability`. `DailyPick.tier` is `read_tier(combined_probability)`. `GET /api/nba/daily-picks` and the trigger's `high_prob_count` filter with `select_daily_picks(..., league="nba")`, which compares `combined_probability` to `min_probability` (default 0.65) and still requires `n_games` >= `min_games` (default 10). A missing or non-finite combined value does not fall back to the historical rate, so that row leaves the board.

This replaces the SPO-111 sentence that `tier` stays a function of the historical probability only. The cutoff table in that decision is still the table. WNBA is unchanged: `combined_probability` stays null, `select_daily_picks(..., league="wnba")` still filters on `probability`, and the WNBA tier is still `read_tier(probability)`.

Storage is unchanged. A candidate is still kept when a historical side clears 0.56 (and the default NBA sample floor of 5). A player below that historical floor is not stored, so a high combined value cannot put them on the board. `top_read` is still the highest historical probability. `GET /api/picks/today` still filters on the historical rate.

An NBA row is constructed with `tier` null. The signal step then sets `tier` from the blend. If `build_nba_signals` raises, the stored row keeps `combined_probability` null and `tier` null, so `board_score` drops it at every floor. WNBA still writes the historical tier at construction, because it does not run that step.

The stored list is ordered by `sort_stored_picks`. NBA uses `combined_probability`. WNBA uses the historical rate. A missing score sorts last. Equal scores keep analysis order. `best_top_reads` still selects the highest historical probability. On a tie it keeps the earlier row of this list, so an NBA tie keeps the higher blend. `high_prob_count` is the length of that blended board for NBA.

## Measured shift on one recorded capture

Same day's data: `tests/fixtures/odds_api_event_odds__player_points.json` (event `07361a8381206817e27bd2697fad7479`, tip `2026-11-10T00:10:00Z`) and the shipped `data/nba_player_game_logs.csv`. Projections are omitted, so the projection and defense adjustments are 0. The signal function is the production one. No Odds API call. Script: `scripts/measure_spo121_board_shift.py`. The default board is 0.65 and 10 games.

15 players were posted. 11 had a historical side at or above 0.56 and were stored.

| | Count |
|---|---|
| Old board (historical `probability` >= 0.65, n >= 10) | 4 |
| New board (`combined_probability` >= 0.65, n >= 10) | 6 |
| Entered | 3 |
| Left | 1 |
| Tier label changed (including to or from null) | 5 |

Entered (Lean on the historical rate, Playable on the blend):

| Player | Side | Historical | Combined |
|---|---|---|---|
| Dyson Daniels | over  | 0.6316 | 0.6862 |
| Nickeil Alexander-Walker | over | 0.5897 | 0.6730 |
| Ziaire Williams | over | 0.6071 | 0.6738 |

Left:

| Player | Side | Historical | Combined | Old tier | New tier |
|---|---|---|---|---|---|
| Matisse Thybulle | under | 0.7333 | 0.6386 | Strong play | Lean |

The fifth tier change stayed off both boards: Jalen Johnson over, historical 0.5972 (Lean) to combined 0.5361 (null). `6 = 4 - 1 + 3`.

This is one event and one market. It is not a full slate. Players under the historical 0.56 floor never enter this count.

## Also in this ticket

`season_mean` is the mean of the metric on the same season games as `season_n_games`. It ignores the line and the `n` window. An empty season is null. WNBA does not compute it; the response field is null.

`BulkPropPlayer.position` is still `Pos` on the newest NBA game log. `team_code` is `team_on_event` for the snapshot row's home club, away club, and slate date, then `canonical_team_code`. A log club that is not in the game is null. The fields are filled on the way out of the props response, including a cache hit. The cached lines do not store the roster fields, so a log correction is not frozen for 60 seconds. The cache document does keep the snapshot clubs so the hit uses the same event. A lookup miss is null and is not an error. The lookup runs on the event loop. Moving it off the loop waits until the slate is large enough to matter.
