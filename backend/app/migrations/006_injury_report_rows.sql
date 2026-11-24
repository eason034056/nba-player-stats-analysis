-- 006_injury_report_rows.sql: official NBA injury-report rows.
--
-- One row is one player, one NOT YET SUBMITTED team, or one
-- ALL PLAYERS AVAILABLE team, from one stored PDF. Re-ingesting that
-- PDF hits nba_injury_report_rows_natural_key and writes nothing new.
-- bdl_player_id and match_method stay null until a later matching step.
--
-- The read for a game is the latest report_at at or before T.
-- T is game_as_of (tip minus 3 hours) when the caller does not pass
-- a time. A report at T is included. A report one second later is
-- stored and is not selected.
--
-- source_refreshes.source gains 'injuries_nba_official'. The BALLDONTLIE
-- list keeps 'injuries'. Every value from 005 stays allowed.
-- No BEGIN/COMMIT: the runner applies this file and records 006 together.

ALTER TABLE source_refreshes DROP CONSTRAINT source_refreshes_source_check;

ALTER TABLE source_refreshes ADD CONSTRAINT source_refreshes_source_check
    CHECK (source IN (
        'injuries',
        'projected_lineups',
        'game_odds_live',
        'game_odds_closing',
        'props_live',
        'props_closing',
        'injuries_nba_official'
    ));

CREATE TABLE nba_injury_report_rows (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    league                league_code NOT NULL,
    report_at             TIMESTAMPTZ NOT NULL,
    game_date             DATE        NOT NULL,
    game_time_et          TEXT,
    matchup               TEXT        NOT NULL,
    team_name             TEXT        NOT NULL,
    bdl_game_id           BIGINT,
    bdl_team_id           INTEGER,
    player_raw            TEXT        NOT NULL DEFAULT '',
    bdl_player_id         INTEGER,
    match_method          TEXT,
    status                TEXT,
    reason                TEXT,
    category              TEXT,
    previous_status       TEXT,
    not_yet_submitted     BOOLEAN     NOT NULL DEFAULT FALSE,
    all_players_available BOOLEAN     NOT NULL DEFAULT FALSE,
    CONSTRAINT nba_injury_report_rows_natural_key UNIQUE (
        league, report_at, game_date, matchup, team_name, player_raw, not_yet_submitted
    ),
    CONSTRAINT nba_injury_report_rows_status_check CHECK (
        status IS NULL OR status IN (
            'Out', 'Questionable', 'Doubtful', 'Probable', 'Available'
        )
    ),
    CONSTRAINT nba_injury_report_rows_previous_status_check CHECK (
        previous_status IS NULL OR previous_status IN (
            'Out', 'Questionable', 'Doubtful', 'Probable', 'Available'
        )
    ),
    -- A player row has a name and a status. A team row is either
    -- NOT YET SUBMITTED or ALL PLAYERS AVAILABLE, and it has neither.
    CONSTRAINT nba_injury_report_rows_row_kind CHECK (
        (
            player_raw <> ''
            AND status IS NOT NULL
            AND NOT not_yet_submitted
            AND NOT all_players_available
        ) OR (
            not_yet_submitted
            AND player_raw = ''
            AND status IS NULL
            AND NOT all_players_available
        ) OR (
            all_players_available
            AND player_raw = ''
            AND status IS NULL
            AND NOT not_yet_submitted
        )
    ),
    FOREIGN KEY (league, bdl_game_id) REFERENCES games (league, bdl_game_id),
    FOREIGN KEY (league, bdl_team_id) REFERENCES teams (league, bdl_team_id),
    FOREIGN KEY (league, bdl_player_id) REFERENCES players (league, bdl_player_id)
);

-- The point-in-time read filters bdl_game_id and report_at.
CREATE INDEX nba_injury_report_rows_game_report_idx
    ON nba_injury_report_rows (bdl_game_id, report_at);

-- Latest official report for one game with report_at <= T.
-- Pass NULL to use game_as_of (tip minus 3 hours). Equal to T is in.
-- One second after T is not, even though that row stays in the table.
CREATE FUNCTION injury_report_rows_asof(
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
$$;
