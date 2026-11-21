-- 003_bdl_game_gaps.sql: leave BALLDONTLIE's broken games out of player_game_log.
--
-- A final game is broken when a team's player points differ from its score,
-- or its player minutes add to under 230. A team plays at least 240; seasons
-- that send whole minutes round a team's total to 231-239. These are gaps in
-- BALLDONTLIE's own data (data-model.md 1.6), so a re-walk returns the same
-- rows. A team with no lines counts as 0 points and 0 minutes.
--
-- The lines stay in player_game_stats as sent. The list is computed from them,
-- not kept on the side: when BALLDONTLIE corrects a game and its season is
-- walked again, the game comes back. backfill/verify.py reads the same view.
-- season is a grouping column so a per-season read filters before it sums.

CREATE VIEW bdl_games_with_gaps AS
SELECT league, bdl_game_id, season, points_off, minutes_short
FROM (
    SELECT
        g.league,
        g.bdl_game_id,
        g.season,
        coalesce(sum(s.pts) FILTER (WHERE s.bdl_team_id = g.home_team_id), 0) <> g.home_score
            OR coalesce(sum(s.pts) FILTER (WHERE s.bdl_team_id = g.visitor_team_id), 0) <> g.visitor_score
            AS points_off,
        least(
            coalesce(sum(s.seconds_played) FILTER (WHERE s.bdl_team_id = g.home_team_id), 0),
            coalesce(sum(s.seconds_played) FILTER (WHERE s.bdl_team_id = g.visitor_team_id), 0)
        ) < 230 * 60 AS minutes_short
    FROM games g
    JOIN player_game_stats s ON s.league = g.league AND s.bdl_game_id = g.bdl_game_id
    WHERE g.status_state = 'final'
    GROUP BY g.league, g.bdl_game_id, g.season
) per_game
WHERE points_off OR minutes_short;

-- As in 002, with every line of a listed game left out.
CREATE OR REPLACE VIEW player_game_log AS
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
    ON l.league = s.league AND l.bdl_game_id = s.bdl_game_id AND l.bdl_player_id = s.bdl_player_id
WHERE NOT EXISTS (
    SELECT 1 FROM bdl_games_with_gaps gap
    WHERE gap.league = s.league AND gap.bdl_game_id = s.bdl_game_id
);
