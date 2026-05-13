# SPO-31 — Scout end-of-task summary

**Ticket:** [SPO-31](/SPO/issues/SPO-31) — Phase 0 of [SPO-29](/SPO/issues/SPO-29) (wnba-rollout)
**Agent:** Scout (`1a495f58-b689-46b7-9e79-9d563b31175d`)
**Heartbeat:** 2026-05-13
**Outcome:** ✅ **Gate row 2** — close `done`, scope confirmed; flag 3 `schema-valid+empty` markets in close comment.

---

## What I did

1. **Wrote `scripts/explore_odds_api_wnba.py`** — stdlib-only, re-runnable exploration script that lists upcoming WNBA events and probes each of the 12 ticket-mandated markets against `/v4/sports/basketball_wnba/events/{eventId}/odds` with one probe per market. Classifies each as `hard-supported` / `schema-valid+empty` / `not-in-schema`. Mirrors the SPO-12 NBA-side script (`scripts/explore_odds_api_extensions.py`) per `CLAUDE.md § External API Wrappers` rule #1.
2. **Ran the script live against The Odds API on 2026-05-13.** Captured raw response bodies for all 13 calls (1 events list + 12 market probes) under `/tmp/odds_wnba_*.json`. Quota burn: 9 paid units / 500 monthly.
3. **Wrote `docs/research/wnba-rollout/odds_api_wnba_markets.md`** — full curl evidence per call (commands + first ~500 bytes raw response), 12-market support table, 6 captured event ids for Phase 2/5 fixture reuse, gate-1 disposition, and an inventory-gap note flagging that the ticket's 12-market list ≠ NBA's current production `SUPPORTED_MARKETS` (CTO decision deferred to Phase 2 boundary).

## Key findings (for CTO + Forge)

1. **`basketball_wnba` is fully on The Odds API.** All 12 ticket-listed market keys are recognised by the schema (no HTTP 4xx, no `not-in-schema` results). Gate-1 escalation does NOT fire — owner's claim that the API supports WNBA is verified.
2. **9 of 12 markets returned populated bookmaker lines today** (`player_points`, `player_rebounds`, `player_assists`, `player_threes`, `player_double_double`, `player_points_rebounds`, `player_points_assists`, `player_rebounds_assists`, `player_points_rebounds_assists`). All 3 **core** markets (points/rebounds/assists) are `hard-supported`.
3. **3 markets are `schema-valid+empty` today** (`player_steals`, `player_blocks`, `player_turnovers`). HTTP 200 + `bookmakers=[]` + 0 cost — the SAME shape the NBA side handles for FTM/FGM today, so Forge's Phase 2 path can reuse SPO-26's empty-bookmakers UX with zero code change.
4. **WNBA response shapes are identical to NBA.** Over/Under markets use `name ∈ {Over, Under}` + `point` field; binary DD uses `name=Yes` (sometimes `No`) + no `point` field. No new parser branches required in Forge's WNBA build — `OVER_UNDER_MARKET_KEYS` and `BINARY_MARKET_KEYS` from `backend/app/services/odds_snapshot_service.py` transfer 1:1.
5. **Inventory gap flagged for CTO (does NOT block Phase 2 start).** The ticket's 12 markets include `player_blocks` and `player_turnovers`, which are not in NBA's `daily_analysis.SUPPORTED_MARKETS` today; the ticket omits `player_frees_made` and `player_field_goals`, which ARE in NBA's list. Phase 2 needs a one-line CTO decision on WNBA-side `SUPPORTED_MARKETS` shape (12 per ticket vs 11 per NBA vs 13 including FTM/FGM). Scout lean: 12 per ticket (BLK/TOV ship as graceful-degrade from day 1).

## Quota burn

| | |
|---|---|
| Starting `x-requests-used` | 160 |
| Ending `x-requests-used`   | 169 |
| **Paid units consumed**    | **9** (9 populated probes × 1 unit; 3 empty probes × 0 unit; `/events` listing free) |
| Remaining                  | 331 / 500 |

Per-market billing model identical to NBA side (SPO-12 measurement still holds).

## Gate-1 disposition

Per SPO-31 §Gate behaviour table:

| Phase 0 result | Action |
|---|---|
| ✅ **Row 2 — Some `hard-supported`, some `schema-valid+empty`** | Close `done`, comment "scope confirmed", flag empty markets. Phase 2 auto-wakes on Forge. Phase 4 auto-wakes on Scout. |

Comment Scout will leave on close: list `player_steals`, `player_blocks`, `player_turnovers` as the 3 markets Forge should expect to need the NBA-side empty-bookmakers graceful-degrade UX (SPO-26 pattern).

## Files touched

| File | Type | Purpose |
|---|---|---|
| `scripts/explore_odds_api_wnba.py` | added | Re-runnable WNBA market probe script (stdlib only). Forge/Sentinel ground truth. |
| `docs/research/wnba-rollout/odds_api_wnba_markets.md` | added | Full curl-evidence research doc (12-market table + captured event ids + gate disposition). |
| `docs/task-summaries/SPO-31-odds-api-wnba-verification.md` | added | This file — Scout end-of-task summary. |

No backend / frontend code touched (correct per SPO-31 §Workflow — research-only ticket).

## Open questions for CTO (non-blocking for Phase 2 start)

1. WNBA `SUPPORTED_MARKETS` shape: 12 per ticket (incl. BLK/TOV) vs 11 per NBA (incl. FTM/FGM, excl. BLK/TOV) vs 13 (NBA ∪ ticket)? Scout lean: 12 per ticket.
2. Should NBA-side `daily_analysis.SUPPORTED_MARKETS` also gain BLK/TOV in a follow-up Forge ticket so the two leagues are symmetric? Out of SPO-31 scope.
3. Will the snapshot cadence / Redis TTL plan from SPO-26 carry over unchanged to WNBA, or does the smaller WNBA bookmaker count (1-3 vs NBA's 5-10) warrant a separate cadence? Out of SPO-31 scope.

## Next action

1. **Sentinel:** push `feature/SPO-31-odds-api-wnba-verification` to `origin`, open PR base=`dev`, PR body = this task summary.
2. **Scout (this agent):** after Sentinel pushes & owner merges, post the gate-2 close comment on SPO-31 (`scope confirmed; empty markets: steals/blocks/turnovers`). Issue then transitions to `done`, which auto-wakes Forge on SPO-32 (Phase 2) and Scout on SPO-33 (Phase 4) per the blocker chain in `decision_20260513_phase-decomposition.md`.
