-- 002_bdl_core.sql: SPO-138 core tables for BALLDONTLIE history.
--
-- Additive only. No legacy table is read, altered, or dropped.
-- The file has no BEGIN/COMMIT: the runner applies it and records the
-- version in one transaction, so a failure part-way leaves nothing behind.
--
-- league has no default. BALLDONTLIE's NBA and WNBA ids overlap, so a writer
-- that leaves league out must fail instead of landing on an NBA row.

CREATE DOMAIN league_code AS TEXT CHECK (VALUE IN ('nba', 'wnba'));

CREATE TABLE books (
    league       league_code NOT NULL,
    book_key     TEXT        NOT NULL,
    source_group TEXT        NOT NULL,
    display_name TEXT        NOT NULL,
    active       BOOLEAN     NOT NULL DEFAULT TRUE,
    PRIMARY KEY (league, book_key)
);

INSERT INTO books (league, book_key, source_group, display_name) VALUES
    ('nba', 'draftkings', 'draftkings', 'DraftKings'),
    ('nba', 'fanduel',    'fanduel',    'FanDuel'),
    ('nba', 'betmgm',     'betmgm',     'BetMGM'),
    ('nba', 'caesars',    'caesars',    'Caesars'),
    ('nba', 'betrivers',  'betrivers',  'BetRivers'),
    ('nba', 'fanatics',   'fanatics',   'Fanatics'),
    ('nba', 'betparx',    'parx_bally', 'BetParx'),
    ('nba', 'ballybet',   'parx_bally', 'Bally Bet'),
    ('nba', 'betway',     'betway',     'Betway'),
    ('nba', 'rebet',      'rebet',      'Rebet');

CREATE TABLE seasons (
    league            league_code NOT NULL,
    season_start_year INTEGER     NOT NULL,
    label             TEXT        NOT NULL,
    start_date        DATE,
    end_date          DATE,
    PRIMARY KEY (league, season_start_year)
);

CREATE TABLE teams (
    league       league_code NOT NULL,
    bdl_team_id  INTEGER     NOT NULL,
    abbreviation TEXT,
    name         TEXT,
    full_name    TEXT,
    city         TEXT,
    conference   TEXT,
    division     TEXT,
    PRIMARY KEY (league, bdl_team_id)
);

-- position is the player's position today, as BALLDONTLIE sends it.
-- The position in one game is game_lineups.position.
CREATE TABLE players (
    league        league_code NOT NULL,
    bdl_player_id INTEGER     NOT NULL,
    first_name    TEXT,
    last_name     TEXT,
    display_name  TEXT        NOT NULL,
    position      TEXT,
    PRIMARY KEY (league, bdl_player_id)
);

CREATE INDEX players_display_name_idx ON players (league, display_name);

-- The /v1/games object does not carry its type, and its postseason flag
-- differs by season for the play-in. The writer records the season_type it
-- asked for, translated to the product game type (CANONICAL_GAME_TYPES in
-- app/services/game_log_hygiene.py): regular -> regular_season,
-- playoffs -> playoffs, playin -> play_in, ist -> cup_championship.
-- Preseason is never fetched. No other table stores a game's type.
CREATE TABLE games (
    league          league_code NOT NULL,
    bdl_game_id     BIGINT      NOT NULL,
    season          INTEGER     NOT NULL,
    date            DATE        NOT NULL,
    datetime_utc    TIMESTAMPTZ,
    status          TEXT,
    status_state    TEXT,
    postponed       BOOLEAN,
    season_type     TEXT        NOT NULL CHECK (
        season_type IN ('regular_season', 'playoffs', 'play_in', 'cup_championship')
    ),
    home_team_id    INTEGER,
    visitor_team_id INTEGER,
    home_score      INTEGER,
    visitor_score   INTEGER,
    home_q1         INTEGER,
    home_q2         INTEGER,
    home_q3         INTEGER,
    home_q4         INTEGER,
    home_ot1        INTEGER,
    home_ot2        INTEGER,
    home_ot3        INTEGER,
    visitor_q1      INTEGER,
    visitor_q2      INTEGER,
    visitor_q3      INTEGER,
    visitor_q4      INTEGER,
    visitor_ot1     INTEGER,
    visitor_ot2     INTEGER,
    visitor_ot3     INTEGER,
    period          INTEGER,
    ist_stage       TEXT,
    PRIMARY KEY (league, bdl_game_id),
    UNIQUE (league, bdl_game_id, season, date),
    FOREIGN KEY (league, season) REFERENCES seasons (league, season_start_year),
    FOREIGN KEY (league, home_team_id) REFERENCES teams (league, bdl_team_id),
    FOREIGN KEY (league, visitor_team_id) REFERENCES teams (league, bdl_team_id)
);

CREATE INDEX games_date_idx ON games (league, date);
CREATE INDEX games_season_date_idx ON games (league, season, date);

-- season and date are copies of the game's, kept for the (player, date) and
-- (season, date) reads. The composite foreign key keeps them equal to games,
-- and ON UPDATE CASCADE carries a rescheduled date over.
CREATE TABLE player_game_stats (
    league         league_code  NOT NULL,
    bdl_stat_id    BIGINT       NOT NULL,
    bdl_game_id    BIGINT       NOT NULL,
    bdl_player_id  INTEGER      NOT NULL,
    bdl_team_id    INTEGER      NOT NULL,
    season         INTEGER      NOT NULL,
    date           DATE         NOT NULL,
    min_raw        TEXT,
    seconds_played INTEGER      CHECK (seconds_played >= 0),
    dnp            BOOLEAN      NOT NULL,
    pts            INTEGER,
    reb            INTEGER,
    oreb           INTEGER,
    dreb           INTEGER,
    ast            INTEGER,
    stl            INTEGER,
    blk            INTEGER,
    turnover       INTEGER,
    pf             INTEGER,
    fgm            INTEGER,
    fga            INTEGER,
    fg_pct         NUMERIC(4,3) CHECK (fg_pct BETWEEN 0 AND 1),
    fg3m           INTEGER,
    fg3a           INTEGER,
    fg3_pct        NUMERIC(4,3) CHECK (fg3_pct BETWEEN 0 AND 1),
    ftm            INTEGER,
    fta            INTEGER,
    ft_pct         NUMERIC(4,3) CHECK (ft_pct BETWEEN 0 AND 1),
    plus_minus     INTEGER,
    PRIMARY KEY (league, bdl_game_id, bdl_player_id),
    FOREIGN KEY (league, bdl_game_id, season, date)
        REFERENCES games (league, bdl_game_id, season, date) ON UPDATE CASCADE,
    FOREIGN KEY (league, bdl_player_id) REFERENCES players (league, bdl_player_id),
    FOREIGN KEY (league, bdl_team_id) REFERENCES teams (league, bdl_team_id),
    CONSTRAINT player_game_stats_dnp_has_no_line CHECK (
        NOT dnp OR num_nonnulls(
            seconds_played, pts, reb, oreb, dreb, ast, stl, blk, turnover, pf,
            fgm, fga, fg_pct, fg3m, fg3a, fg3_pct, ftm, fta, ft_pct, plus_minus
        ) = 0
    ),
    CONSTRAINT player_game_stats_played_has_seconds CHECK (dnp OR seconds_played IS NOT NULL)
);

CREATE INDEX player_game_stats_player_date_idx ON player_game_stats (league, bdl_player_id, date);
CREATE INDEX player_game_stats_season_date_idx ON player_game_stats (league, season, date);
CREATE INDEX player_game_stats_team_date_idx ON player_game_stats (league, bdl_team_id, date);

-- BALLDONTLIE has no removal event: a player who recovers drops off the list.
-- listed = false records that drop. The writer finds it by comparing a complete
-- refresh with each player's last row; a partial refresh must not write one.
CREATE TABLE injury_snapshots (
    league        league_code NOT NULL,
    snapshot_at   TIMESTAMPTZ NOT NULL,
    bdl_player_id INTEGER     NOT NULL,
    listed        BOOLEAN     NOT NULL,
    bdl_team_id   INTEGER,
    status        TEXT,
    return_date   DATE,
    description   TEXT,
    PRIMARY KEY (league, snapshot_at, bdl_player_id),
    FOREIGN KEY (league, bdl_player_id) REFERENCES players (league, bdl_player_id),
    FOREIGN KEY (league, bdl_team_id) REFERENCES teams (league, bdl_team_id),
    CONSTRAINT injury_snapshots_removal_has_no_details CHECK (
        listed OR num_nonnulls(status, return_date, description) = 0
    )
);

CREATE INDEX injury_snapshots_player_latest_idx
    ON injury_snapshots (league, bdl_player_id, snapshot_at DESC);

CREATE TABLE game_lineups (
    league        league_code NOT NULL,
    bdl_game_id   BIGINT      NOT NULL,
    bdl_player_id INTEGER     NOT NULL,
    bdl_team_id   INTEGER,
    starter       BOOLEAN     NOT NULL,
    position      TEXT,
    PRIMARY KEY (league, bdl_game_id, bdl_player_id),
    FOREIGN KEY (league, bdl_game_id) REFERENCES games (league, bdl_game_id),
    FOREIGN KEY (league, bdl_player_id) REFERENCES players (league, bdl_player_id),
    FOREIGN KEY (league, bdl_team_id) REFERENCES teams (league, bdl_team_id)
);

-- updated_at is when BALLDONTLIE published a version; first_seen_at is when our
-- job first stored it. A read as of time T takes the newest version with
-- first_seen_at <= T, so it never sees one published but not yet polled.
CREATE TABLE projected_lineups (
    league        league_code NOT NULL,
    bdl_game_id   BIGINT      NOT NULL,
    bdl_team_id   INTEGER     NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    status        TEXT,
    PRIMARY KEY (league, bdl_game_id, bdl_team_id, updated_at),
    FOREIGN KEY (league, bdl_game_id) REFERENCES games (league, bdl_game_id),
    FOREIGN KEY (league, bdl_team_id) REFERENCES teams (league, bdl_team_id)
);

CREATE TABLE projected_lineup_players (
    league        league_code NOT NULL,
    bdl_game_id   BIGINT      NOT NULL,
    bdl_team_id   INTEGER     NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL,
    bdl_player_id INTEGER     NOT NULL,
    position      TEXT,
    PRIMARY KEY (league, bdl_game_id, bdl_team_id, updated_at, bdl_player_id),
    FOREIGN KEY (league, bdl_game_id, bdl_team_id, updated_at)
        REFERENCES projected_lineups (league, bdl_game_id, bdl_team_id, updated_at),
    FOREIGN KEY (league, bdl_player_id) REFERENCES players (league, bdl_player_id)
);

CREATE TABLE prop_markets (
    league            league_code NOT NULL,
    market            TEXT        NOT NULL,
    bdl_prop_type     TEXT        NOT NULL,
    stat_columns      TEXT[]      NOT NULL,
    settle_rule       TEXT        NOT NULL CHECK (settle_rule IN ('sum', 'double_digits')),
    min_double_digits SMALLINT,
    PRIMARY KEY (league, market),
    UNIQUE (league, bdl_prop_type),
    CHECK ((settle_rule = 'sum') = (min_double_digits IS NULL))
);

INSERT INTO prop_markets (league, market, bdl_prop_type, stat_columns, settle_rule, min_double_digits) VALUES
    ('nba', 'player_points',                  'points',                  '{pts}',                 'sum',           NULL),
    ('nba', 'player_rebounds',                'rebounds',                '{reb}',                 'sum',           NULL),
    ('nba', 'player_assists',                 'assists',                 '{ast}',                 'sum',           NULL),
    ('nba', 'player_threes',                  'threes',                  '{fg3m}',                'sum',           NULL),
    ('nba', 'player_steals',                  'steals',                  '{stl}',                 'sum',           NULL),
    ('nba', 'player_blocks',                  'blocks',                  '{blk}',                 'sum',           NULL),
    ('nba', 'player_points_rebounds',         'points_rebounds',         '{pts,reb}',             'sum',           NULL),
    ('nba', 'player_points_assists',          'points_assists',          '{pts,ast}',             'sum',           NULL),
    ('nba', 'player_rebounds_assists',        'rebounds_assists',        '{reb,ast}',             'sum',           NULL),
    ('nba', 'player_points_rebounds_assists', 'points_rebounds_assists', '{pts,reb,ast}',         'sum',           NULL),
    ('nba', 'player_double_double',           'double_double',           '{pts,reb,ast,stl,blk}', 'double_digits', 2),
    ('nba', 'player_triple_double',           'triple_double',           '{pts,reb,ast,stl,blk}', 'double_digits', 3);

-- In both odds tables, snapshot_at is BALLDONTLIE's opened_at on an opening
-- row and the job time on a live or closing row; source_updated_at is
-- BALLDONTLIE's updated_at. Opening keys leave snapshot_at out: a retry whose
-- opened_at moved or went missing must update the first row, not add a
-- second opening line.
CREATE TABLE game_odds_snapshots (
    id                  BIGSERIAL   PRIMARY KEY,
    league              league_code NOT NULL,
    snapshot_kind       TEXT        NOT NULL CHECK (snapshot_kind IN ('opening', 'live', 'closing')),
    bdl_game_id         BIGINT      NOT NULL,
    book_key            TEXT        NOT NULL,
    snapshot_at         TIMESTAMPTZ,
    source_updated_at   TIMESTAMPTZ,
    spread_home_value   NUMERIC,
    spread_home_odds    INTEGER,
    spread_away_value   NUMERIC,
    spread_away_odds    INTEGER,
    moneyline_home_odds INTEGER,
    moneyline_away_odds INTEGER,
    total_value         NUMERIC,
    total_over_odds     INTEGER,
    total_under_odds    INTEGER,
    CHECK (snapshot_kind = 'opening' OR snapshot_at IS NOT NULL),
    FOREIGN KEY (league, bdl_game_id) REFERENCES games (league, bdl_game_id),
    FOREIGN KEY (league, book_key) REFERENCES books (league, book_key)
);

CREATE UNIQUE INDEX game_odds_snapshots_opening_key
    ON game_odds_snapshots (league, bdl_game_id, book_key)
    WHERE snapshot_kind = 'opening';
CREATE UNIQUE INDEX game_odds_snapshots_tick_key
    ON game_odds_snapshots (league, snapshot_kind, bdl_game_id, book_key, snapshot_at)
    WHERE snapshot_kind IN ('live', 'closing');
CREATE INDEX game_odds_snapshots_game_idx
    ON game_odds_snapshots (league, bdl_game_id, snapshot_kind, snapshot_at);

-- One row per player, book, and market at each snapshot: the main line only.
-- BALLDONTLIE sends a whole ladder for one player and stat at one time (17 rows
-- in the recorded DraftKings rebounds), so the writer picks the main line
-- before the insert. A second line under the same key replaces the first.
CREATE TABLE player_prop_snapshots (
    id                BIGSERIAL   PRIMARY KEY,
    league            league_code NOT NULL,
    snapshot_kind     TEXT        NOT NULL CHECK (snapshot_kind IN ('opening', 'live', 'closing')),
    bdl_game_id       BIGINT      NOT NULL,
    bdl_player_id     INTEGER     NOT NULL,
    book_key          TEXT        NOT NULL,
    market            TEXT        NOT NULL,
    market_type       TEXT        NOT NULL CHECK (market_type IN ('over_under', 'milestone')),
    line              NUMERIC     NOT NULL,
    over_odds         INTEGER,
    under_odds        INTEGER,
    milestone_odds    INTEGER,
    snapshot_at       TIMESTAMPTZ,
    source_updated_at TIMESTAMPTZ,
    CHECK (snapshot_kind = 'opening' OR snapshot_at IS NOT NULL),
    CONSTRAINT player_prop_snapshots_odds_fit_market_type CHECK (
        (market_type = 'over_under'
            AND over_odds IS NOT NULL AND under_odds IS NOT NULL AND milestone_odds IS NULL)
        OR (market_type = 'milestone'
            AND milestone_odds IS NOT NULL AND over_odds IS NULL AND under_odds IS NULL)
    ),
    FOREIGN KEY (league, bdl_game_id) REFERENCES games (league, bdl_game_id),
    FOREIGN KEY (league, bdl_player_id) REFERENCES players (league, bdl_player_id),
    FOREIGN KEY (league, book_key) REFERENCES books (league, book_key),
    FOREIGN KEY (league, market) REFERENCES prop_markets (league, market)
);

CREATE UNIQUE INDEX player_prop_snapshots_opening_key
    ON player_prop_snapshots (league, bdl_game_id, bdl_player_id, book_key, market)
    WHERE snapshot_kind = 'opening';
CREATE UNIQUE INDEX player_prop_snapshots_tick_key
    ON player_prop_snapshots (league, snapshot_kind, bdl_game_id, bdl_player_id, book_key, market, snapshot_at)
    WHERE snapshot_kind IN ('live', 'closing');
CREATE INDEX player_prop_snapshots_game_latest_idx
    ON player_prop_snapshots (league, bdl_game_id, snapshot_kind, snapshot_at DESC);
CREATE INDEX player_prop_snapshots_player_market_idx
    ON player_prop_snapshots (league, bdl_player_id, market);

-- rows_written is what the shard has stored, set from count(*) after each
-- page, so a replay cannot inflate it. rows_fetched, rows_dropped, and
-- rows_rejected count what BALLDONTLIE sent, which the tables cannot recount
-- because dropped and rejected rows are not stored. They are added to in the
-- page's transaction, so each page is counted once; a restart resets the row.
CREATE TABLE bdl_backfill_checkpoints (
    league        league_code NOT NULL,
    data_type     TEXT        NOT NULL CHECK (data_type IN (
                      'games', 'stats', 'opening_odds', 'opening_props',
                      'lineups', 'projected_lineups', 'players', 'teams')),
    season        INTEGER     NOT NULL DEFAULT 0,
    shard_key     TEXT        NOT NULL DEFAULT '',
    cursor        TEXT,
    status        TEXT        NOT NULL CHECK (status IN ('in_progress', 'done', 'error')),
    rows_written  BIGINT      NOT NULL DEFAULT 0,
    pages_fetched INTEGER     NOT NULL DEFAULT 0,
    rows_fetched  BIGINT      NOT NULL DEFAULT 0,
    rows_dropped  BIGINT      NOT NULL DEFAULT 0,
    rows_rejected BIGINT      NOT NULL DEFAULT 0,
    last_error    TEXT,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (league, data_type, season, shard_key)
);

-- The per-game row the history readers want, built from ids. Abbreviations
-- are BALLDONTLIE's current ones (team 3 is BKN in 2000-01 too), so filter by
-- team id. is_starter and position come from game_lineups and are null for a
-- game with no lineup row.
CREATE VIEW player_game_log AS
SELECT
    s.league,
    s.bdl_game_id,
    s.bdl_player_id,
    s.bdl_team_id,
    side.opponent_team_id,
    s.season,
    s.date,
    g.season_type,
    side.home_or_away,
    p.display_name AS player_name,
    t.abbreviation AS team_abbr,
    o.abbreviation AS opponent_abbr,
    l.starter AS is_starter,
    l.position,
    s.min_raw, s.seconds_played, s.dnp,
    s.pts, s.reb, s.oreb, s.dreb, s.ast, s.stl, s.blk, s.turnover, s.pf,
    s.fgm, s.fga, s.fg_pct, s.fg3m, s.fg3a, s.fg3_pct, s.ftm, s.fta, s.ft_pct,
    s.plus_minus
FROM player_game_stats s
JOIN games g ON g.league = s.league AND g.bdl_game_id = s.bdl_game_id
CROSS JOIN LATERAL (
    SELECT
        CASE s.bdl_team_id WHEN g.home_team_id THEN 'home' WHEN g.visitor_team_id THEN 'away' END
            AS home_or_away,
        CASE s.bdl_team_id WHEN g.home_team_id THEN g.visitor_team_id WHEN g.visitor_team_id THEN g.home_team_id END
            AS opponent_team_id
) side
JOIN players p ON p.league = s.league AND p.bdl_player_id = s.bdl_player_id
JOIN teams t ON t.league = s.league AND t.bdl_team_id = s.bdl_team_id
LEFT JOIN teams o ON o.league = s.league AND o.bdl_team_id = side.opponent_team_id
LEFT JOIN game_lineups l
    ON l.league = s.league AND l.bdl_game_id = s.bdl_game_id AND l.bdl_player_id = s.bdl_player_id;
