-- 007_injury_report_rows_order.sql: stable point-in-time order, league-first index.
--
-- 006 is already on dev and may have been applied, so this file does not
-- edit 006. The read had no ORDER BY, so two players in one report could
-- come back in either order. The game index started at bdl_game_id, so
-- the same game id in two leagues shared a leading column.
-- No BEGIN/COMMIT: the runner applies this file and records 007 together.

DROP INDEX nba_injury_report_rows_game_report_idx;

CREATE INDEX nba_injury_report_rows_game_report_idx
    ON nba_injury_report_rows (league, bdl_game_id, report_at);

-- Latest official report for one game with report_at <= T.
-- Pass NULL to use game_as_of (tip minus 3 hours). Equal to T is in.
-- One second after T is not, even though that row stays in the table.
-- Rows of that one report come back in a fixed order.
CREATE OR REPLACE FUNCTION injury_report_rows_asof(
    p_league league_code,
    p_bdl_game_id BIGINT,
    p_as_of TIMESTAMPTZ DEFAULT NULL)
RETURNS TABLE (
    report_at TIMESTAMPTZ,
    game_date DATE,
    game_time_et TEXT,
    matchup TEXT,
    team_name TEXT,
    bdl_game_id BIGINT,
    bdl_team_id INTEGER,
    player_raw TEXT,
    bdl_player_id INTEGER,
    match_method TEXT,
    status TEXT,
    reason TEXT,
    category TEXT,
    previous_status TEXT,
    not_yet_submitted BOOLEAN,
    all_players_available BOOLEAN
)
LANGUAGE sql STABLE AS $$
    SELECT r.report_at, r.game_date, r.game_time_et, r.matchup, r.team_name,
           r.bdl_game_id, r.bdl_team_id, r.player_raw, r.bdl_player_id,
           r.match_method, r.status, r.reason, r.category, r.previous_status,
           r.not_yet_submitted, r.all_players_available
    FROM nba_injury_report_rows r
    WHERE r.league = p_league
      AND r.bdl_game_id = p_bdl_game_id
      AND r.report_at = (
          SELECT max(i.report_at)
          FROM nba_injury_report_rows i
          WHERE i.league = p_league
            AND i.bdl_game_id = p_bdl_game_id
            AND i.report_at <= coalesce(p_as_of, game_as_of(p_league, p_bdl_game_id))
      )
    ORDER BY r.team_name, r.player_raw, r.not_yet_submitted, r.matchup, r.id
$$;
