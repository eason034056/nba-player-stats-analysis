# SPO-130 — Recorded same-slate fixtures (OKC at MIA)

- Ticket: SPO-130
- Branch: `feature/SPO-130-same-slate-fixtures` (from `origin/dev` `c409447`)

## Summary

Six recorded JSON files for Oklahoma City at Miami on 2026-11-22 now sit in `backend/tests/fixtures/same_slate/`. They were copied byte-for-byte from the capture Eason recorded with `scripts/record_bdl_odds_fixtures.py`. No key is in the URLs, headers, or fields. Production code, the existing pytest, and the 90% threshold are unchanged.

The consensus check is `TestMissingFixtures::test_same_slate_consensus_agrees_within_half_a_point`. The node id `TestRecordedSamples::test_same_slate_consensus_agrees_within_half_a_point` is not a test on `dev` (`pytest` exit 4, no match). The method that is in the tree passed and did not skip.

## Changes

| Area | File | Change |
|---|---|---|
| Fixtures | `backend/tests/fixtures/same_slate/2026-11-22_OKC@MIA__meta.json` | Capture clock `2026-11-22T21:53:15Z`, commence times, slate date, OKC and MIA. 248 bytes. |
| Fixtures | `backend/tests/fixtures/same_slate/2026-11-22_OKC@MIA__odds_api_events.json` | Odds API events list. 1986 bytes. |
| Fixtures | `backend/tests/fixtures/same_slate/2026-11-22_OKC@MIA__odds_api_odds.json` | Odds API odds for this game. 138017 bytes. |
| Fixtures | `backend/tests/fixtures/same_slate/2026-11-22_OKC@MIA__bdl_games.json` | BALLDONTLIE games. 10416 bytes. |
| Fixtures | `backend/tests/fixtures/same_slate/2026-11-22_OKC@MIA__bdl_props.json` | BALLDONTLIE player props. 1073126 bytes. |
| Fixtures | `backend/tests/fixtures/same_slate/2026-11-22_OKC@MIA__bdl_players.json` | BALLDONTLIE player names. 8405 bytes. |
| Note | `backend/tests/fixtures/README.md` | Lists this pair. `player_props_429.json` is still absent. |
| Attributes | `.gitattributes` | `same_slate/*.json` is `linguist-generated`, same as the other recorded captures. |
| Docs | `docs/task-summaries/SPO-130-same-slate-fixtures.md` | This file. |

## Why

The check skips when `backend/tests/fixtures/same_slate/` has no `*__meta.json`. These files are that pair, so the check can compare the two feeds with no API key.

## Tests

No `BALLDONTLIE_API_KEY` and no `ODDS_API_KEY`.

The node id on `TestRecordedSamples` does not collect:

```
cd backend && DATABASE_URL="" PYTHONPATH=. python -m pytest tests/test_spo130d_bdl_odds_provider.py::TestRecordedSamples::test_same_slate_consensus_agrees_within_half_a_point -q
```

Result: exit 4, `not found` (no match in `TestRecordedSamples`).

The method that exists:

```
cd backend && DATABASE_URL="" PYTHONPATH=. python -m pytest tests/test_spo130d_bdl_odds_provider.py::TestMissingFixtures::test_same_slate_consensus_agrees_within_half_a_point -q
```

Result: `1 passed`. Stdout: `same-slate consensus agreement 95/101 = 94.1% capture=2026-11-22T21:53:15Z`. Not a skip.

`--from-fixtures` (no key, writes nothing):

```
PYTHONPATH=backend python3 scripts/record_bdl_odds_fixtures.py --stats-only --from-fixtures backend/tests/fixtures/same_slate
```

```
capture=2026-11-22T21:53:15Z
shared=101
within_0.5=95
percent=94.1%
result=pass
market=player_assists shared=12 within_0.5=12 percent=100.0%
market=player_points shared=13 within_0.5=13 percent=100.0%
market=player_points_assists shared=12 within_0.5=11 percent=91.7%
market=player_points_rebounds shared=13 within_0.5=12 percent=92.3%
market=player_points_rebounds_assists shared=12 within_0.5=10 percent=83.3%
market=player_rebounds shared=13 within_0.5=13 percent=100.0%
market=player_rebounds_assists shared=12 within_0.5=10 percent=83.3%
market=player_steals shared=3 within_0.5=3 percent=100.0%
market=player_threes shared=11 within_0.5=11 percent=100.0%
```

Exit 0. Eason's live `--stats-only` run was also 95 of 101 (94.1%). His live per-market note was `player_points_assists` 9/12 (75%), `player_points_rebounds_assists` 10/12 (83.3%), `player_points_rebounds` 12/13, and 100% on the rest. This replay keeps the same 95/101 total. Two props sit on `player_points_assists` here (11/12) that his note had off that market, and `player_rebounds_assists` is 10/12 (83.3%) rather than 100%. The 90% bar still passes. The threshold and the adapter were not edited.

Mutation check: the comparison in that test was temporarily `assert rate >= 0.99`. The test failed (`agreement 94.1% is below 90% (95/101)`; the message text still says 90% because only the compared number was changed). The test file was restored. `git diff` for `backend/tests/test_spo130d_bdl_odds_provider.py` is empty.

Full backend suite, explicit local `DATABASE_URL` on `127.0.0.1:5441` (not `127.0.0.1:5434`), local Redis, no API key:

`1877 passed, 34 skipped, 4 xfailed`.

The same-slate test is not in the skip list. Skips that remain:

- Live HTTP tests that need `RUN_INTEGRATION=1` (The Odds API, BALLDONTLIE, ESPN, quota simulation).
- `player_props_429.json` is still not recorded (1 test).
- `test_spo132b_optional_vpc.py::TestVpcIdConsole`: 3 skipped, reason `terraform is not on PATH`.
- `test_spo140_terraform_environments.py`: 3 skipped, same reason.
- `test_spo132c_migrate_verify.py`: 1 skipped, `docker is not available`.

## Follow-ups

- A later ticket can move this test onto `TestRecordedSamples` if that node id should match the older note. This branch does not move it.
- `bdl/player_props_429.json` is still absent. The recorder writes it only when a live 429 happens.
