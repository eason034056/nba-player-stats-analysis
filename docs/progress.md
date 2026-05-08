# Sports Lab Progress

> Maintained by CTO. Last refresh: **2026-05-08T08:24Z** (heartbeat: SPO-24 `issue_assigned` — Lens APPROVED test-prob English-regex fix → CTO reassigning to owner (CEO triage → Eason) for squash-merge to `dev`; CTO does NOT push/merge per role). Prior refreshes: 2026-05-08T08:14Z (SPO-27 productivity review closed as productive); 06:11Z (Phase 3 done, Phase 3.5 SPO-26 opened); 01:56Z (Phase 3 dispatch — file later reverted to 01:18Z snapshot); 01:18Z (SPO-15 closed); 2026-05-03T02:59Z–02:38Z (SPO-16 Lens APPROVED chain); 2026-05-02T23:27Z (SPO-11 v3 accept → SPO-16 dispatch); 23:20Z (plan v3 + Addendum 1).
> Source of truth: Paperclip API. This file is a snapshot — when in doubt, query paperclip directly.

---

## Active epics

| Epic | Current phase | Status | Assignee | Updated |
|---|---|---|---|---|
| [SPO-10 — State type increment](/SPO/issues/SPO-10) (擴充 event page 球員 prop stat types: 3PM/R+A/P+R/P+A/DD/STL/FTM/FGM) | **Phase 3.5 in review.** Phase 0/1/1.5/2A/2B/3 closed; SPO-20 squash-merged at 06:07Z (PR #3, merge `e36cb57`). **Phase 3.5 ([SPO-26](/SPO/issues/SPO-26))** Forge → `in_review` at 06:27Z (Lens to verify backend API-route 12-metric expansion + `/player-dd-history` + `/props/no-vig` DD branch). Phase 4 (Sentinel) and Phase 5 (Lens-final) deferred until SPO-26 closes. | blocked | CEO (held) | 2026-05-08T08:24Z |

---

## Phase tickets in flight

| Ticket | Title | Phase | Status | Assignee | Branch |
|---|---|---|---|---|---|
| [SPO-11](/SPO/issues/SPO-11) | [CTO] SPO-10 規劃: 擴充 event page 球員 prop stat types | Phase orchestrator. v1 ✅; v2 ❌; **v3 ✅ 23:19:44Z**. Monitoring Phase 3.5; blocked on [SPO-26](/SPO/issues/SPO-26). | blocked (`blockedBy=[SPO-26]`) | CTO | _(no code branch — orchestrator only)_ |
| [SPO-26](/SPO/issues/SPO-26) | [Forge] SPO-10 Phase 3 backend gap: API route 12-metric expansion + /player-dd-history + /props/no-vig DD branch | Phase 3.5 implementation. Forge complete; Lens review pending. | in_review | Forge (held; Lens picks up review) | `feature/SPO-26-backend-route-12metric-expansion` |
| [SPO-21](/SPO/issues/SPO-21) | [Sentinel] Triage 7 pre-existing backend test failures + 3 collection errors | Out-of-epic hygiene. Blocked on its own SPO-24/SPO-25 (SPO-22/23 already closed). SPO-25 closed 08:18Z; SPO-24 awaiting owner squash-merge. Will fully unblock when SPO-24 closes. | blocked | Sentinel | _(triage only — no branch)_ |
| [SPO-24](/SPO/issues/SPO-24) | [Forge] Update test_prob.py regexes to match English error messages | Sub-ticket of SPO-21. Forge complete on `feature/SPO-24-test-prob-english-regex` (commit `d8f211f`, 25/25 tests pass, prod `prob.py` untouched). **Lens APPROVED 08:22Z** — branch base `35a25dd` is two commits behind `origin/dev` (`e36cb57`) but `git log 35a25dd..origin/dev -- backend/tests/test_prob.py backend/app/services/prob.py` is empty → squash-merge will be conflict-free. **THIS HEARTBEAT (08:24Z):** CTO reassigning to CEO (`in_review`) for owner Eason's squash-merge to `dev` (conventional prefix `fix(test):`). | in_review | CEO (held; awaiting Eason squash-merge) | `feature/SPO-24-test-prob-english-regex` (local, commit `d8f211f`) |

---

## Blocked / awaiting owner

| Ticket | Blocker | Action needed |
|---|---|---|
| [SPO-24](/SPO/issues/SPO-24) | Lens APPROVED, ready to merge. CTO cannot push/merge per role. | **Owner Eason: squash-merge `feature/SPO-24-test-prob-english-regex` (commit `d8f211f`) into `dev` with conventional prefix `fix(test):`, then close SPO-24 as `done`.** Closing SPO-24 also auto-resolves [SPO-21](/SPO/issues/SPO-21)'s last blocker → Sentinel triage closure unblocks. |
| [SPO-10](/SPO/issues/SPO-10) | Phase 3.5 in review ([SPO-26](/SPO/issues/SPO-26)). Epic stays blocked until Phase 5 (Lens-final) closes — by design. | None for owner now. CTO auto-wakes on SPO-26 close → opens Phase 4 (Sentinel). |
| [SPO-11](/SPO/issues/SPO-11) | Blocked on [SPO-26](/SPO/issues/SPO-26). Plan v3 accepted; CTO is phase orchestrator monitoring only. | None for owner. CTO auto-wakes on SPO-26 close. |

---

## Recently completed (last 7 days)

| Ticket | Closed | Summary doc |
|---|---|---|
| [SPO-25](/SPO/issues/SPO-25) | 2026-05-08T08:18Z (closed) | Forge content-based reason assertions for `test_agent_chat.py`. Sub-ticket of SPO-21 closed cleanly after Forge handoff nudge. |
| [SPO-27](/SPO/issues/SPO-27) | 2026-05-08T08:20Z (closed) | Productivity review for SPO-24. Manager decision: productive — 6h timer was stale-status artifact (Forge→Lens assignee PATCH missed at run-exit due to branch-thrash), not actual churn. |
| [SPO-28](/SPO/issues/SPO-28) | 2026-05-08T08:13Z (closed) | Productivity review for SPO-25. Same playbook as SPO-27. |
| [SPO-23](/SPO/issues/SPO-23) | 2026-05-08T02:31Z (closed) | Forge sys.path fix recovered after branch-thrash; task summary committed at `154cc64` (visible on `origin/dev`). Forge→Lens handoff worked correctly here. |
| [SPO-22](/SPO/issues/SPO-22) | 2026-05-08T02:18Z (closed) | Forge sys.path off-by-one fix; superseded operationally by SPO-23. |
| [SPO-20](/SPO/issues/SPO-20) | 2026-05-08T06:09Z (closed by CEO) | Phase 3 Forge frontend: 12-tile `MarketSelect` w/ Single/Combo/Binary visual grouping; `PlayerDDTile.tsx` (NEW); `lib/schemas.ts` extended w/ `r_a/p_r/p_a` (NOT `dd` — anti-hallucination guard intact); FTM/FGM empty-bookmakers UX; 39/39 tests pass, `tsc` clean, lint clean. Eason squash-merged 06:07Z (PR #3, merge `e36cb57`). Discovered backend API-layer gap → spawned [SPO-26](/SPO/issues/SPO-26). |
| [SPO-18](/SPO/issues/SPO-18) | 2026-05-08T02:07Z (closed) | Tail polish on Phase 2B: dispatcher hardening; `# pragma: SPO-18 follow-up` grep marker; `single_leg_devig` docstring rounding fix. Commits `5ff02e2` + `257591a` landed in `dev` via the post-SPO-16 squash-merge `35a25dd`. |
| [SPO-16](/SPO/issues/SPO-16) | 2026-05-08T01:50Z (squash-merged + closed) | Phase 2B backend services: 8 new markets, DD binary parser, FTM/FGM empty handling, FGM disambiguation integration test, derived projection fields. Lens MUST FIX → SPO-17. **Gap discovered post-merge** → SPO-26. Branch squash-merged to `dev` (merge `35a25dd`). |
| [SPO-15](/SPO/issues/SPO-15) | 2026-05-08 (closed by CEO) | Forge Phase 2A audit: live ground-truth = 500/mo free tier; current 4-mkt scheduler-bound burn = **3 520/mo** (7.04× free); 12-mkt post-merge worst-case = **10 560/mo** (21.1× free). Plan-tier upgrade and `ODDS_API_KEY` rotation on Eason's plate (Q3 pre-approved). |
| [SPO-19](/SPO/issues/SPO-19) | 2026-05-03 (auto-resolved) | Productivity review for SPO-15; auto-closed at 08:55Z when SPO-15 progressed. |
| [SPO-17](/SPO/issues/SPO-17) | 2026-05-03 | Forge must-fix for SPO-16: `ra→r_a`, `pr→p_r`, `pa→p_a` aliases; positive walking-coverage test. Lens re-review APPROVED. |
| [SPO-12](/SPO/issues/SPO-12) | 2026-05-02 | Scout: research The Odds API NBA player props 9 candidate markets. 6/9 hard-supported, 2/9 schema-valid+empty (FTM/FGM), 1/9 not in schema (3PA). |
| [SPO-13](/SPO/issues/SPO-13) | 2026-05-02 (cancelled by CEO) | Scout-created CTO follow-up duplicate. |
| [SPO-14](/SPO/issues/SPO-14) | 2026-05-02 (cancelled by CEO) | Exact duplicate of SPO-13. |
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
| 2026-05-08T06:07Z | [SPO-20](/SPO/issues/SPO-20) | **squash-merge** (owner Eason via GitHub PR #3, merge `e36cb57`) | "merged SPO-20 到 dev了" — Phase 3 frontend landed in `dev`. |
| 2026-05-08T02:50Z | [SPO-20](/SPO/issues/SPO-20) | comment "現在完成了哪些事情，我現在要做什麼" (owner Eason via local-board) | Eason asked CEO for status. CEO answered with full Phase 3 deliverable summary + flagged backend API-layer gap. |
| 2026-05-08T~01:54Z | [SPO-16](/SPO/issues/SPO-16) | **squash-merge** (owner Eason via GitHub) | Eason squash-merged `feature/SPO-18-spo16-followup-polish` PR #1 into `origin/dev` (merge `35a25dd`). |
| 2026-05-08T01:14Z | [SPO-15](/SPO/issues/SPO-15) | comment **ack** (owner Eason via local-board) | Eason ack'd CEO's plan-tier upgrade heads-up — comment `5adb0bec`. |
| 2026-05-03T08:55Z | [SPO-19](/SPO/issues/SPO-19) | auto-resolved | System-authored productivity review (not Eason). |
| 2026-05-03T02:34Z | [SPO-16](/SPO/issues/SPO-16) | comment via local-board (Lens reviewer agent posting on board persona) | "APPROVED — must-fix verified, ready for CTO sign-off + squash-merge". |
| 2026-05-02T23:32Z | [SPO-15](/SPO/issues/SPO-15) | comment via local-board (Forge audit deliverable handoff) | "SPO-15 audit complete — handed off to CTO for Override 2 action". |
| 2026-05-02T23:19Z | [SPO-11](/SPO/issues/SPO-11) | confirmation **accepted** (owner Eason via local-board) | Plan v3 accepted cleanly. |
| 2026-05-02T23:12Z | [SPO-11](/SPO/issues/SPO-11) | comment (owner Eason via local-board) | "可以直接執行計劃了" + reject reason on confirmation `f4fa39da`: "FTM + FGA 也要在phase 1做完". |
| 2026-05-02T23:05Z | [SPO-11](/SPO/issues/SPO-11) | confirmation **rejected** (owner Eason via local-board) | Plan v2 rejected; FTM/FGA into Phase 1; Q3 plan upgrade pre-approved. |
| 2026-05-02T22:42Z | [SPO-12](/SPO/issues/SPO-12) | comment (owner Eason via local-board) | Flagged FTM canonical key. |
| 2026-05-02T20:43Z | [SPO-12](/SPO/issues/SPO-12) | comment (owner Eason via local-board) | Scout deliverable summary repost — research signed off. |
| 2026-05-02T20:31Z | [SPO-11](/SPO/issues/SPO-11) | confirmation accepted (owner Eason via local-board) | Phase 0 plan v1 approved. |
| 2026-05-02T20:00Z | [SPO-10](/SPO/issues/SPO-10) | created (owner Eason) | event page 需 9 個新球員 stat type；先研究、再整合 API. |

> Owner-created tickets are inferred from `originKind=manual` plus owner-authored description. Latest **Eason-authored** action: 2026-05-08T06:07Z SPO-20 squash-merge.

---

## This-heartbeat note (CTO 2026-05-08T08:24Z, run on SPO-24 `issue_assigned` wake — Lens APPROVED handoff)

Lens posted approval comment `d07da26b-…` at 08:22:53Z and reassigned [SPO-24](/SPO/issues/SPO-24) to CTO with status `in_review` for "squash-merge to dev". Lens's evidence:

- Diff: 4 lines in `backend/tests/test_prob.py` (2 regex literals) + 1 new task summary doc (`docs/task-summaries/SPO-24-test-prob-english-regex.md`). Production `backend/app/services/prob.py` **untouched** per acceptance criteria (`git show --stat d8f211f` confirms).
- Strings exact-match production: `prob.py:36` `"Odds cannot be 0"` ↔ test regex `"Odds cannot be 0"` ✓; `prob.py:103` `"Total probability cannot be 0"` ↔ test regex `"Total probability cannot be 0"` ✓.
- Test execution local (`backend/.venv`, py3.13): 2/2 targeted PASS, 25/25 full `test_prob.py` PASS — no regressions.
- Branch base `35a25dd` is two commits behind `origin/dev` (`e36cb57`); `git log 35a25dd..origin/dev -- backend/tests/test_prob.py backend/app/services/prob.py` is empty → squash-merge will be conflict-free.

**CTO role boundary (refresher for future me):** AGENTS.md is explicit — *"You do NOT push, merge, or open PRs. Owner handles all remote git actions."* So Lens's "handoff for squash-merge" lands on me as a routing decision, not an execution one. The right action is to forward to the owner (Eason) via CEO triage, exactly the same handoff pattern used at every prior phase merge (SPO-16 `35a25dd`, SPO-20 `e36cb57`).

**CTO actions this heartbeat:**
- `progress.md` refreshed (this file) — moved SPO-25/27/28 to Recently Completed; updated SPO-24 row to `in_review` / CEO-held; updated SPO-21 row to reflect "only SPO-24 left"; added SPO-24 to Blocked/awaiting owner with the explicit owner action.
- Reassigning [SPO-24](/SPO/issues/SPO-24) to CEO `27970cac-…` with `status=in_review` for owner Eason's squash-merge to `dev` (conventional prefix `fix(test):` per ticket's branching note).
- Posting closing comment on SPO-24 documenting Lens approval + the explicit owner action + downstream cascade (SPO-24 done → SPO-21 unblocks).

**Decision-log policy check:** No new architectural / library / external-API choice was made this heartbeat — the only "decision" was the routing one (Lens→CTO→CEO/owner), which is mechanical role enforcement, not a design call. So no new entry under `docs/decisions/<epic>/` is required per AGENTS.md output bar.

**Watch-items for next wake:**
- SPO-24 close — once Eason squash-merges, expect CEO to close as `done`. That auto-resolves SPO-21's last blocker (`issue_blockers_resolved` wake to Sentinel) — Sentinel can then close out the SPO-21 triage epic.
- SPO-26 review by Lens — when Lens approves, CTO reassigns to CEO/owner for squash-merge. When SPO-26 lands in `dev`, CTO auto-wakes (children-completed on SPO-11) and opens Phase 4 (Sentinel) on the SPO-10 epic.
- FGM disambiguation integration test still wired and waiting for first populated `player_field_goals` response.
- Audit §7 follow-ups remain registered for post-SPO-10-close.

**Pre-existing dirty working-tree note:** the repo at `/Users/wuyusen/Documents/bet` is on branch `feature/SPO-26-backend-route-12metric-expansion` with uncommitted edits (this `progress.md` from prior heartbeat + `frontend/package-lock.json`) and two untracked task-summary files (`SPO-20-frontend-stat-expansion.md`, `SPO-21-test-suite-triage.md`). Those are NOT mine to touch this heartbeat — they pre-date this wake. Owner / appropriate IC will reconcile when SPO-26 merges.

---

## Earlier-heartbeat notes

Prior heartbeat narratives (2026-05-08T06:11Z Phase 3 close + Phase 3.5 spawn; 02:54Z SPO-18 timing-race + rebase decision; 02:46Z SPO-15 Override 2 routing) are preserved in the git history of this file's commits / stashes. Trim live document to current heartbeat + watch-items only.

---

## How this file is maintained

CTO refreshes this whole file on **every wake-up** as the very first action. Source: Paperclip API ticket tree for company `5bf7dcb7-39df-4efd-bc96-e6397e18fd9d`.

- **Active epics**: tickets with `type=epic` and any descendant in `todo|in_progress|in_review`.
- **Phase tickets in flight**: any non-epic ticket in `todo|in_progress|in_review`.
- **Blocked / awaiting owner**: tickets with status `blocked` OR assigned to owner with status `in_review`.
- **Recently completed**: tickets closed within the last 7 days. Link to `docs/task-summaries/<TICKET>-<slug>.md` if it exists.
- **Owner action timeline**: paperclip ticket events filtered to `actor.type == "user"`, last 14 days, newest first. Action types: `assign`, `reassign` (with from→to), `status_change`, `comment`, `close`. The Note column truncates the owner's comment to ≤80 chars (`—` if no comment) and disambiguates `local-board` author identity (Eason vs reviewer agents posting through the board shim) when relevant.

CTO does **not** edit this file's structure mid-flight — only the rows. If a section needs structural change, raise it in a paperclip ticket and apply explicitly.
