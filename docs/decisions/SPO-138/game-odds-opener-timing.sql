-- SPO-138k game-odds opener timing.
-- Status: PENDING. This file was not executed. There is no DSN and no credential.
--
-- Question: for snapshot_kind = 'opening', where does snapshot_at sit relative
-- to tip, by season? The handoff estimate (about one book per game in
-- 2020-25, about twelve from 2026) is not a result. These queries measure it.
-- Do not copy a book count from the estimate into the feature code.
--
-- T in THIS file is games.datetime_utc - interval '3 hours'.
-- A NULL snapshot_at is counted, then left out of the <= T, > T, and
-- exact-boundary counts. It is not filled in.
-- A NULL datetime_utc has no tip, so it has no T here. Those rows are
-- counted separately. They are not given 00:00 America/New_York.
-- The dataset cutoff is app.ml.asof.prediction_instant, including that
-- midnight fallback. This file does not change that rule and does not
-- apply the fallback.
--
-- rows_exact_boundary is a subset of rows_at_or_before_t. Do not add them.
-- snapshot_minus_tip_hours is snapshot_at - datetime_utc, in hours.
-- Negative means the opener is before tip.

-- 1. Season totals, NULL timestamps, the T buckets, and the lag.
WITH opening AS (
    SELECT
        g.season,
        g.bdl_game_id,
        o.book_key,
        o.snapshot_at,
        g.datetime_utc,
        (g.datetime_utc - interval '3 hours') AS t_tip_minus_3h
    FROM game_odds_snapshots o
    JOIN games g
        ON g.league = o.league
       AND g.bdl_game_id = o.bdl_game_id
    WHERE o.league = 'nba'
      AND o.snapshot_kind = 'opening'
),
timed AS (
    SELECT
        season,
        bdl_game_id,
        book_key,
        snapshot_at,
        datetime_utc,
        t_tip_minus_3h,
        CASE
            WHEN snapshot_at IS NOT NULL AND datetime_utc IS NOT NULL
            THEN EXTRACT(EPOCH FROM (snapshot_at - datetime_utc)) / 3600.0
        END AS snapshot_minus_tip_hours
    FROM opening
)
SELECT
    season,
    count(*) AS total_rows,
    count(*) FILTER (WHERE snapshot_at IS NULL) AS null_snapshot_at,
    count(*) FILTER (WHERE datetime_utc IS NULL) AS null_tip,
    count(*) FILTER (
        WHERE snapshot_at IS NOT NULL
          AND datetime_utc IS NOT NULL
          AND snapshot_at <= t_tip_minus_3h
    ) AS rows_at_or_before_t,
    count(*) FILTER (
        WHERE snapshot_at IS NOT NULL
          AND datetime_utc IS NOT NULL
          AND snapshot_at > t_tip_minus_3h
    ) AS rows_after_t,
    count(*) FILTER (
        WHERE snapshot_at IS NOT NULL
          AND datetime_utc IS NOT NULL
          AND snapshot_at = t_tip_minus_3h
    ) AS rows_exact_boundary,
    count(DISTINCT bdl_game_id) AS games_with_any_opening_row,
    count(DISTINCT bdl_game_id) FILTER (
        WHERE snapshot_at IS NOT NULL
          AND datetime_utc IS NOT NULL
          AND snapshot_at <= t_tip_minus_3h
    ) AS games_with_row_at_or_before_t,
    min(snapshot_minus_tip_hours) AS min_snapshot_minus_tip_hours,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY snapshot_minus_tip_hours)
        AS median_snapshot_minus_tip_hours,
    max(snapshot_minus_tip_hours) AS max_snapshot_minus_tip_hours
FROM timed
GROUP BY season
ORDER BY season;

-- 2. Book counts per game. books_at_or_before_t is the eligible-book count
-- the feature code would see when the tip is present and hours_before_tip is 3.
-- A NULL tip is not given a fallback T in this count.
WITH per_game AS (
    SELECT
        g.season,
        g.bdl_game_id,
        count(*) AS opening_rows,
        count(*) FILTER (WHERE o.snapshot_at IS NULL) AS null_snapshot_at,
        count(DISTINCT o.book_key) AS distinct_books,
        count(DISTINCT o.book_key) FILTER (
            WHERE o.snapshot_at IS NOT NULL
              AND g.datetime_utc IS NOT NULL
              AND o.snapshot_at <= g.datetime_utc - interval '3 hours'
        ) AS books_at_or_before_t
    FROM game_odds_snapshots o
    JOIN games g
        ON g.league = o.league
       AND g.bdl_game_id = o.bdl_game_id
    WHERE o.league = 'nba'
      AND o.snapshot_kind = 'opening'
    GROUP BY g.season, g.bdl_game_id
)
SELECT season, bdl_game_id, opening_rows, null_snapshot_at, distinct_books, books_at_or_before_t
FROM per_game
ORDER BY season, bdl_game_id;

-- 3. Season rollup of query 2, so the per-game book counts can be read
-- without assuming one book or twelve books.
WITH per_game AS (
    SELECT
        g.season,
        g.bdl_game_id,
        count(DISTINCT o.book_key) FILTER (
            WHERE o.snapshot_at IS NOT NULL
              AND g.datetime_utc IS NOT NULL
              AND o.snapshot_at <= g.datetime_utc - interval '3 hours'
        ) AS books_at_or_before_t
    FROM game_odds_snapshots o
    JOIN games g
        ON g.league = o.league
       AND g.bdl_game_id = o.bdl_game_id
    WHERE o.league = 'nba'
      AND o.snapshot_kind = 'opening'
    GROUP BY g.season, g.bdl_game_id
)
SELECT
    season,
    count(*) AS games_with_any_opening_row,
    min(books_at_or_before_t) AS min_books_at_or_before_t,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY books_at_or_before_t)
        AS median_books_at_or_before_t,
    max(books_at_or_before_t) AS max_books_at_or_before_t,
    avg(books_at_or_before_t) AS avg_books_at_or_before_t
FROM per_game
GROUP BY season
ORDER BY season;

-- 4. Coverage denominator: every game, including games with no opening row.
SELECT
    g.season,
    count(DISTINCT g.bdl_game_id) AS games,
    count(DISTINCT o.bdl_game_id) AS games_with_any_opening_row
FROM games g
LEFT JOIN game_odds_snapshots o
    ON o.league = g.league
   AND o.bdl_game_id = g.bdl_game_id
   AND o.snapshot_kind = 'opening'
WHERE g.league = 'nba'
GROUP BY g.season
ORDER BY g.season;
