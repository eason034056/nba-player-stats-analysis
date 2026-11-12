# Decision — Remove the projection vendor

- **Ticket:** SPO-135
- **Date:** 2026-11-11
- **Status:** Accepted

> Superseded in part by SPO-135c (2026-11-11): NBA picks and event reads omit the projection signal. The slot returns when the ML model ships.

## Context

The SportsDataIO projection feed was not a real model. It must not feed picks, the UI, or RDS. NBA rows in RDS come from BALLDONTLIE. That API has no projection endpoint. A CSV average is not a projection, and the betting line is not a stand-in. WNBA already ran without a projection client and stays that way.

## Decision

1. `projected_value`, `edge`, and `projected_minutes` are not filled from a vendor. The `DailyPick` fields stay optional and default to null. `has_projection` is false. The `projection` signal slot stays and is missing, the same way WNBA already leaves it.

2. `GET /api/nba/projections`, `GET /api/nba/projections/{player}`, and `POST /api/nba/projections/refresh` are removed, including the router include and the startup key check. The frontend still calls those routes until a paired frontend PR. This PR does not edit `frontend/`.

3. `player_projections` and `projection_fetch_logs` stay in `SCHEMA_SQL`. Nothing reads or writes them. A later change drops them after a grep shows no remaining reference outside the schema.

4. The projection service, the vendor client, the early/mid/final projection jobs, the manual trigger, `sportsdata_api_key`, `sportsdata_base_url`, `cache_ttl_projections`, and the compose env lines for those settings are removed. Event reads do not look up a projection cache. Daily analysis does not take a team from a projection row.

5. Defense ranks come from the NBA game log only. The source is `csv`. `sportsdata` and `sportsdata_invalid` are not emitted. The frontend schema does not enumerate those sources.

6. `injury_status` and `lineup_confirmed` on `DailyPick` were copied from the projection row. Lineup consensus and `team_lineup_snapshots` do not write them. After this change they are null. This PR does not add a BALLDONTLIE injuries call.

7. The agent projection tools stay unavailable. The reason is `no projection source; ML model pending`. The source string is `projection_stub`.

8. Current docs (`CLAUDE.md`, `README.md`, `docs/dev-doc.md`) describe the live path. `docs/player-stats-projection-api.md` is deleted. Historical decision logs stay, with a one-line superseded note where the old text still reads as current policy. `docs/progress.md` is not edited here.
