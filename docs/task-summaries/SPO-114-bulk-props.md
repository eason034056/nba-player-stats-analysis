# SPO-114 — Bulk NBA props from stored snapshots

- Ticket: SPO-114 (backend half, Option A)
- Branch: `feature/SPO-114-bulk-props` (from `origin/dev`)
- Base: `dev`

## Summary

`GET /api/nba/events/{event_id}/props` returns every stored player line for one NBA game. The only source is the latest `odds_line_snapshots` capture written by `odds_snapshot_service` for `SNAPSHOT_MARKETS`. The route does not call The Odds API, including when no capture exists and including when Redis or Postgres fails. A well-formed event id with no snapshot is HTTP 200 with empty `markets` and a null `snapshot_at`. A malformed event id is HTTP 404.

WNBA is unchanged.

## Changes

| Area | File | Change |
|---|---|---|
| Read path | `backend/app/services/bulk_props.py` | Assembles the payload from the latest snapshot. One bookmaker, one vote (`_main_book_line`). Player `line` is `calculate_mode_threshold` of those votes. 60s Redis cache of the assembled JSON. Postgres only on a miss. |
| HTTP | `backend/app/api/nba.py` | `GET /api/nba/events/{event_id}/props`. Optional `markets` and `player`. 404 / 400 / 503 / 500. No Odds API import on this handler. |
| Schema | `backend/app/models/schemas.py` | `BulkPropsResponse` and the nested book, player, and market models. |
| Parser | `backend/app/services/odds_snapshot_service.py` | `rows_from_bookmakers` is the existing parser, moved out of `_process_event` so tests can build rows without a fetch. Parse rules are unchanged. `_process_event` still fetches, then calls it. The new route does not call `_process_event`. |
| Tests | `backend/tests/test_spo114_bulk_props.py` | Recorded fixtures through the real parser. Provider and gateway patched and asserted unused. |
| Docs | `docs/decisions/spo-114-bulk-props/decision_20261110_snapshot-only.md`, `docs/progress.md` | Snapshot-only decision, credit math, options B and C not implemented. |

The path did not conflict. `GET /api/nba/events` remains the game list. Nothing else was mounted at `/events/{event_id}/props`.

## Why

The board needs every player in the game. Calling The Odds API once per player, or once per page view, spends credits the snapshot job has already spent. Option A serves that board from the table the scheduler writes. A miss stays empty so a cold event cannot turn into a live quote.

`_main_book_line` is local because SPO-115's helper is not on `dev`. A book that stored several totals (alternates) votes once: the row whose Over price, or Yes price on a binary market, is closest to a 50 percent implied probability. Ties break toward -110, then the lower line. The player's `line` is the mode of those votes (`calculate_mode_threshold`: unique mode, else the average of tied modes, else the median when every line appears once). `bookmakers_count` is the number of books after that collapse.

The snapshot writer still stores one pair per book, and that pair is the last Over and the last Under in the payload. This ticket does not change that write. The read path collapses extra rows when they are present. Making the writer store the same main line is a follow-up, not this change.

Binary markets keep the stored 0.5 sentinel on `line`. Yes and No are `yes_odds` and `no_odds`. A missing No is null. It is not copied onto `over_odds` or `under_odds`.

The 60 second cache holds the assembled JSON only. `data_age_seconds` is recomputed from `snapshot_at` on a hit. It is not a live-odds TTL. The live-odds rule (30 seconds in-game) does not apply, because this payload is a stored capture and says so with `source: "snapshot"`.

## API contract

`GET /api/nba/events/{event_id}/props`

Query:

| Name | Type | Required | Meaning |
|---|---|---|---|
| `markets` | string | no | Comma-separated market keys. Omit for every market in the capture. Unknown key: HTTP 400. A known key with no rows stays an empty `markets` list and still returns `snapshot_at` when a capture exists. |
| `player` | string | no | Exact player name, case-insensitive. Omit for every player. No match: `markets` is empty and `snapshot_at` is still set when a capture exists. |

`event_id` must match `^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`. Anything else is HTTP 404 `{"detail":"Malformed event_id"}` and is not queried. A well-formed id with no row is HTTP 200, not 404.

HTTP errors:

| Status | When |
|---|---|
| 200 | Capture found, or well-formed id with no capture. |
| 400 | `markets` contains a key outside the snapshot allow-list. |
| 404 | Malformed `event_id`. |
| 503 | Postgres is not connected. |
| 500 | The snapshot query failed. |

None of those responses call The Odds API.

Body: `BulkPropsResponse`. Every field is present. Nulls are JSON `null`, not omitted.

| Field | Type | Null |
|---|---|---|
| `event_id` | string | no |
| `snapshot_at` | string, ISO 8601 datetime | yes, when no capture exists |
| `data_age_seconds` | integer, whole seconds since `snapshot_at` | yes, when no capture exists |
| `source` | string, always `"snapshot"` | no |
| `markets` | array | no; empty array when nothing is stored or nothing matches |

`markets[]`:

| Field | Type | Null |
|---|---|---|
| `market` | string, market key | no |
| `players` | array | no |

Market order follows `SNAPSHOT_MARKETS`. Players are sorted by name, case-insensitive. Books are sorted by bookmaker key, case-insensitive.

`markets[].players[]`:

| Field | Type | Null |
|---|---|---|
| `player` | string | no |
| `line` | number | no. Modal consensus of one line per book. Binary markets are the 0.5 sentinel. |
| `bookmakers_count` | integer | no. Distinct books. Equal to `books.length`. |
| `books` | array | no |

`markets[].players[].books[]`:

| Field | Type | Null |
|---|---|---|
| `bookmaker` | string | no |
| `line` | number | no. That book's stored line (0.5 sentinel on a binary market). |
| `over_odds` | integer, American | yes. Posted Over. Null on a binary market. |
| `under_odds` | integer, American | yes. Posted Under. Null on a binary market. |
| `yes_odds` | integer, American | yes. Posted Yes on a binary market. Null on Over/Under. |
| `no_odds` | integer, American | yes. Posted No. Null when that side was not stored, and null on Over/Under. |

Example, no capture:

```json
{
  "event_id": "07361a8381206817e27bd2697fad7479",
  "snapshot_at": null,
  "data_age_seconds": null,
  "source": "snapshot",
  "markets": []
}
```

`snapshot_at` on a hit is the capture time, not the cache time. `data_age_seconds` is that age at response time, so a cache hit does not freeze the age. The cached document itself can be up to 60 seconds old, which only delays the first view of a brand-new capture.

## Tests

Rows come from `backend/tests/fixtures/odds_api_event_odds__player_points.json` and `backend/tests/fixtures/player-double-double-one-sided.json`, passed through `rows_from_bookmakers` (the snapshot parser). The one-sided file is a recorded no-vig body; the test copies `yes_price` / `no_price` into outcomes and parses those. It does not invent prices.

The Odds API gateway, provider (`get_events`, `get_event_odds`, `get_event_odds_with_usage`), and the provider's `httpx.AsyncClient` are patched. Every test asserts those mocks were not called. `bulk_props.py` does not import them. The route function source does not name them.

Covered: both markets in one payload, one vote per book against Bovada's alternate ladder (the vote is the closest-to-even total, not the last alternate, and `bookmakers_count` is 6 rather than the alternate-row count), one-sided double-double (`no_odds` null, Over/Under fields null), markets filter, player filter, empty filter, no snapshot, malformed id, unknown market, Postgres disconnected, query failure, Redis hit (no second read, age recomputed, TTL 60), and an older capture ignored when a newer one exists.

```
cd backend && pytest --tb=line -q
2 failed, 820 passed, 23 skipped, 6 xfailed
```

The two failures are the known Redis ones: `test_agent_chat_endpoint_validates_action_and_uses_service` and `test_lineups_api_returns_team_count`. Both die in slowapi with `ConnectionError` because Redis is not running. No other failure.

Integration tests that need `RUN_INTEGRATION=1` were not run. `ODDS_API_KEY` was not set and was not requested.

## Follow-ups

- Option B (on-demand refresh, at most one Odds API call per game per 30 minutes) is not implemented. Waiting on the owner.
- Option C (one extra pre-tip snapshot) is not implemented. Waiting on the owner.
- The snapshot writer still keeps the last Over/Under pair when a book posts alternates. The read path already collapses extra rows to the main line. Teaching the writer to store that same line is separate.
- Frontend wiring of this contract is the other half of the board. This change is backend only.
- WNBA bulk props stay out while WNBA is paused.
