-- 005_bdl_pit.sql: SPO-141 point-in-time, coverage, hit rate, and integrity
-- read layer on top of 002_bdl_core, 003_bdl_game_gaps, and 004_read_layer.
--
-- The 14 tables of 002 do not change. This file has no ALTER TABLE, DROP, or
-- COMMENT ON for any 002 object. It adds new tables, views, functions, plain
-- indexes, one unique index, and BEFORE INSERT OR UPDATE triggers.
-- It reuses 004 (prop_actuals, current_injuries, current_projected_lineups,
-- predictions) instead of redefining settlement.
-- No BEGIN/COMMIT: the runner applies the file and records the version in one
-- transaction.
--
-- T is tip-off minus 3 hours everywhere (Eason 2026-11-21). A push stays in
-- the last-N window and stays out of the hit-rate denominator (Eason
-- 2026-11-21: the sketch default stands).
--
-- Writes that 002 would have accepted are refused by objects that are not
-- table constraints:
--   player_game_stats_league_bdl_stat_id_uidx  unique (league, bdl_stat_id)
--   games_refuse_same_team                     home_team_id = visitor_team_id
--   games_refuse_orphan_stat_team              a team change that leaves a
--                                              stat row on neither side
--   player_game_stats_refuse_team_not_in_game  bdl_team_id is neither side
--   player_prop_snapshots_refuse_market_type_mismatch
-- bdl_integrity_problems is the backstop. On data these objects accept it
-- returns 0 rows. It still names a bad row if a trigger is disabled or the
-- unique index is dropped.

-- 1. The as-of time T. ------------------------------------------------------------------------
-- T = tip-off minus p_hours_before_tip (default 3). A game with no
-- datetime_utc uses 00:00 America/New_York on games.date, earlier than any
-- tip-off, so it cannot leak. The hours parameter is ignored in that case.
-- Same rule as the Python T in the dataset module.
CREATE FUNCTION game_as_of(
    p_league league_code, p_bdl_game_id BIGINT, p_hours_before_tip NUMERIC DEFAULT 3)
RETURNS TIMESTAMPTZ
LANGUAGE sql STABLE AS $$
    SELECT coalesce(
        g.datetime_utc - make_interval(secs => p_hours_before_tip * 3600),
        g.date::timestamp AT TIME ZONE 'America/New_York')
    FROM games g
    WHERE g.league = p_league AND g.bdl_game_id = p_bdl_game_id
$$;

-- 2. Poll coverage: proof that a point-in-time source was being collected. -------------------
-- One row per job run (injury refresh, projected lineups, live odds, closing
-- odds, live props, closing props). The first complete row per (league,
-- source) is the go-live marker for strict backtests.
CREATE TABLE source_refreshes (
    league       league_code NOT NULL,
    source       TEXT        NOT NULL CHECK (source IN (
                     'injuries', 'projected_lineups', 'game_odds_live', 'game_odds_closing',
                     'props_live', 'props_closing')),
    refreshed_at TIMESTAMPTZ NOT NULL,
    complete     BOOLEAN     NOT NULL,
    rows_seen    INTEGER     NOT NULL DEFAULT 0 CHECK (rows_seen >= 0),
    rows_written INTEGER     NOT NULL DEFAULT 0 CHECK (rows_written >= 0),
    error        TEXT,
    PRIMARY KEY (league, source, refreshed_at),
    CHECK (complete OR error IS NOT NULL)
);

-- False before go-live, or when the last complete refresh at or before
-- p_as_of is older than p_max_staleness (default 90 minutes). An incomplete
-- run does not count. Callers check this first; false means "unknown", never
-- "healthy".
CREATE FUNCTION source_covered(
    p_league league_code, p_source TEXT, p_as_of TIMESTAMPTZ,
    p_max_staleness INTERVAL DEFAULT '90 minutes')
RETURNS BOOLEAN
LANGUAGE sql STABLE AS $$
    SELECT coalesce(max(r.refreshed_at) >= p_as_of - p_max_staleness, FALSE)
    FROM source_refreshes r
    WHERE r.league = p_league AND r.source = p_source AND r.complete
      AND r.refreshed_at <= p_as_of
$$;

-- 3. Projected lineups: when a version became knowable, without altering 002. ----------------
-- A side table keyed like projected_lineups records how a version arrived.
-- No row means 'poll', so 002's rule stays the default.
-- known_from is derived, never stored:
--   poll           -> first_seen_at (002's rule)
--   backfill_final -> updated_at (the 2026-27 backfill, visible at its BDL time)
CREATE TABLE projected_lineup_sources (
    league        league_code NOT NULL,
    bdl_game_id   BIGINT      NOT NULL,
    bdl_team_id   INTEGER     NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL,
    source        TEXT        NOT NULL CHECK (source IN ('poll', 'backfill_final')),
    bdl_lineup_id BIGINT,
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (league, bdl_game_id, bdl_team_id, updated_at),
    FOREIGN KEY (league, bdl_game_id, bdl_team_id, updated_at)
        REFERENCES projected_lineups (league, bdl_game_id, bdl_team_id, updated_at)
);

CREATE VIEW projected_lineup_versions AS
SELECT
    l.league, l.bdl_game_id, l.bdl_team_id, l.updated_at, l.first_seen_at, l.status,
    coalesce(s.source, 'poll') AS source,
    s.bdl_lineup_id,
    CASE WHEN s.source = 'backfill_final' THEN l.updated_at ELSE l.first_seen_at END AS known_from
FROM projected_lineups l
LEFT JOIN projected_lineup_sources s
    ON s.league = l.league AND s.bdl_game_id = l.bdl_game_id
   AND s.bdl_team_id = l.bdl_team_id AND s.updated_at = l.updated_at;

COMMENT ON COLUMN projected_lineup_versions.known_from IS
    'As-of reads use known_from <= T. poll: first_seen_at. backfill_final: BDL updated_at.';

-- The newest version per team with known_from <= p_as_of, one row per
-- projected starter. 004's current_projected_lineups stays the latest read.
CREATE FUNCTION projected_lineups_asof(
    p_league league_code, p_bdl_game_id BIGINT, p_as_of TIMESTAMPTZ)
RETURNS TABLE (bdl_team_id INTEGER, updated_at TIMESTAMPTZ, known_from TIMESTAMPTZ,
               source TEXT, status TEXT, bdl_player_id INTEGER, lineup_position TEXT)
LANGUAGE sql STABLE AS $$
    SELECT v.bdl_team_id, v.updated_at, v.known_from, v.source, v.status,
           p.bdl_player_id, p.position
    FROM (
        SELECT DISTINCT ON (x.bdl_team_id) x.*
        FROM projected_lineup_versions x
        WHERE x.league = p_league AND x.bdl_game_id = p_bdl_game_id AND x.known_from <= p_as_of
        ORDER BY x.bdl_team_id, x.updated_at DESC
    ) v
    JOIN projected_lineup_players p
      ON p.league = p_league AND p.bdl_game_id = p_bdl_game_id
     AND p.bdl_team_id = v.bdl_team_id AND p.updated_at = v.updated_at
$$;

-- 4. Injuries as of T (the as-of twin of 004's current_injuries). ----------------------------
-- Latest row per player at or before T, then keep it only if listed. Filtering
-- first would bring back an older Out after a removal.
CREATE FUNCTION injuries_asof(p_league league_code, p_as_of TIMESTAMPTZ)
RETURNS TABLE (bdl_player_id INTEGER, bdl_team_id INTEGER, status TEXT, return_date DATE,
               description TEXT, snapshot_at TIMESTAMPTZ)
LANGUAGE sql STABLE AS $$
    SELECT l.bdl_player_id, l.bdl_team_id, l.status, l.return_date, l.description, l.snapshot_at
    FROM (
        SELECT DISTINCT ON (i.bdl_player_id) i.*
        FROM injury_snapshots i
        WHERE i.league = p_league AND i.snapshot_at <= p_as_of
        ORDER BY i.bdl_player_id, i.snapshot_at DESC
    ) l
    WHERE l.listed
$$;

-- 5. Inferred teammate availability, using only games dated before p_as_of. ------------------
-- On the roster for a final game means a stats row for that team in the same
-- season on or before the game and on or after it. Labeled
-- 'inferred_from_stats': it cannot tell rest from injury, and it misses
-- absences before a player's first appearance or after his last one.
-- A traded player is not "out" for the team he has left.
CREATE FUNCTION teammate_availability(
    p_league league_code, p_team INTEGER, p_season INTEGER, p_as_of DATE)
RETURNS TABLE (bdl_game_id BIGINT, date DATE, bdl_player_id INTEGER,
               state TEXT, is_out BOOLEAN, out_basis TEXT)
LANGUAGE sql STABLE AS $$
    WITH team_games AS (
        SELECT g.bdl_game_id, g.date
        FROM games g
        WHERE g.league = p_league AND g.season = p_season AND g.status_state = 'final'
          AND g.date < p_as_of AND p_team IN (g.home_team_id, g.visitor_team_id)
    ), spans AS (
        SELECT s.bdl_player_id, min(s.date) AS first_date, max(s.date) AS last_date
        FROM player_game_stats s
        WHERE s.league = p_league AND s.season = p_season AND s.bdl_team_id = p_team
          AND s.date < p_as_of
        GROUP BY s.bdl_player_id
    )
    SELECT tg.bdl_game_id, tg.date, sp.bdl_player_id,
           CASE WHEN s.bdl_player_id IS NULL THEN 'absent' WHEN s.dnp THEN 'dnp' ELSE 'played' END,
           (s.bdl_player_id IS NULL OR s.dnp),
           'inferred_from_stats'
    FROM team_games tg
    JOIN spans sp ON tg.date BETWEEN sp.first_date AND sp.last_date
    LEFT JOIN player_game_stats s
      ON s.league = p_league AND s.bdl_game_id = tg.bdl_game_id
     AND s.bdl_player_id = sp.bdl_player_id AND s.bdl_team_id = p_team
$$;

-- 6. Hit rate on demand, from 004's prop_actuals. --------------------------------------------
-- One row per final game the player has a stat line in, dated before p_before
-- (a date in America/New_York; pass the target game's date for a backtest,
-- today for the API).
-- result: sum markets over / under / push against p_threshold; double_digits
-- markets yes / no (p_threshold is ignored); void = dnp; unknown = a needed
-- stat is NULL.
-- Hit rate = over / (over + under), or yes / (yes + no). void, unknown, and
-- push are not in the denominator. A push still occupies one last-N slot.
CREATE FUNCTION player_market_results(
    p_league league_code, p_bdl_player_id INTEGER, p_market TEXT, p_threshold NUMERIC,
    p_before DATE)
RETURNS TABLE (bdl_game_id BIGINT, date DATE, season INTEGER, season_type TEXT,
               bdl_team_id INTEGER, opponent_team_id INTEGER, home_or_away TEXT,
               actual_value INTEGER, result TEXT)
LANGUAGE sql STABLE AS $$
    SELECT a.bdl_game_id, s.date, s.season, g.season_type, s.bdl_team_id,
           CASE s.bdl_team_id WHEN g.home_team_id THEN g.visitor_team_id
                              WHEN g.visitor_team_id THEN g.home_team_id END,
           CASE s.bdl_team_id WHEN g.home_team_id THEN 'home'
                              WHEN g.visitor_team_id THEN 'away' END,
           a.actual_value,
           CASE
               WHEN s.dnp                      THEN 'void'
               WHEN a.actual_value IS NULL     THEN 'unknown'
               WHEN m.settle_rule = 'double_digits' THEN
                    CASE WHEN a.actual_value = 1 THEN 'yes' ELSE 'no' END
               WHEN a.actual_value > p_threshold THEN 'over'
               WHEN a.actual_value < p_threshold THEN 'under'
               ELSE 'push'
           END
    FROM prop_actuals a
    JOIN player_game_stats s
      ON s.league = a.league AND s.bdl_game_id = a.bdl_game_id AND s.bdl_player_id = a.bdl_player_id
    JOIN games g ON g.league = a.league AND g.bdl_game_id = a.bdl_game_id
    JOIN prop_markets m ON m.league = a.league AND m.market = a.market
    WHERE a.league = p_league AND a.bdl_player_id = p_bdl_player_id AND a.market = p_market
      AND s.date < p_before
$$;

-- Last-N hit rate. The window is the last p_last_n games with a settled
-- result. void and unknown are skipped. A push stays in the window and out of
-- the denominator, so it uses one of the N slots. NULL p_last_n means every
-- settled game before p_before. bdl_game_id breaks a same-date tie.
-- Optional splits: NULL means "any".
CREATE FUNCTION player_hit_rate(
    p_league league_code, p_bdl_player_id INTEGER, p_market TEXT, p_threshold NUMERIC,
    p_before DATE, p_last_n INTEGER DEFAULT NULL,
    p_home_or_away TEXT DEFAULT NULL, p_opponent_team_id INTEGER DEFAULT NULL,
    p_season_type TEXT DEFAULT NULL)
RETURNS TABLE (games INTEGER, hits INTEGER, misses INTEGER, pushes INTEGER, hit_rate NUMERIC)
LANGUAGE sql STABLE AS $$
    WITH w AS (
        SELECT r.result
        FROM player_market_results(p_league, p_bdl_player_id, p_market, p_threshold, p_before) r
        WHERE r.result NOT IN ('void', 'unknown')
          AND (p_home_or_away    IS NULL OR r.home_or_away = p_home_or_away)
          AND (p_opponent_team_id IS NULL OR r.opponent_team_id = p_opponent_team_id)
          AND (p_season_type     IS NULL OR r.season_type = p_season_type)
        ORDER BY r.date DESC, r.bdl_game_id DESC
        LIMIT p_last_n
    )
    SELECT count(*)::INTEGER,
           count(*) FILTER (WHERE result IN ('over', 'yes'))::INTEGER,
           count(*) FILTER (WHERE result IN ('under', 'no'))::INTEGER,
           count(*) FILTER (WHERE result = 'push')::INTEGER,
           round(count(*) FILTER (WHERE result IN ('over', 'yes'))::NUMERIC
                 / NULLIF(count(*) FILTER (WHERE result IN ('over', 'yes', 'under', 'no')), 0), 4)
    FROM w
$$;

-- 7. Integrity backstop. ---------------------------------------------------------------------
-- Must return 0 rows on data the refusal objects accept. The verifier and the
-- tests read it; the API does not. The four names are the same words the
-- triggers and the unique index use.
CREATE VIEW bdl_integrity_problems AS
SELECT 'games_same_team' AS problem, g.league, g.season,
       g.bdl_game_id::TEXT AS key
FROM games g
WHERE g.home_team_id = g.visitor_team_id
UNION ALL
SELECT 'stat_id_duplicate', s.league, min(s.season), s.bdl_stat_id::TEXT
FROM player_game_stats s
GROUP BY s.league, s.bdl_stat_id
HAVING count(*) > 1
UNION ALL
SELECT 'stat_team_not_in_game', s.league, s.season,
       s.bdl_game_id::TEXT || ':' || s.bdl_player_id::TEXT
FROM player_game_stats s
JOIN games g ON g.league = s.league AND g.bdl_game_id = s.bdl_game_id
WHERE s.bdl_team_id IS DISTINCT FROM g.home_team_id
  AND s.bdl_team_id IS DISTINCT FROM g.visitor_team_id
UNION ALL
-- A sum market stored as milestone (or a double-digit market stored as
-- over_under). A player_points milestone would replace the opening over/under
-- row under 002's opening key. settle_rule = 'sum' must equal
-- market_type = 'over_under'. double_double and triple_double are
-- double_digits, so they must be milestone. Every other seeded market is sum,
-- so it must be over_under. The props adapter copies only a double_double
-- milestone and drops every other milestone; it does not map triple_double.
SELECT 'prop_market_type_mismatch', p.league, g.season, p.id::TEXT
FROM player_prop_snapshots p
JOIN prop_markets m ON m.league = p.league AND m.market = p.market
JOIN games g ON g.league = p.league AND g.bdl_game_id = p.bdl_game_id
WHERE (m.settle_rule = 'sum') <> (p.market_type = 'over_under');

-- 8. Plain indexes (new names; 002's indexes stay). ------------------------------------------
-- Per-player prop history. 002's (league, bdl_player_id, market) is a prefix
-- and stays, because dropping it would change 002.
CREATE INDEX player_prop_snapshots_player_market_game_idx
    ON player_prop_snapshots (league, bdl_player_id, market, bdl_game_id, snapshot_kind);
-- Who is out on team X at T.
CREATE INDEX injury_snapshots_team_latest_idx
    ON injury_snapshots (league, bdl_team_id, snapshot_at DESC);

-- 9. Refusal, without ALTER TABLE. -----------------------------------------------------------
-- bdl_stat_id is NOT NULL in 002, so the index needs no WHERE. Two rows with
-- the same (league, bdl_stat_id) cannot land. PostgreSQL treats this index as
-- an index, not a table constraint, so 002's constraint list is unchanged.
CREATE UNIQUE INDEX player_game_stats_league_bdl_stat_id_uidx
    ON player_game_stats (league, bdl_stat_id);

-- home_team_id = visitor_team_id. NULL = NULL is unknown, matching the view,
-- so a game whose teams are not filled yet is still allowed.
CREATE FUNCTION games_refuse_same_team() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.home_team_id = NEW.visitor_team_id THEN
        RAISE EXCEPTION 'games_same_team'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER games_refuse_same_team
    BEFORE INSERT OR UPDATE ON games
    FOR EACH ROW
    EXECUTE FUNCTION games_refuse_same_team();

-- A later edit of the two team ids must not leave a stored stat on neither
-- side. INSERT cannot orphan a stat: 002's foreign key requires the game row
-- before the stat row. Score and status updates do not fire this trigger.
CREATE FUNCTION games_refuse_orphan_stat_team() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM player_game_stats s
        WHERE s.league = NEW.league
          AND s.bdl_game_id = NEW.bdl_game_id
          AND s.bdl_team_id IS DISTINCT FROM NEW.home_team_id
          AND s.bdl_team_id IS DISTINCT FROM NEW.visitor_team_id
    ) THEN
        RAISE EXCEPTION 'stat_team_not_in_game'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER games_refuse_orphan_stat_team
    BEFORE UPDATE OF home_team_id, visitor_team_id ON games
    FOR EACH ROW
    EXECUTE FUNCTION games_refuse_orphan_stat_team();

-- The stat row's team is one of the two teams on the game. The game row
-- already exists (002's foreign key). Either side is accepted; a third team
-- that is already in teams is not. A team id with no teams row is left to
-- that foreign key, so a missing team still fails the page the same way.
-- An UPDATE of the stat is checked again.
CREATE FUNCTION player_game_stats_refuse_team_not_in_game() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM games g
        WHERE g.league = NEW.league
          AND g.bdl_game_id = NEW.bdl_game_id
          AND (NEW.bdl_team_id = g.home_team_id OR NEW.bdl_team_id = g.visitor_team_id)
    ) AND EXISTS (
        SELECT 1
        FROM teams t
        WHERE t.league = NEW.league AND t.bdl_team_id = NEW.bdl_team_id
    ) THEN
        RAISE EXCEPTION 'stat_team_not_in_game'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER player_game_stats_refuse_team_not_in_game
    BEFORE INSERT OR UPDATE ON player_game_stats
    FOR EACH ROW
    EXECUTE FUNCTION player_game_stats_refuse_team_not_in_game();

-- Same predicate as bdl_integrity_problems: (settle_rule = 'sum') must equal
-- (market_type = 'over_under'). A sum market (points and the other counting
-- props) stored as milestone is refused, including an ON CONFLICT update that
-- would replace the opening over/under row. A double_digits market
-- (double_double, triple_double) stored as over_under is refused. A
-- double_double milestone and a points over_under are accepted.
CREATE FUNCTION player_prop_snapshots_refuse_market_type_mismatch() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM prop_markets m
        WHERE m.league = NEW.league
          AND m.market = NEW.market
          AND (m.settle_rule = 'sum') <> (NEW.market_type = 'over_under')
    ) THEN
        RAISE EXCEPTION 'prop_market_type_mismatch'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER player_prop_snapshots_refuse_market_type_mismatch
    BEFORE INSERT OR UPDATE ON player_prop_snapshots
    FOR EACH ROW
    EXECUTE FUNCTION player_prop_snapshots_refuse_market_type_mismatch();
