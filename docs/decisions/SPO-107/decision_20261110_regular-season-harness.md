# Decision — Walk-forward history uses production game types

- **Ticket:** SPO-107
- **Date:** 2026-11-10
- **Status:** Accepted

## Context

SPO-97 made production stats regular-season only. `CSVPlayerHistoryService._allowed_game_types()` returns regular season unless the caller opts into playoffs or the play-in. A missing `game_type` counts as regular season, via `_game_type_of`. `tools.historical._games_for` uses that default.

The walk-forward harness was still scoring every non-DNP game and using those games as history. On the post-SPO-97 CSVs that disagreed with `get_player_stats`: a prior window that still held a playoff game produced a different rate than production, which drops that game. The CI guard never ran the comparison (`validate=0`), so the mismatch did not fail a job.

## Decision

Headline history and headline targets are `_allowed_game_types()` with both opt-in flags off. The harness calls that method. It does not keep a second list of game-type strings.

Playoff and play-in games are still scored. Their prior window is the regular-season list, which is what production would use on the morning of that game. Those rows are stored apart from the headline rows and reported under "Playoffs and play-in". They are not in the headline hit rate, ROI, Brier, calibration tables, or the recorded oracle.

The Cup final stays out of both lists. `_allowed_game_types` does not include `cup_championship` even when playoffs and the play-in are opted in.

The CI sample guard compares 25 daily L10 rates per league, seed 7, with `get_player_stats`. Any mismatch fails the job. Zero sampled rows fails too.

## Alternatives

1. *Filter history only, and leave playoff targets inside the headline.* Rejected. The headline would still mix a postseason game into the number this report compares with the regular-season product.
2. *Drop playoff and play-in games from the report.* Rejected. They are real games in the file. The question "what would production have said, using regular-season history" is answerable, and it should be visible without entering the headline.
3. *Copy the token `regular_season` into the harness.* Rejected. A new opt-in on the service would not reach the replay, and the two lists would drift.

## Tradeoff

A playoff game's prior does not include earlier playoff games or the play-in. That matches production's default (`include_playoffs` and `include_play_in` off). It is the wrong history for a question about series form. That question is the opt-in flags, which this report does not claim to answer.
