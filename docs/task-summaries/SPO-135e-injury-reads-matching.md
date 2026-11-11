# SPO-135e — injury status on reads, safer matching, refill after restart

- Ticket: SPO-135e
- Branch: `feature/SPO-135d-injury-reads-matching` (the branch name stays; SPO-135d is the frontend ticket)
- Base: `dev`
- Stacks on PR #72, which stacks on PR #69. After those squash-merge, `git merge origin/dev` on this branch.

## Summary

NBA `/reads` loads Redis key `injuries:nba:latest` and matches posted names with `match_injury_entry`, the same helper daily picks use. Out, and a source word of Doubtful, set `combined_probability` to null. A missing or stale snapshot logs one warning and leaves the blend. The request path still only reads Redis.

Injury names keep Jr/Sr/II/III/IV. The fold is case, punctuation, and accents. `Gary Trent Jr.` does not match `Gary Trent`. Picks and reads have no `bdl_player_id`; the id still wins when a caller actually has one. An ambiguous full name stays null.

Startup refills a missing key once, including outside the slate window. It refills a stale or malformed key only inside the window. `misfire_grace_time` is 25 minutes with coalesce, so a missed :07 or :37 runs once and does not burst. A restart outside the window with a stale snapshot leaves `injury_status` null until 11:07 America/Chicago. A fill on the analysis run was not added, because that function is also the HTTP handler.

Doubtful blocking is unchanged.

## Why

SPO-135c put the snapshot on the daily board and left three holes. `/reads` never opened it, so the game page still blended an Out player. The name key dropped suffixes, so one "Gary Trent Jr." Out row blocked "Gary Trent". A stale key was not refilled at startup, and a 1-second misfire grace dropped a tick a restart had just missed.

## Changes

| Area | What changed |
|---|---|
| `/reads` | `get_event_reads` loads the snapshot. `match_injury_entry` sets the words passed to `build_nba_signals`. No BALLDONTLIE call |
| Names | `_injury_name_key` keeps the suffix. `player_name_key` is unchanged for other callers |
| Ids | Picks and reads pass no id. Odds outcomes and snapshot rows do not have one. The agent id path stays |
| Startup | Missing key still refreshes once, outside the window included. Stale or malformed refreshes only inside the window |
| Cron | `misfire_grace_time` 25 minutes, `coalesce` true, `max_instances` 1. 429 rule unchanged |
| Docs | This summary and `docs/decisions/SPO-135/decision_20261111_injury-reads-matching.md`. SPO-135c decision gets a one-line superseded note |

## Blast radius

NBA daily picks, NBA `/reads`, and the NBA agent tool share `match_injury_entry`. A query that used to match only because the suffix was stripped, such as "jaren jackson" against "Jaren Jackson Jr.", now misses. WNBA daily picks still ignore the snapshot. WNBA scrape matching of an exact name is unchanged. `player_name_key` still strips suffixes for game logs. Doubtful still blocks the blend and still leaves the filtered board, because the filter sees Questionable.

## Tests / Verification

Recorded fixtures only. No live BALLDONTLIE or Odds API call. Gary Trent and Luka Doncic rows in the new tests are recorded injury entries with only `player` changed. The injury page has neither name.

- `cd backend && python3 -m pytest tests -q --tb=line` → 1379 passed, 28 skipped, 6 xfailed, 0 failed.
- Redis on localhost. Snapshot seeded by `refresh_nba_injuries_from_bdl` with a mocked transport over the recorded `player_injuries` page and a terminal copy (190 entries). `GET /api/health` 200. `GET /api/nba/daily-picks?date=2026-11-10&tz_offset=480&min_probability=0.5&min_games=5` 200, 11 picks. Jimmy Butler `injury_status` `Out`, `combined_probability` null, `lineup_confirmed` null. Dyson Daniels `injury_status` null, `combined_probability` 0.743. `GET /api/nba/events/07361a8381206817e27bd2697fad7479/reads?market=player_points` 200, 15 reads. Jimmy Butler `combined_probability` null. Dyson Daniels `combined_probability` 0.743. Odds and the snapshot rows are the recorded `player_points` capture with one description relabeled to Jimmy Butler.

## Open question

Doubtful. The cache stores it as Questionable and keeps `raw_status`. `injury_blocks_combined` treats that source word like Out, so `combined_probability` is null, while `DailyPick.injury_status` stays Questionable. The filtered board then drops the row with the other null blends. Out stays on the board. This PR does not change that. Eason decides whether Doubtful should keep a probability the way Questionable does, or keep blocking the way Out does. If it keeps blocking, the filter has to see `raw_status` or the row will not stay on the board.

## Follow-ups

- [ ] Eason: Doubtful keeps a blend, or blocks and stays on the filtered board.
- [ ] A restart outside the slate window with a stale snapshot is blind until 11:07 America/Chicago.
- [ ] SPO-130d: a production team-id map. This PR still reads the recorded standings fixture.
