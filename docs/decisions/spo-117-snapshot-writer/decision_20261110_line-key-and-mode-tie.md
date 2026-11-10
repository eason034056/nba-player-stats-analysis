# Decision — SPO-117 snapshot rows and the consensus tie

- **Ticket:** SPO-117
- **Date:** 2026-11-10
- **Status:** Accepted

## Context

`odds_line_snapshots` is the only source for bulk props (SPO-114). The scheduled writer (`odds_snapshot_early` / `mid` / `final`) was logging a successful run with zero lines. Two further bugs sat on the rows that would have been written: the unique key had no room for an alternate total, and a tied mode could become a number nobody posted.

The proof uses the recorded Odds API bodies in `backend/tests/fixtures/` (`odds_api_events__basketball_nba.json` and `odds_api_event_odds__player_points.json`). No new response shape was typed in.

## Why the table stayed empty

`_get_events` treats `date` as a local calendar date and `tz_offset_minutes` as minutes east of UTC. The default offset was 480 (UTC+8). The scheduler passed the UTC calendar date and left that default.

The recorded Lakers at Hawks tip is `2026-11-10T00:10:00Z`. That is 19:10 on 2026-11-09 in America/New_York and 08:10 on 2026-11-10 in Taipei. At the mid job, 2026-11-09 22:05 UTC, the UTC date plus offset 480 does not contain that tip. The same instant in New York is 2026-11-09 with offset -300, and that window contains the evening slate (eight recorded events). The job then logged success with "No events", which is an empty `odds_line_snapshots` table next to a row in `odds_snapshot_logs`.

These were checked and are not the empty-table cause:

- The three jobs are registered, and a manual `POST /api/nba/odds-history/snapshot` calls the same writer.
- The insert commits when it runs. asyncpg `executemany` is not wrapped in a transaction that rolls back on success.
- A repeated key inside one `executemany` updates the existing row. It does not abort the batch, so the old unique key did not produce zero rows.
- A missing Under (`under_odds` NULL on a Yes-only double-double) inserts.

A write exception used to be caught around `executemany`, logged as success, and discarded. That path was not what emptied the table. It is still the wrong status, so a write error now reaches the outer handler, which logs `status = "error"` and re-raises. A disconnected database still skips the write and reports the parsed count, which is the existing contract.

## Decision: US game date for the snapshot only

`take_snapshot()` with no date uses `nba_slate_date()`: the calendar date in America/New_York, and that zone's offset in minutes. An explicit date is a US game date. Its offset is Eastern at noon that day, which is after the 02:00 DST fold. 2026-11-09 is -300. 2026-07-15 is -240.

The latest scheduled job is 23:35 UTC, which is still the same Eastern date. A call after midnight UTC on the previous Eastern evening stays on that US slate because the clock is Eastern, not UTC.

`run_daily_analysis` is unchanged. Its default offset is still 480, and the HTTP caller can pass the viewer's offset. That board means "today" for the person looking at it. The snapshot `date` column is the Eastern game date, which is what the table comment already said.

## Decision: the unique key includes the line

The old key was `(snapshot_at, event_id, player_name, market, bookmaker)`. The parser also kept only the last Over and the last Under per player, so a Bovada ladder was stored as the last alternate.

The key is now `(snapshot_at, event_id, player_name, market, bookmaker, line)`, named `odds_line_snapshots_book_line_key`. The line is part of the identity, so the upsert does not update `line`. A second total is a new row.

The new key is wider than the old one. Every existing row still satisfies it. Nothing is rewritten or deleted. There is no Alembic migration. `DatabaseService.init()` runs `SCHEMA_SQL` on startup. The SPO-117 block drops every UNIQUE constraint on `odds_line_snapshots` whose columns do not include `line` (the primary key is `contype = 'p'`, so it is left alone) and adds the named key when it is missing. Running it again does nothing. A fresh database gets the named key from `CREATE TABLE`.

The parser pairs Over and Under only when they share a point, rounded to one decimal. A rung with one side is skipped. A later quote at the same point replaces that side. Both the main total and each alternate are stored. Read-side `_main_book_line` still collapses one book to one vote.

NULL lines are distinct in a Postgres unique index. The parser does not emit a NULL line. Binary double-double keeps the 0.5 sentinel on a different market key.

## Decision: one vote per book, then a posted tie

Bulk props and daily analysis already chose each book's main line with `_main_book_line` / `_even_money_distance` before the mode. That collapse only helps if the ladder is stored. With every rung stored, the alt totals still must not vote. `assemble_bulk_props` keeps that order: one stored row per book (the main line), then `calculate_mode_threshold` across books.

A tie is not averaged. Averaging 24.5 and 25.5 produces 25.0, which nobody posted. SPO-115 already refused to blend two points inside one book. The cross-book rule matches that refusal.

`calculate_mode_threshold(lines, distances=None)`:

1. The unique mode wins.
2. A tie is every line that shares the highest count. That includes the case where every line appears once. Previously an even count of all-unique lines averaged the two central values (the docstring example `[24.5, 25.0, 25.5, 26.0]` returned 25.25) and an odd count took the median. Both of those results are now the tie below, so the consensus is always a posted line.
3. If `distances` is passed, one per vote, the tied line with the smallest distance wins. A line's distance is the smallest `_even_money_distance` among the books that voted it. Lower is closer to a coin flip.
4. If those distances are equal, or `distances` is omitted, the lower posted line wins (`min` of the tied lines).

A two-way tie with no prices still returns the lower line. The old "lower of the two central values" rule did the same thing for exactly two modes, so those tests stay. Three or more tied lines used to keep the middle one. They now keep the lower line unless a distance says otherwise.

Within one book, `_posted_point` is unchanged. With no usable price, an odd count of posted points keeps the middle point, and an even count keeps the lower of the two central points. That is the SPO-115 rule for a book that did not price the ladder. It is not the cross-book tie. An unpriced book's cross-book distance is 1.0, which is worse than any priced rung.

Daily analysis passes the same distances through `_group_main_votes`. `_group_props_by_player` still returns one float per book, which is the point half of that vote. WNBA calls the same `calculate_mode_threshold`. It has no snapshot writer. Its daily-analysis date and offset are unchanged.
