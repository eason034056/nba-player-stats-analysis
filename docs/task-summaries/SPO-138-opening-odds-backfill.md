# SPO-138 opening odds and opening props backfill

## Sketch (before the code)

Unique keys today (migration `002_bdl_core`):

- `game_odds_snapshots` opening: `(league, bdl_game_id, book_key)` where `snapshot_kind = 'opening'`.
- `player_prop_snapshots` opening: `(league, bdl_game_id, bdl_player_id, book_key, market)` where `snapshot_kind = 'opening'`.
- Live and closing rows use a different key that includes `snapshot_at`. This backfill does not write those rows.
- `snapshot_at` on an opening row is BDL `opened_at`. It is not part of the key. `source_updated_at` stays null because an opening row has no `updated_at`.
- `bdl_backfill_checkpoints.data_type` already allows `opening_odds` and `opening_props`.

Types and signatures:

- `BdlClient.list_opening_odds(*, dates, per_page=100, cursor=None) -> dict`
  Recorded path `GET /nba/v2/odds/opening` with repeated `dates[]`, `per_page`, and `cursor` on a later page.
  No recorded opening request sends `game_ids`, so the method does not send that parameter.
- `BdlClient.get_opening_props(*, game_id) -> dict`
  Recorded path `GET /nba/v2/odds/player_props/opening?game_id=`. One response, no `per_page`, no `cursor`.
- Shard: odds `shard_key` is the game date `YYYY-MM-DD`. Props `shard_key` is the `bdl_game_id` text.
  Both live in `bdl_backfill_checkpoints`. A shard with pages stored and a null cursor is not fetched again.
  The current season's checkpoints are deleted at the start of each run, same as games and stats.
- `prepare_game_odds(rows, *, league, game_ids, book_keys) -> (rows, skips)`
  Skips a book that is not in `books`. Skips a game that has no `games` row. One tuple per `(game, book)`.
- `prepare_prop_rows(rows, *, league, game_ids, player_ids, book_keys) -> (rows, skips)`
  Reuses `BdlPropsAdapter` and `_live_prop_args` / `_main_line_vote`. `snapshot_at` is that group's `opened_at`.
  `game_datetime` is not passed: opening rows have `opened_at`, not `updated_at`, and a post-tip `opened_at` is stored and warned, not dropped.
- `write_opening_odds_page` / `write_opening_props_page`
  `INSERT ... ON CONFLICT ... DO NOTHING` on the opening unique keys. The checkpoint moves in the same transaction.
- `run_opening(...)` walks one season, then `season_opening_report` prints rows written, skips by reason,
  the percent of final games with odds, the percent of non-DNP player-games with props, and the
  `snapshot_at` buckets `NULL`, `< T`, `= T`, `T..tip`, `= tip`, `> tip` where `T = tip - 3h`.
- CLI: `python -m app.backfill [SEASON...] --data games_stats|opening_odds|opening_props`.
  Defaults when the season list is empty: odds `2020` through `2025`, props `2024` through `2025`.
  `2026` is not in those defaults. Pass `2026` to walk it.
  Odds work list also requires `date >= 2020-12-01`. Props work list also requires `season >= 2024`.
  Both require `status_state = 'final'` and a stored season type.
- The live writer still accepts only `live` and `closing`. Opening uses its own SQL because the conflict
  target and the timestamp are different. Widening `_write_bdl_live` would point opening rows at the tick index.

## Flags and defaults

| Command | Seasons when none are passed | Extra work-list filter |
|---|---|---|
| `--data games_stats` (default) | required; the command errors if you pass none | unchanged |
| `--data opening_odds` | 2020 through 2025 (2020-21 through 2025-26) | final games, stored season type, `date >= 2020-12-01` |
| `--data opening_props` | 2024 through 2025 (2024-25 through 2025-26) | final games, stored season type, `season >= 2024` |

`2026` is off by default and is reached by passing `2026`. A season later than the current one is rejected. The current season (July 1 turnover) is walked from the start every run and is never marked done. `--restart-season` deletes only that data type's checkpoints for that season. Games and stats checkpoints are not deleted. `--dry-run` for opening reads `games` (so it needs the DSN) and writes no snapshot and no checkpoint. Games/stats `--dry-run` still needs no DSN. Rate limit stays 500 calls/min. A 429 waits for `Retry-After` when that header is a positive delay, then for `x-ratelimit-reset`, and never longer than 65 seconds.

`list_opening_odds` does not send `game_ids`. No recorded opening request uses it. There is no `--concurrency` flag. One walker matches the games/stats backfill. A later change can add a pool.

`blocks` and `triple_double` are in `prop_markets`, and the live adapter does not map them. This backfill does not map them either. They are counted as `unknown_prop_type`, with `1q` and `first3min`. Polymarket and Kalshi are not seeded. A vendor missing from `books` is skipped before the insert. An unexpected foreign key still raises.

Opening rows are not written by `_write_bdl_live`. That function accepts only `live` and `closing`, and its `snapshot_at` is the job time. The opening conflict target is different, and each row's `snapshot_at` is its own `opened_at`. The adapter's post-tip drop looks at `updated_at`. Opening rows do not have `updated_at`, so the call does not pass `game_datetime`. A row with `opened_at` after tip is stored. The report prints `warning: snapshot_at after tip`.

`INSERT ... ON CONFLICT ... DO NOTHING` keeps the first stored line. The printed `written` count is this run's insert diff, not the rows already in the table.

## Runbook

Postgres here is 16.15 from the distro packages, cluster `spo138`, port `5441`. Docker was not installed. Role, password, and database for the suite are `test`. Do not point tests at `127.0.0.1:5434`.

Throwaway smoke (no live BDL key on this machine; the smoke used the recorded bodies through a fake transport):

```bash
DATABASE_URL=postgresql://test:test@127.0.0.1:5441/test python -m app.migrations upgrade
# then, with the DSN in an env var and BALLDONTLIE_API_KEY set:
python -m app.backfill 2024 2025 --data opening_odds  --dsn-env NBA_HISTORY_DATABASE_URL --dry-run
python -m app.backfill 2024 2025 --data opening_odds  --dsn-env NBA_HISTORY_DATABASE_URL
python -m app.backfill 2024 2025 --data opening_props --dsn-env NBA_HISTORY_DATABASE_URL
```

The dates in the recorded odds bodies with no `next_cursor` are 2024-11-20, 2025-11-20, and 2026-01-15. `odds_opening_2026-03-10.json` has `meta.next_cursor` 77717648. This run does not invent page 2. The test that covers that cursor returns HTTP 400 for the second request and checks that a resume asks only for that cursor.

Eason's local `nba_history` (Mac, school VPN on, append-only). Do not paste the DSN into chat.

```bash
cd backend
export NBA_HISTORY_DATABASE_URL='<local nba_history DSN>'
DATABASE_URL="$NBA_HISTORY_DATABASE_URL" .venv/bin/python -m app.migrations upgrade
pg_dump -Fc -t game_odds_snapshots -t player_prop_snapshots -t bdl_backfill_checkpoints "$NBA_HISTORY_DATABASE_URL" > ~/nba_history_pre_odds.dump
.venv/bin/python -m app.backfill 2020-2025 --data opening_odds  --dsn-env NBA_HISTORY_DATABASE_URL --dry-run
.venv/bin/python -m app.backfill 2024-2025 --data opening_props --dsn-env NBA_HISTORY_DATABASE_URL --dry-run
.venv/bin/python -m app.backfill 2020-2025 --data opening_odds  --dsn-env NBA_HISTORY_DATABASE_URL
.venv/bin/python -m app.backfill 2024-2025 --data opening_props --dsn-env NBA_HISTORY_DATABASE_URL
.venv/bin/python -m app.backfill 2026 --data opening_odds  --dsn-env NBA_HISTORY_DATABASE_URL
.venv/bin/python -m app.backfill 2026 --data opening_props --dsn-env NBA_HISTORY_DATABASE_URL
```

Prod RDS only after the wipe gate, with the backend stopped, using the same commands and the RDS DSN env. This change does not wipe anything and does not call RDS.

### Verification SQL

```sql
-- 1. Opening game odds per season, % final games covered
SELECT g.season,
       count(o.*) AS rows,
       count(DISTINCT o.bdl_game_id) AS games_with_odds,
       count(DISTINCT g.bdl_game_id) AS final_games,
       round(100.0 * count(DISTINCT o.bdl_game_id) / nullif(count(DISTINCT g.bdl_game_id),0), 1) AS pct
FROM games g
LEFT JOIN game_odds_snapshots o
  ON o.league = g.league AND o.bdl_game_id = g.bdl_game_id AND o.snapshot_kind = 'opening'
WHERE g.league = 'nba' AND g.season BETWEEN 2020 AND 2026 AND g.status_state = 'final'
GROUP BY g.season ORDER BY g.season;

-- 2. Opening props per season, % non-DNP player-games with any prop
SELECT s.season,
       count(*) AS player_games,
       count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM player_prop_snapshots p
           WHERE p.league = s.league AND p.bdl_game_id = s.bdl_game_id
             AND p.bdl_player_id = s.bdl_player_id AND p.snapshot_kind = 'opening')) AS with_props,
       round(100.0 * count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM player_prop_snapshots p
           WHERE p.league = s.league AND p.bdl_game_id = s.bdl_game_id
             AND p.bdl_player_id = s.bdl_player_id AND p.snapshot_kind = 'opening')) / count(*), 1) AS pct
FROM player_game_stats s
WHERE s.league = 'nba' AND s.season BETWEEN 2024 AND 2026 AND NOT s.dnp
GROUP BY s.season ORDER BY s.season;

-- 3. snapshot_at vs T (= tip - 3h) and vs tip, both tables
SELECT 'game_odds' AS tbl, g.season,
       count(*) FILTER (WHERE o.snapshot_at IS NULL)                                   AS null_ts,
       count(*) FILTER (WHERE o.snapshot_at <  g.datetime_utc - interval '3 hours')    AS before_t,
       count(*) FILTER (WHERE o.snapshot_at =  g.datetime_utc - interval '3 hours')    AS at_t,
       count(*) FILTER (WHERE o.snapshot_at >  g.datetime_utc - interval '3 hours'
                          AND o.snapshot_at <  g.datetime_utc)                         AS t_to_tip,
       count(*) FILTER (WHERE o.snapshot_at =  g.datetime_utc)                         AS at_tip,
       count(*) FILTER (WHERE o.snapshot_at >  g.datetime_utc)                         AS after_tip
FROM game_odds_snapshots o JOIN games g USING (league, bdl_game_id)
WHERE o.league = 'nba' AND o.snapshot_kind = 'opening' GROUP BY g.season
UNION ALL
SELECT 'props', g.season,
       count(*) FILTER (WHERE p.snapshot_at IS NULL),
       count(*) FILTER (WHERE p.snapshot_at <  g.datetime_utc - interval '3 hours'),
       count(*) FILTER (WHERE p.snapshot_at =  g.datetime_utc - interval '3 hours'),
       count(*) FILTER (WHERE p.snapshot_at >  g.datetime_utc - interval '3 hours'
                          AND p.snapshot_at <  g.datetime_utc),
       count(*) FILTER (WHERE p.snapshot_at =  g.datetime_utc),
       count(*) FILTER (WHERE p.snapshot_at >  g.datetime_utc)
FROM player_prop_snapshots p JOIN games g USING (league, bdl_game_id)
WHERE p.league = 'nba' AND p.snapshot_kind = 'opening' GROUP BY g.season
ORDER BY 1, 2;

-- 4. The PENDING 138k measurement
\i docs/decisions/SPO-138/game-odds-opener-timing.sql

-- 5. Checkpoints and integrity
SELECT data_type, season, status, count(*), sum(rows_written), sum(rows_dropped), sum(rows_rejected)
FROM bdl_backfill_checkpoints WHERE league = 'nba' AND data_type IN ('opening_odds','opening_props')
GROUP BY 1,2,3 ORDER BY 1,2,3;
SELECT count(*) FROM bdl_integrity_problems;
```

The plan's sample expectation (odds through 2024 all `= tip`, props all `= T`, `after_tip` 0) matches the 2024-11-20 capture. It does not match every later capture. On 2026-01-15 the nine DraftKings rows have `opened_at` `2026-01-15T05:00:00Z`, which is `< T`. BetMGM on that date is `= tip`. Those rows are stored as BDL sent them. A tip-stamped opener is after `T`, so the 138k read `snapshot_at <= T` does not take it. A prop stamped exactly at `T` is eligible. That split is left as the open policy question in the plan. This writer does not move timestamps.

## Throwaway CLI report

Recorded bodies, fake transport, Postgres 16 on `127.0.0.1:5441`, database `spo138_cli`. Games without a captured props file were answered with the recorded empty body `props_opening_858287_2023-03-01.json`. The second run of each command sent no HTTP requests.

```text
2024-25 opening_odds done | written 8 | skipped unknown_book 0, unknown_prop_type 0, missing_game 0, missing_player 0 | final games with odds 100.0% (8/8) | non-DNP player-games with props n/a (0/0) | odds buckets NULL 0, < T 0, = T 0, T..tip 0, = tip 8, > tip 0 | props buckets NULL 0, < T 0, = T 0, T..tip 0, = tip 0, > tip 0
2025-26 opening_odds done | written 22 | skipped unknown_book 0, unknown_prop_type 0, missing_game 0, missing_player 0 | final games with odds 100.0% (13/13) | non-DNP player-games with props n/a (0/0) | odds buckets NULL 0, < T 9, = T 0, T..tip 0, = tip 13, > tip 0 | props buckets NULL 0, < T 0, = T 0, T..tip 0, = tip 0, > tip 0
2024-25 opening_odds done | written 0 | ... | odds buckets NULL 0, < T 0, = T 0, T..tip 0, = tip 8, > tip 0
2025-26 opening_odds done | written 0 | ... | odds buckets NULL 0, < T 9, = T 0, T..tip 0, = tip 13, > tip 0
2024-25 opening_props done | written 158 | skipped unknown_book 0, unknown_prop_type 13, missing_game 0, missing_player 0 | ... | props buckets NULL 0, < T 0, = T 158, T..tip 0, = tip 0, > tip 0
2025-26 opening_props done | written 472 | skipped unknown_book 0, unknown_prop_type 17, missing_game 0, missing_player 0 | ... | props buckets NULL 0, < T 0, = T 472, T..tip 0, = tip 0, > tip 0
2024-25 opening_props done | written 0
2025-26 opening_props done | written 0
2025-26 opening_props done | written 431 | skipped unknown_book 0, unknown_prop_type 196, missing_game 0, missing_player 0 | final games with odds 92.9% (13/14) | props buckets NULL 0, < T 425, = T 472, T..tip 6, = tip 0, > tip 0
2025-26 opening_props done | written 0 | props buckets NULL 0, < T 425, = T 472, T..tip 6, = tip 0, > tip 0
```

The last pair is game `18447754` (2026-03-10) added after the first props walk. 196 rows were `unknown_prop_type` (`1q`, `first3min`, `blocks`, `triple_double`). Six stored lines sit strictly between `T` and tip. None are after tip. Game `15907655`: odds `opened_at` equals tip `2024-11-21T00:30:00.000Z` (`= tip`); every props row is `2024-11-20T21:30:00.000Z` (`= T`).

## Tests

`DATABASE_URL=postgresql://test:test@127.0.0.1:5441/test python -m pytest` from `backend/`:

**2071 passed, 17 skipped, 4 xfailed, 0 failed.**

`tests/test_spo138_opening_backfill.py` alone: 17 passed. Collection failed before `app.backfill.opening` existed (`ModuleNotFoundError`).

## Blast radius

- Diff is `backend/app/backfill/__init__.py`, `cli.py`, new `opening.py`, `bdl_client.py` (two methods plus Retry-After on the default 429 wait), the new test, the 11 recorded fixtures, and this file.
- Games/stats SQL, the games/stats walker, and `_RESET_SEASON` (still `data_type IN ('games','stats')`) are unchanged. `test_opening_run_leaves_games_checkpoints_alone` and `test_games_dry_run_still_needs_no_database` passed.
- `_write_bdl_live` and `app/services/odds_snapshot_service.py` are unchanged. `app/ml/` is unchanged, including the 138k read `snapshot_at <= T`.
- No migration file changed. The migration runner is unchanged.
- `app/services/scheduler.py` does not import `app.backfill` and does not name `opening_odds` or `opening_props`. `test_scheduler_does_not_call_the_backfill` passed.
- The full suite's 0 failures include `tests/test_spo132b_optional_vpc.py`. Nothing in that file was edited.

## Mutation checks

Both edits were restored. The same two tests then passed.

1. Removed `ON CONFLICT ... DO NOTHING` from the opening odds insert, leaving a plain `INSERT`. `test_recorded_odds_load_and_a_rerun_writes_nothing` failed with `UniqueViolationError` on `game_odds_snapshots_opening_key`. The test calls `write_opening_odds_page` a second time, so a done checkpoint cannot hide this.
2. Removed the odds `vendor not in book_keys` skip. `test_polymarket_and_kalshi_are_skipped` failed with `ForeignKeyViolationError` on `game_odds_snapshots_league_book_key_fkey`. The foreign key is not caught.

## What this run did not do

No live BDL call. No database wipe. No prod or RDS connection. No lineups backfill. No 138k or ML change. The scheduler does not call the new modes.
