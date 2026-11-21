# Decision — Read layer for the frontend and the player-props model

- **Ticket:** SPO-138i (provisional number; Paperclip was offline when this was written)
- **Date:** 2026-11-20
- **Status:** Accepted (Eason)

## Context

`002_bdl_core` stores each fact with the time we learned it. Two readers need different cuts of that history:

- The frontend wants the newest row: injuries, projected lineups, and model predictions.
- The player-props model wants what was known at a prediction time T, plus the result as a label.

Without one definition, every query re-derives "newest" and "settled" its own way. Daily picks live only in Redis (`daily_analysis.py:1077`), so nothing durable records what the product said before a game.

## Decision

1. **The 14 tables of 002 do not change.** `003_read_layer.sql` adds one table and four views.
2. **`predictions`** holds one row per model run for a game, player, and market (`model_version`, `predicted_value`, nullable `distribution`).
   - `predicted_at` is the insert's transaction time. A trigger overwrites whatever the writer sends.
   - An insert at or after `games.datetime_utc` is refused, and so is one for a game with no `datetime_utc`.
   - UPDATE and DELETE are refused.
   - No line, book, or price is stored; the model never reads prop odds.
   - `player_double_double` and `player_triple_double` store a probability (at most 1). `distribution` is a JSON object that only Python reads, per `model_version`.
3. **`prop_actuals`** gives one row per stat line and market, for final games only (`games.status_state = 'final'`).
   - The value follows `prop_markets`: `sum` adds the `stat_columns`; `double_digits` is 1 when enough of them reach 10.
   - It is NULL when the line is `dnp` (the prop is void) or when a needed stat is NULL (unknown, never guessed).
   - It is both the model's label and the source for grading. It reads no odds.
4. **`current_predictions`** keeps the newest run per game, player, market, and model version. **`current_injuries`** takes each player's newest row first and then keeps it only if `listed`; filtering first would bring back an older Out. **`current_projected_lineups`** shows the newest `updated_at` version per game and team, one row per starter.
5. **Model inputs** are built by a Python dataset module (SPO-138j), not in Postgres.
   - One training row is one `player_game_stats` row. The label comes from `prop_actuals`, with one target per market.
   - Each source is read only up to T: earlier games' stats; opening `game_odds_snapshots`, median across books; `projected_lineups` by `first_seen_at`; `injury_snapshots` by `snapshot_at`.
   - `player_prop_snapshots` is never a feature, and any source not listed is refused.
   - Two stand-ins are allowed in training: actual starters (`game_lineups`, 2025-26 on) and box-score absence (no row or `dnp`). An output column `info_source` is `standin` when a row used either, and `pregame` otherwise. Final model scores count only `pregame` rows.
6. **Teammate absence** is computed by one function, `team_absences(league, team, game, as_of, source)`, used for both training and live inputs.
   - A rotation player's latest game before the target was for the team, and he played at least 3 of its last 10 games, averaging at least 15 minutes.
   - With `source = actual`, an absent player has `p_out` 1. With `source = reported`, `p_out` comes from the latest listed injury row as of T. It starts at Out 1, Doubtful 0.75, Questionable 0.5, Day-To-Day 0.25, Probable 0.1, and is refit later from how often each status actually sat out.
   - Features: `team_missing_minutes`, `team_missing_share` (the absent players' share of the team's stat for the market), and `opp_missing_minutes`.
   - A player's own injury status exists only on `pregame` rows; it is NULL on stand-in rows.
7. **`injury_snapshots.status` stores BDL's word.** Spelling is unified (`DAY_TO_DAY` becomes `Day-To-Day`), but Doubtful stays Doubtful. An unknown word is stored as sent (trimmed), and a blank status is NULL. The Redis cache stops merging Doubtful into Questionable in SPO-135i, which supersedes SPO-135h. Product behavior does not change: Doubtful still gets the Questionable blend.

## Alternatives

- *Star schema or feature tables in Postgres.* Rejected. RDS is `db.t4g.micro`, rolling features are awkward in SQL, and the history is small enough (about 0.92 million stat rows) to export and build in Python.
- *Prop lines as model features.* Rejected. A model that sees the line learns to copy the market and never finds a disagreement to bet. Line history also starts only in 2024-25, while stats start in 2000-01.
- *A writer-supplied `predicted_at` with a "before tip-off" check.* Rejected. A backtest could write any earlier time. With the trigger removed, the 003 test for a post-tip insert passes only because the writer's old timestamp is accepted.
- *A foreign key from `predictions` to a prop snapshot.* Rejected. Live snapshots are downsampled after 14 days (§9 Q3 in `data-model.md`), so the key would break. Each prediction is a self-contained receipt.
- *A `current_props` view.* Not built. The frontend did not ask for line movement.

## Tradeoff

- The stand-ins make backtests optimistic. Training sees only `p_out` of 0 or 1, while live inputs see 0.5. The gap is measured once enough `pregame` rows exist.
- `predictions` cannot hold backtest output. Backtests write files instead.
- `prop_actuals` looks columns up by name. `test_every_stat_column_name_is_an_integer_column` guards against a seed row with a typo, which would otherwise turn a market into NULLs.
- `prop_actuals` builds one JSON object per stat line. A full scan pays for that, so readers filter by player, game, or season.
