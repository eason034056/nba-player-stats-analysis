-- 004_read_layer.sql: SPO-138i read layer for the frontend and the ML model.
-- Version 003 is SPO-138g's 003_bdl_game_gaps.sql.
--
-- Additive only: one table (predictions) and four views. No 002 table is
-- altered. The file has no BEGIN/COMMIT: the runner applies it and records the
-- version in one transaction.

-- One row per model run for one player, game, and market. The model reads no
-- prop odds, so a row carries no line, book, or price.
CREATE TABLE predictions (
    league          league_code NOT NULL,
    bdl_game_id     BIGINT      NOT NULL,
    bdl_player_id   INTEGER     NOT NULL,
    market          TEXT        NOT NULL,
    model_version   TEXT        NOT NULL CHECK (model_version <> ''),
    predicted_at    TIMESTAMPTZ NOT NULL,
    predicted_value NUMERIC     NOT NULL CHECK (predicted_value >= 0),
    distribution    JSONB       CHECK (jsonb_typeof(distribution) = 'object'),
    PRIMARY KEY (league, bdl_game_id, bdl_player_id, market, model_version, predicted_at),
    FOREIGN KEY (league, bdl_game_id) REFERENCES games (league, bdl_game_id),
    FOREIGN KEY (league, bdl_player_id) REFERENCES players (league, bdl_player_id),
    FOREIGN KEY (league, market) REFERENCES prop_markets (league, market)
);

CREATE INDEX predictions_player_market_idx
    ON predictions (league, bdl_player_id, market, predicted_at);

-- predicted_at is the insert's transaction start time, whatever the writer
-- sends. The tip-off refusal uses the wall clock at the INSERT, not now(), so
-- a stored row proves the INSERT itself ran before tip-off. A backtest cannot
-- write here.
CREATE FUNCTION predictions_check_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    tip  TIMESTAMPTZ;
    rule TEXT;
BEGIN
    NEW.predicted_at := now();

    SELECT datetime_utc INTO tip
    FROM games
    WHERE league = NEW.league AND bdl_game_id = NEW.bdl_game_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'predictions: game % is not in games', NEW.bdl_game_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF tip IS NULL THEN
        RAISE EXCEPTION 'predictions: game % has no datetime_utc to check against', NEW.bdl_game_id
            USING ERRCODE = 'check_violation';
    END IF;
    IF clock_timestamp() >= tip THEN
        RAISE EXCEPTION 'predictions: game % tipped off at %', NEW.bdl_game_id, tip
            USING ERRCODE = 'check_violation';
    END IF;

    SELECT settle_rule INTO rule
    FROM prop_markets
    WHERE league = NEW.league AND market = NEW.market;
    IF rule = 'double_digits' AND NEW.predicted_value > 1 THEN
        RAISE EXCEPTION 'predictions: % is a probability, got %', NEW.market, NEW.predicted_value
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END
$$;

CREATE TRIGGER predictions_check_insert
    BEFORE INSERT ON predictions
    FOR EACH ROW EXECUTE FUNCTION predictions_check_insert();

CREATE FUNCTION predictions_refuse_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'predictions is append-only; % is refused', TG_OP
        USING ERRCODE = 'restrict_violation';
END
$$;

CREATE TRIGGER predictions_refuse_change
    BEFORE UPDATE OR DELETE ON predictions
    FOR EACH ROW EXECUTE FUNCTION predictions_refuse_change();

CREATE VIEW current_predictions AS
SELECT DISTINCT ON (league, bdl_game_id, bdl_player_id, market, model_version)
    league, bdl_game_id, bdl_player_id, market, model_version,
    predicted_at, predicted_value, distribution
FROM predictions
ORDER BY league, bdl_game_id, bdl_player_id, market, model_version, predicted_at DESC;

-- The result of every market for every stat line of a final game. Columns are
-- looked up by the names in prop_markets.stat_columns, so a new market is a
-- seed row; each name must be an INTEGER column of player_game_stats.
-- NULL means void (dnp) or not known (a needed stat is NULL).
CREATE VIEW prop_actuals AS
SELECT
    s.league,
    s.bdl_game_id,
    s.bdl_player_id,
    m.market,
    CASE
        WHEN s.dnp OR v.missing > 0 THEN NULL
        WHEN m.settle_rule = 'sum' THEN v.total
        ELSE (v.double_digits >= m.min_double_digits)::INTEGER
    END AS actual_value
FROM player_game_stats s
JOIN games g ON g.league = s.league AND g.bdl_game_id = s.bdl_game_id
CROSS JOIN LATERAL (SELECT to_jsonb(s) AS line) r
JOIN prop_markets m ON m.league = s.league
CROSS JOIN LATERAL (
    SELECT
        sum(x.value)::INTEGER                AS total,
        count(*) FILTER (WHERE x.value >= 10) AS double_digits,
        count(*) FILTER (WHERE x.value IS NULL) AS missing
    FROM unnest(m.stat_columns) AS c(name)
    CROSS JOIN LATERAL (SELECT (r.line ->> c.name)::INTEGER AS value) x
) v
WHERE g.status_state = 'final';

-- Latest row first, then the listed filter: filtering first would bring back
-- an older Out for a player whose newest row says he left the list.
CREATE VIEW current_injuries AS
SELECT league, bdl_player_id, bdl_team_id, status, return_date, description, snapshot_at
FROM (
    SELECT DISTINCT ON (league, bdl_player_id) *
    FROM injury_snapshots
    ORDER BY league, bdl_player_id, snapshot_at DESC
) latest
WHERE listed;

CREATE VIEW current_projected_lineups AS
SELECT
    l.league, l.bdl_game_id, l.bdl_team_id, l.updated_at, l.first_seen_at, l.status,
    p.bdl_player_id, p.position
FROM (
    SELECT DISTINCT ON (league, bdl_game_id, bdl_team_id) *
    FROM projected_lineups
    ORDER BY league, bdl_game_id, bdl_team_id, updated_at DESC
) l
JOIN projected_lineup_players p
    ON p.league = l.league
    AND p.bdl_game_id = l.bdl_game_id
    AND p.bdl_team_id = l.bdl_team_id
    AND p.updated_at = l.updated_at;
