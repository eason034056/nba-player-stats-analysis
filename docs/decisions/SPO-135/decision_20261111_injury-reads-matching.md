# Decision — injury status on reads, suffix-kept names, refill after restart

- **Ticket:** SPO-135e
- **Date:** 2026-11-11
- **Status:** Accepted

## Context

SPO-135c copies `injuries:nba:latest` onto NBA daily picks. Three gaps remained. `/reads` still passed `injury_status=None`, so an Out player kept a `combined_probability` on the game page. `match_injury_entry` compared names with `player_name_key`, which drops Jr/Sr/II/III/IV/V/VI, so a unique cache row for "Gary Trent Jr." blocked a pick named "Gary Trent". Startup refreshed only a missing key. A stale key waited for the next in-window tick, and `misfire_grace_time` of 1 second dropped a :07 or :37 the process had just missed.

Doubtful is still stored as Questionable with `raw_status` kept. SPO-135h stops the blend from blocking on that source word. This change did not touch it.

## Decision

1. `GET /api/nba/events/{id}/reads` loads `injuries:nba:latest` once per cache miss through `load_nba_pick_injuries` and matches each posted name with `match_injury_entry`. That is the same helper daily picks use. Out sets `combined_probability` to null. A stored Doubtful keeps a number, the same as Questionable (SPO-135h). The signals stay. A missing, stale, or malformed snapshot logs one warning and leaves the blend. The handler still does not call BALLDONTLIE or The Odds API. WNBA has no reads route and still does not load this snapshot.

2. Picks and reads do not have a BALLDONTLIE id. An Odds API outcome is `name`, `description`, `price`, and `point`. A snapshot row is a player name. `DailyPick` and `PropRead` have no `bdl_player_id` field. Both callers leave the id argument unset. The agent tool still passes an id when it has one, and that id still wins.

3. Injury names match on `_injury_name_key`. It folds case, punctuation, and accents through `normalize_name` and keeps the suffix. `Luka Dončić` matches `luka doncic`. `Gary Trent Jr.` matches `gary trent jr`. `Gary Trent Jr.` does not match `Gary Trent`. There is no suffix-stripped fallback. Two rows that share that full key and carry different ids return no match. The code does not guess. `player_name_key` is unchanged for game logs and the other callers that already strip suffixes.

4. Startup still runs once per process. A missing key refreshes even outside the slate window. A key readers would reject (older than six hours, or `entries` not a list) refreshes only inside the window (11:00 through 00:59 America/Chicago). Outside the window a stale key is left in place. `injury_status` then stays null until the next in-window :07 or :37. After an overnight restart that is 11:07 America/Chicago. A restart between about 01:00 and 11:07 can leave Out players with a blend for hours.

5. `nba_injuries_refresh` `misfire_grace_time` is 25 minutes, with `coalesce` true and `max_instances` 1. A tick missed by less than 25 minutes runs once. Several missed ticks do not burst. The 429 rule is unchanged: one retry, a wait of at most 60 seconds, and the previous snapshot stays.

6. A fill on the first analysis run was considered and not added. `run_daily_analysis` is the HTTP daily-picks handler as well as the UTC 12:00 job. Calling BALLDONTLIE from it would put the shared 5-per-minute key on the request path. A scheduler-only fill at UTC 12:00 would be a second call site and would still leave a restart after that job and before 11:07 blind. The in-window startup refill plus the 25-minute grace covers a restart during the slate, which is when the board is being read. That is the smaller change inside the rate budget.

## Alternatives

1. *Keep the suffix-stripped fallback when it is unique and the pick has no suffix.* Rejected. "Gary Trent" would still attach to the only "Gary Trent Jr." row. The rule is exact after case, punctuation, and accents.
2. *Refresh a stale key at startup outside the window too.* Rejected for this change. The window is what keeps the overnight key idle. The empty-key fill outside the window stays, so a cold process is not blind.
3. *Refresh on the first daily-picks request when the snapshot is stale.* Rejected. The request path does not call BALLDONTLIE.
4. *Change Doubtful blocking.* Not in this change. SPO-135h makes NBA Doubtful keep the Questionable blend.

## Tradeoff

A deploy outside the slate window with a stale snapshot publishes picks and reads with null injury data until 11:07 America/Chicago. A missed :07 or :37 inside 25 minutes is caught. A longer outage inside the window is caught by the one startup refill.
