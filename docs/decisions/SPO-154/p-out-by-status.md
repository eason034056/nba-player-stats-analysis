# SPO-154 — p_out by official status

## Real 2024-25 fit: PENDING

No read-only history database was available, so the full 2024-25 season was not counted. The cells below are empty on purpose. They are not guesses written down as measurements. 2025-26 and 2026-27 were not used.

A later fit has to use only `games.season = 2024` (the 2024-25 season). T is `games.datetime_utc` minus 3 hours. A report at T counts. A report one second later does not. The did-not-play label is that game's box-score `dnp`. A player with no box-score row is left out.

| Status | p_out | rows | did not play | season | T rule | kind |
|---|---|---|---|---|---|---|
| Out | PENDING | PENDING | PENDING | 2024-25 only | tip minus 3 hours; equal to T counts | real fit not run |
| Doubtful | PENDING | PENDING | PENDING | 2024-25 only | tip minus 3 hours; equal to T counts | real fit not run |
| Questionable | PENDING | PENDING | PENDING | 2024-25 only | tip minus 3 hours; equal to T counts | real fit not run |
| Probable | PENDING | PENDING | PENDING | 2024-25 only | tip minus 3 hours; equal to T counts | real fit not run |
| Available | PENDING | PENDING | PENDING | 2024-25 only | tip minus 3 hours; equal to T counts | real fit not run |

## What the feature code reads today

`P_OUT_BY_OFFICIAL_STATUS` in `backend/app/ml/injury_weights.py` is the only copy of these five numbers. `WEIGHT_TABLE_SOURCE` is `prior`. The numbers are the old fixed scale. They are not a measured 2024-25 did-not-play rate.

| Status | p_out in the feature table | kind |
|---|---|---|
| Out | 1.0 | prior, not a 2024-25 count |
| Doubtful | 0.75 | prior, not a 2024-25 count |
| Questionable | 0.5 | prior, not a 2024-25 count |
| Probable | 0.1 | prior, not a 2024-25 count |
| Available | 0.0 | prior, not a 2024-25 count |

Day-To-Day is not an official report word. It stays `DAY_TO_DAY_P_OUT = 0.25` for the snapshot path. It was not fit from official reports.

## Fixture check

This is one made-up game, not the 2024-25 season. `games.season` is 2024. Tip is 2024-12-01 23:00 UTC. T is 2024-12-01 20:00 UTC. The counted report is exactly at T. The fitter returned these counts, and they match a hand count of the same rows.

| Status | p_out | rows | did not play | season | T rule | kind |
|---|---|---|---|---|---|---|
| Out | 1.0 | 4 | 4 | fixture, season field 2024 | tip minus 3 hours; report time equal to T | fixture |
| Doubtful | 0.75 | 4 | 3 | fixture, season field 2024 | tip minus 3 hours; report time equal to T | fixture |
| Questionable | 0.5 | 4 | 2 | fixture, season field 2024 | tip minus 3 hours; report time equal to T | fixture |
| Probable | 0.2 | 5 | 1 | fixture, season field 2024 | tip minus 3 hours; report time equal to T | fixture |
| Available | 0.0 | 4 | 0 | fixture, season field 2024 | tip minus 3 hours; report time equal to T | fixture |

Probable is 1/5 = 0.2 on this fixture. The feature table still has the prior 0.1. The fixture rate was not copied into the table.

The same run also saw a report one second after T, one 2025-26 game (season 2025), and one 2026-27 game (season 2026). Those rows did not change the counts above.
