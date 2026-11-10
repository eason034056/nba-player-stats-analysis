# SPO-115 — Bookmaker count counted both sides

- Ticket: SPO-115
- Branch: `feature/SPO-115-bookmakers-count` (from `origin/dev`)
- Base: `dev`

## Summary

`_group_props_by_player` appended the `point` of every outcome. A normal book posts Over and Under at the same point, so `bookmakers_count = len(lines)` was about twice the number of books, and each book cast two votes in `calculate_mode_threshold`. Bovada also posts an alternate ladder (many points, each with Over and Under), so that one book cast a vote per rung per side.

Each bookmaker now contributes one main line per player per market. `bookmakers_count` is the number of distinct books. The main line is the two-sided rung closest to a coin flip after the vig is removed. Over and Under at different points are not averaged.

## Does pick selection change?

On the recorded Lakers @ Hawks `player_points` body (`backend/tests/fixtures/odds_api_event_odds__player_points.json`, event `07361a8381206817e27bd2697fad7479`, six US books), **no**.

There is no min-bookmaker filter. `bookmakers_count` is stored on `DailyPick` and shown on the picks pages (`{pick.bookmakers_count} bookmakers` / `books`). Nothing in `backend/app` drops a pick because the count is small. The old 2× number did not let a pick through a gate, and the corrected count does not remove one. C.J. McCollum is posted by five books (BetMGM does not post him) and still becomes a pick when the historical rate clears 0.65.

The modal line is the same for all 15 players before and after. `get_player_stats` is therefore called at the same threshold, so direction, probability, inclusion, and edge (`projected_value - threshold`) do not change on this fixture. What changes is the number and the contents of `all_lines`: one main line per book, not every Over, Under, and alternate rung. The picks page does not render `all_lines`.

| Player | Books | Old `len(lines)` | New `bookmakers_count` | Mode (before and after) |
|---|---:|---:|---:|---:|
| Aaron Wiggins | 6 | 24 | 6 | 13.5 |
| Austin Reaves | 6 | 26 | 6 | 21.5 |
| C.J. McCollum | 5 | 22 | 5 | 12.5 |
| Dyson Daniels | 6 | 22 | 6 | 10.5 |
| Jake LaRavia | 6 | 20 | 6 | 6.5 |
| Jalen Johnson | 6 | 28 | 6 | 20.5 |
| Kingston Flemings | 6 | 22 | 6 | 8.5 |
| Luguentz Dort | 6 | 20 | 6 | 7.5 |
| Luka Doncic | 6 | 32 | 6 | 36.5 |
| Matisse Thybulle | 6 | 20 | 6 | 6.5 |
| Nickeil Alexander-Walker | 6 | 28 | 6 | 19.5 |
| Onyeka Okongwu | 6 | 22 | 6 | 13.5 |
| Sandro Mamukelashvili | 5 | 20 | 5 | 8.5 |
| Walker Kessler | 6 | 24 | 6 | 14.5 |
| Ziaire Williams | 5 | 20 | 5 | 8.5 |

Equal doubling cannot move a mode: if every book contributes exactly two copies of one point, the winner stays the winner. A mode moves only when some books contribute a different number of rows than others (an alternate ladder, or a one-sided quote). On this file each Bovada rung is a different point, so no single alternate outvotes the consensus point. Counting every unique rung once, or every Over once, still produces the same mode here. The count would still be wrong if those rungs were kept: Luka would be 16 (five other books plus Bovada's 11 rungs) instead of 6. The ticket requires the distinct-book count, so the ladder collapses to one vote.

A different slate can change the mode. Two books at 20.5 and one book with three alternate rungs all sitting on 21.5 used to elect 21.5 (the ladder had more rows). It now elects 20.5. That case is not in the recorded fixture.

## Changes

| Area | File | Change |
|---|---|---|
| Grouping | `backend/app/services/daily_analysis.py` | One main line per bookmaker per player per market. See the line list below. |
| API copy | `backend/app/models/schemas.py` | `DailyPick.bookmakers_count` is distinct books. `all_lines` is one main line per book. `threshold` is the mode of those lines. Types are unchanged. |
| Frontend copy | `frontend/lib/schemas.ts` | Same three comments, in Traditional Chinese. The Zod types are unchanged. The picks pages already print `bookmakers_count` and do not render `all_lines`. |
| Existing unit test | `backend/tests/test_daily_analysis.py` | One book posting 15.5, 16.5, 15.5 is one book. `bookmakers_count` is 1 and `all_lines` is `[15.5]`. |
| Regression | `backend/tests/test_spo115_bookmakers_count.py` | Recorded `player_points` fixture. Count equals distinct books. Mode matches the old outcome-row mode. Bovada's ladder votes the even-money rung. |

### Exact lines in `daily_analysis.py`

SPO-112 also edits this file. The constructors were not rewritten.

| Lines | What |
|---|---|
| 27 | `Counter` added to the `collections` import. |
| 37–41 | Import `american_to_prob` and `posted_american_odds` next to `calculate_mode_threshold`. |
| 337–356 | New `_book_id`. Odds API `key`, else `title`, else `#<index>`. |
| 359–386 | New `_even_money_distance`. Vig-free distance from 0.5. |
| 389–411 | New `_posted_point`. A posted number when prices are missing. No average. |
| 414–487 | New `_main_book_line`. One rung per book. |
| 1048–1115 | `_group_props_by_player` rewritten. Was the loop that appended every `point` (old ~L891–L933). |

These call sites still say `len(lines)` / `sorted(lines)` / `calculate_mode_threshold(lines)`. They moved down because the helpers were inserted above them. The behavior change is the list, not these expressions.

| Now | Was | Expression |
|---|---|---|
| 865 | ~708 | `mode_threshold = calculate_mode_threshold(lines)` |
| 948 | ~791 | `bookmakers_count=len(lines)` on the Over `DailyPick` |
| 949 | ~792 | `all_lines=sorted(lines)` on the Over `DailyPick` |
| 981 | ~824 | `bookmakers_count=len(lines)` on the Under `DailyPick` |
| 982 | ~825 | `all_lines=sorted(lines)` on the Under `DailyPick` |

## Why

The field was documented as "number of bookmakers offering this line". The implementation counted outcome rows. Over -113 and Under -113 at 10.5 are one book.

Alternate lines are the case where one book's Over point and Under point are not a single shared number. Bovada posts a ladder: Aaron Wiggins has seven points, Luka Doncic has eleven, each point with both sides. Grouping to `{player: {bookmaker_key: line}}` means one of those points.

The point kept is the two-sided rung whose vig-free Over, `p_over / (p_over + p_under)`, is closest to 0.5. Over -110 / Under -110 scores 0. A one-sided rung is used only when the book posted no two-sided rung, and it is scored by the raw implied probability. An equal distance keeps the lower posted point. Prices that are missing, zero, or not a number are ignored (`posted_american_odds`). With no usable price at all, the book's own posted mode is used; a tie returns a point that was actually posted (the middle tied value, or the lower of the two central ones). Over 24.5 and Under 25.5 do not become 25.0.

That choice is the balanced number the rest of the market is quoting. Averaging two different points publishes a line nobody posted. Keeping every rung lets one book outvote the field. On this fixture the balanced Bovada rung matches the consensus for 14 of 15 players. Onyeka Okongwu's Bovada rung is 12.5 while the other five books are 13.5, so the mode stays 13.5 and he still counts as one book.

Two markets in one payload stay separate, so a points line and a rebounds line are not collapsed. `_analyze_single_event` already requests one market at a time, which is why `len(lines)` equals the distinct-book count on that path. The same function serves WNBA. This change does not add a WNBA path.

## Consumers audited

| Consumer | What it does with the list | After this change |
|---|---|---|
| `calculate_mode_threshold(lines)` | Consensus threshold for history, side, and edge | One vote per book. Mode unchanged on the recorded fixture. |
| `DailyPick.bookmakers_count` | `len(lines)`, returned by the daily-picks API | Distinct books. Schema description updated. Type still `int`. |
| `DailyPick.all_lines` | `sorted(lines)`, distribution payload | One main line per book, sorted. |
| Min-bookmaker filter | None in `backend/app`, the daily-picks route, or the picks pages | No inclusion change. |
| Picks UI | Prints `bookmakers_count` only | The printed number drops from the outcome-row count (20–32) to 5 or 6. |
| `scripts/agents/tools/market.py` `_extract_player_lines` | Separate parser. It already pairs Over with Under into one row per book, but the dict is keyed only by side, so a ladder keeps the last Over and the last Under in file order. | Not a consumer of this list. Not changed. |

## Tests

```
cd backend && /tmp/nba-venv/bin/python -m pytest -q --tb=line
2 failed, 815 passed, 23 skipped, 6 xfailed, 3 warnings in 11.55s
```

The two failures are the known Redis-only ones. Nothing else failed.

- `tests/test_agent_chat.py::test_agent_chat_endpoint_validates_action_and_uses_service` — `slowapi` `AttributeError: 'ConnectionError' object has no attribute 'detail'`
- `tests/test_lineup_consensus.py::test_lineups_api_returns_team_count` — same Redis `ConnectionError`

`tests/test_spo115_bookmakers_count.py` loads the recorded fixture and does not hand-type an API body. It asserts `bookmakers_count` equals the number of distinct bookmaker keys that post that player, that the modal line matches the pre-fix outcome-row mode, that FanDuel's Over/Under at 10.5 for Dyson Daniels is one line, and that Bovada alone votes Aaron Wiggins 13.5 (7 rungs), Luka 36.5 (11 rungs), and Onyeka Okongwu 12.5 (6 rungs). Two real Bovada Luka rows at different points (Over 36.5, Under 37.5) stay on 36.5 and are not averaged to 37.0. WNBA daily-analysis tests pass; no WNBA behavior was added.

Integration test: SKIPPED (no live Odds API call; the fixture is the recorded response).

Fabrication scan (mock without fixture): PASS. The regression reads `odds_api_event_odds__player_points.json`. The existing unit test still builds a minimal `{description, point}` payload, which is the shape that file already used.

## Follow-ups

- [ ] `scripts/agents/tools/market.py` `_extract_player_lines` keeps the last Over and last Under when a book posts a ladder. On Bovada's file order that is the highest alternate, not the even-money rung. `n_books` on the market tools is that parser, not `DailyPick.bookmakers_count`.
- [ ] A slate where one book's ladder repeats a single off-consensus point can change the modal line. Not observed on the recorded fixture.
