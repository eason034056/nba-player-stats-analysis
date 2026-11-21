# Game-odds opener timing

**Status: PENDING.** The real history was not queried, so
[game-odds-opener-timing.sql](game-odds-opener-timing.sql) has no season
totals, NULL counts, boundary counts, or book counts from that database.
A scratch server can parse the SQL. Those rows are not this measurement.
Do not fill the blanks from the prop-opener probe or from the handoff estimate.

## What is not known

- Both probed **prop** openers had `opened_at` equal to tip-off minus 3 hours.
  That was two games. It is not a measurement of `game_odds_snapshots`.
- The storage note in `data-model.md` estimates about one vendor per game for
  2020-25 and about twelve for 2026 (measured 2026-11-10 on a sample). That
  estimate is not reused as a constant. Query 3 is the check.
- Opening coverage in the data model starts 2020-12-23. Query 4 is the game
  denominator. This note does not repeat that date as a measured row count.

## What the SQL does

`T` in the SQL is `games.datetime_utc - interval '3 hours'`.

- A NULL `snapshot_at` is counted, then excluded from the `<= T`, `> T`, and
  exact-boundary buckets. It is not imputed.
- A NULL `datetime_utc` is counted as `null_tip`. It is not given 00:00
  America/New_York. That midnight is the dataset cutoff in
  `backend/app/ml/asof.py` when the tip is missing. The dataset still uses it.
  This measurement does not, and it does not change the dataset rule.
- `rows_exact_boundary` is the subset of `rows_at_or_before_t` where
  `snapshot_at` equals T. The two counts overlap on purpose.
- `snapshot_minus_tip_hours` is `snapshot_at - datetime_utc` in hours.
- Query 2 is one row per game: opening rows, NULL timestamps, distinct books,
  and books at or before T. Query 3 rolls that book count up by season.

## What an opening row means

The opening unique key is `(league, bdl_game_id, book_key)`. `snapshot_at` is
not in that key. A retry can change the timestamp and the values. The row is
not an immutable first-observed history. A historical import shows that BDL
published a value at `opened_at`. It does not show that this application
polled that value at `opened_at`.
