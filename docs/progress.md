# Sports Lab Progress

> Maintained by CTO. Last refresh: **2026-05-02T23:27Z** (heartbeat: SPO-11 mention wake → Eason ✅ accepted plan v3 23:19:44Z; CTO opened [SPO-16](/SPO/issues/SPO-16) Forge backend Phase 2B, patched [SPO-15](/SPO/issues/SPO-15) audit spec to non-merge-gate, blocked SPO-11 on SPO-16). Prior refreshes: 23:20Z (plan v3 + Addendum 1), 23:18Z (SPO-15 stale-summary recovery), 23:16Z (CEO housekeeping).
> Source of truth: Paperclip API. This file is a snapshot — when in doubt, query paperclip directly.

---

## Active epics

| Epic | Current phase | Status | Assignee | Updated |
|---|---|---|---|---|
| [SPO-10 — State type increment](/SPO/issues/SPO-10) (擴充 event page 球員 prop stat types: 3PM/R+A/P+R/P+A/DD/STL/FTM/FGA/3PA) | **Phase 2 in flight** — Phase 0 done (plan v3 ✅ Eason 23:19:44Z); Phase 2A audit ([SPO-15](/SPO/issues/SPO-15)) in progress; **Phase 2B parser merge ([SPO-16](/SPO/issues/SPO-16)) just opened 23:26Z** (8 markets, DD binary, FTM/FGM graceful-degrade). Phase 3 (Forge frontend), Phase 4 (Sentinel), Phase 5 (Lens) not yet opened — phase-gated. | blocked | CEO (held) | 2026-05-02T23:27Z |

---

## Phase tickets in flight

| Ticket | Title | Phase | Status | Assignee | Branch |
|---|---|---|---|---|---|
| [SPO-11](/SPO/issues/SPO-11) | [CTO] SPO-10 規劃: 擴充 event page 球員 prop stat types | Phase orchestrator. v1 ✅ 20:31Z; v2 ❌ rejected 23:05Z; **v3 ✅ accepted 23:19:44Z**. Now monitoring Phase 2; blocked on [SPO-16](/SPO/issues/SPO-16) | blocked (`blockedBy=[SPO-16]`) | CTO (auto-wakes on `issue_blockers_resolved`) | _(no code branch — orchestrator only)_ |
| [SPO-15](/SPO/issues/SPO-15) | [Forge] SPO-10 Phase 2A: Snapshot cadence + Redis TTL audit | Phase 2A — quota/cadence audit. **v3 addendum 23:24Z**: no longer merge-gating per Q3 pre-approval; projection bumped to 12 markets (4 baseline + 8 new). Original spec body unchanged. | in_progress | Forge | `feature/SPO-15-snapshot-cadence-audit` |
| [SPO-16](/SPO/issues/SPO-16) | [Forge] SPO-10 Phase 2B: backend implementation (8 markets + DD binary parser + FTM/FGM graceful-degrade) | Phase 2B — backend parser merge. Spec includes DD binary path, FTM/FGM empty-bookmakers handling, FGM disambiguation integration test, 3 derived projection fields, 7 continuous + 1 binary csv metrics. Anti-hallucination guards cited verbatim. | in_progress | Forge | `feature/SPO-16-backend-stat-expansion` (Forge to create from `origin/dev`) |

---

## Blocked / awaiting owner

| Ticket | Blocker | Action needed |
|---|---|---|
| [SPO-10](/SPO/issues/SPO-10) | Phase chain in flight ([SPO-15](/SPO/issues/SPO-15) audit + [SPO-16](/SPO/issues/SPO-16) parser merge, Forge holds both). Epic stays blocked until Phase 5 (Lens) done — that's the design, not a problem. | None for owner now. Forge time-slices SPO-15 + SPO-16. CTO auto-wakes on SPO-16 close to open Phase 3 (frontend). |
| [SPO-11](/SPO/issues/SPO-11) | Blocked on [SPO-16](/SPO/issues/SPO-16) (Forge backend Phase 2B). Plan v3 accepted; CTO is now phase orchestrator monitoring only. | None for owner. CTO auto-wakes on SPO-16 close. |

---

## Recently completed (last 7 days)

| Ticket | Closed | Summary doc |
|---|---|---|
| [SPO-12](/SPO/issues/SPO-12) | 2026-05-02 | Scout: research The Odds API NBA player props 9 candidate markets (curl-evidenced). 6/9 hard-supported, 2/9 schema-valid+empty (FTM/FGA), 1/9 not in schema (3PA). Per-market billing confirmed. See `docs/research/event-page-stat-expansion/research_odds_api_markets.md` and `docs/task-summaries/SPO-12-odds-api-9-markets-research.md`. |
| [SPO-13](/SPO/issues/SPO-13) | 2026-05-02 (cancelled by CEO) | Scout-created CTO follow-up duplicate; Phase 1.5 deliverable lives on SPO-11 plan v2 + `decision_20260502_market-key-feasibility.md`. No artifact migration needed. |
| [SPO-14](/SPO/issues/SPO-14) | 2026-05-02 (cancelled by CEO) | Exact duplicate of SPO-13 (created 42s later by Scout retry collision). Same redirect as SPO-13. |
| [SPO-1](/SPO/issues/SPO-1) | 2026-05-02 | Hire your first engineer + hiring plan (parent epic). |
| [SPO-2](/SPO/issues/SPO-2) | 2026-05-02 | Architecture proposal: stack, topology, build-vs-buy. |
| [SPO-4](/SPO/issues/SPO-4) | 2026-05-02 | Compliance & licensing technical checklist v1. |
| [SPO-8](/SPO/issues/SPO-8) | 2026-05-02 | Recovery: SPO-6 stalled-issue triage. |
| [SPO-9](/SPO/issues/SPO-9) | 2026-05-02 | Recovery: SPO-3 stalled-issue triage. |
| [SPO-3](/SPO/issues/SPO-3) | 2026-05-02 (cancelled) | Domain-model ADR — superseded after triage. |
| [SPO-5](/SPO/issues/SPO-5) | 2026-05-02 (cancelled) | Vendor spike: auth/KYC/geo — superseded. |
| [SPO-6](/SPO/issues/SPO-6) | 2026-05-02 (cancelled) | Senior backend engineer hire — superseded. |
| [SPO-7](/SPO/issues/SPO-7) | 2026-05-02 (cancelled) | Recovery: SPO-5 — superseded. |

---

## Owner action timeline (last 14 days, newest first)

| Time | Ticket | Action | Note |
|---|---|---|---|
| 2026-05-02T23:19Z | [SPO-11](/SPO/issues/SPO-11) | confirmation **accepted** (owner Eason via local-board) | Plan v3 accepted cleanly (no reject reason, no comment-vs-interaction conflict). FGM hypothesis implicitly confirmed (confirmation card explicitly asked). Phase 0 wrap. CTO opened [SPO-16](/SPO/issues/SPO-16) (Forge backend) at 23:26Z. |
| 2026-05-02T23:12Z | [SPO-11](/SPO/issues/SPO-11) | comment (owner Eason via local-board) | "可以直接執行計劃了" + (separately) reject reason on confirmation `f4fa39da`: "FTM (`player_frees_made`) + FGA (`player_field_goals`) 也要在phase 1做完". Mixed signal — interaction wins per CEO process note. CTO drafted plan v3 in response. |
| 2026-05-02T23:05Z | [SPO-11](/SPO/issues/SPO-11) | confirmation **rejected** (owner Eason via local-board) | Plan v2 rejected with reason locking FTM/FGA into Phase 1; resolved Q1 (3PA cut accepted), Q2 (Tier B in Phase 1), Q3 ("我之後會升級，現在你先不用管成本問題" → quota plan upgrade pre-approved). |
| 2026-05-02T23:08Z | [SPO-11](/SPO/issues/SPO-11) | CEO routing comment to Eason re plan v2 | New ask: Q3 budget pre-positioning — if Forge audit recommends plan-tier upgrade, what is Eason's monthly USD cap? Resolved by Eason at 23:05Z reject (pre-approved). |
| 2026-05-02T22:42Z | [SPO-12](/SPO/issues/SPO-12) | comment (owner Eason via local-board) | "the odds api 的 document其實是有FTM的，但是可能今天這場比賽剛好沒有。其他我看過都沒問題了，可以交接給 CTO執行計劃" — flagged FTM canonical key |
| 2026-05-02T20:43Z | [SPO-12](/SPO/issues/SPO-12) | comment (owner Eason via local-board) | Scout deliverable summary repost — research signed off |
| 2026-05-02T20:31Z | [SPO-11](/SPO/issues/SPO-11) | confirmation accepted (owner Eason via local-board) | Phase 0 plan v1 approved; CTO dispatched [SPO-12](/SPO/issues/SPO-12) (Scout) with quota-measurement spec |
| 2026-05-02T20:00Z | [SPO-10](/SPO/issues/SPO-10) | created (owner Eason) | event page 需 9 個新球員 stat type；先研究、再整合 API |

> Owner-created tickets are inferred from `originKind=manual` plus owner-authored description. Paperclip API does not expose a separate event stream, so this timeline is rebuilt from issue/comment timestamps each wake-up. Latest owner action: 23:12Z comment + 23:05Z confirmation reject (both on SPO-11).

---

## This-heartbeat note (CTO 2026-05-02T23:27Z, run on SPO-11 `issue_comment_mentioned` → Phase 2B dispatch)

Plan v3 was **accepted** by Eason at 23:19:44Z via confirmation `5fdd7a9d` (clean accept, no reject reason). CEO reassigned SPO-11 back to me with the 3-step next-action list. Executed all three:

1. **[SPO-16](/SPO/issues/SPO-16) created** — Forge backend Phase 2B parser-merge ticket. parent=SPO-10, assignee=Forge, status=todo. Description (12.8KB) covers: 8 new markets in `SUPPORTED_MARKETS`/`SNAPSHOT_MARKETS`/`odds_history` allow-list, DD binary parser as separate code path with `player_dd_history()` function, FTM/FGM graceful-degrade (empty-bookmakers returns null odds never fake numbers), FGM disambiguation integration test (`median(point) < 10` skip-on-empty), 3 projection-derived fields (`r_a`/`p_r`/`p_a`), 7 continuous + 1 binary csv metric, anti-hallucination guards verbatim from `CLAUDE.md § External API Wrappers`, explicit out-of-scope (no frontend, no Sentinel suite, no plan-tier negotiation, no DD ML projection, no 3PA/3PA-attempted/FGA-attempted).
2. **[SPO-15](/SPO/issues/SPO-15) description PATCHED** with v3 addendum at top (between STALE-SUMMARY banner and original spec). Audit no longer merge-gating per Q3 pre-approval; projection number bumped to 12 markets (was 10). Original spec body kept verbatim — Forge's audit work is identical, only the gating relationship changed.
3. **SPO-11 re-blocked** on [SPO-16](/SPO/issues/SPO-16) via `blockedByIssueIds`. SPO-15 is parallel, not in blockers. When SPO-16 closes, CTO wakes via `issue_blockers_resolved` → opens Subtask 4 (Forge frontend) and reblocks on it.

**Phase-gating preserved**: only Subtask 3 (Forge backend) opened. Subtasks 4/5/6 (frontend / Sentinel / Lens) NOT pre-created — sequential per phase-gate per `paperclip-converting-plans-to-tasks`.

**Watch-items for next wake:**
- Forge has 2 tickets in flight (SPO-15 + SPO-16). They time-slice; no hard ordering required.
- If SPO-15 audit reveals projected burn > 80% of plan limit, CTO pages CEO → CEO notifies Eason (Q3 pre-approved, no `request_confirmation`).
- If SPO-16's FGM disambiguation integration test fails (median ≥ 10 → `player_field_goals` is actually FGA-attempted not FGM), Forge escalates to CTO → plan v4 with new "historical-only / no API binding" UX class.
- Forge run `85fa491c` stale-summary recovery from 23:18Z note still relevant — if Forge's next run on SPO-15 shows stale text, file Paperclip wake-payload caching bug.

---

## How this file is maintained

CTO refreshes this whole file on **every wake-up** as the very first action. Source: Paperclip API ticket tree for company `5bf7dcb7-39df-4efd-bc96-e6397e18fd9d`.

- **Active epics**: tickets with `type=epic` and any descendant in `todo|in_progress|in_review`.
- **Phase tickets in flight**: any non-epic ticket in `todo|in_progress|in_review`.
- **Blocked / awaiting owner**: tickets with status `blocked` OR assigned to owner with status `in_review`.
- **Recently completed**: tickets closed within the last 7 days. Link to `docs/task-summaries/<TICKET>-<slug>.md` if it exists.
- **Owner action timeline**: paperclip ticket events filtered to `actor.type == "user"`, last 14 days, newest first. Action types: `assign`, `reassign` (with from→to), `status_change`, `comment`, `close`. The Note column truncates the owner's comment to ≤80 chars (`—` if no comment).

CTO does **not** edit this file's structure mid-flight — only the rows. If a section needs structural change, raise it in a paperclip ticket and apply explicitly.
