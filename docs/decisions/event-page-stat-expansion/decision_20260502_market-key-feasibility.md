# Decision — Market-key feasibility (Phase 1.5)

**Date:** 2026-05-02
**Author:** CTO ([SPO-14](/SPO/issues/SPO-14) — supersedes the duplicate [SPO-13](/SPO/issues/SPO-13) which is being cancelled)
**Epic:** event-page-stat-expansion (parent [SPO-10](/SPO/issues/SPO-10))
**Status:** proposed (gates plan v2 confirmation on [SPO-11](/SPO/issues/SPO-11#document-plan))
**Predecessor:** Scout research [SPO-12](/SPO/issues/SPO-12) (curl-evidenced, approved by Eason 2026-05-02T22:42Z)
**Predecessor decision:** [`decision_20260502_phase0-research-first-and-derive-strategy.md`](decision_20260502_phase0-research-first-and-derive-strategy.md)

---

## Context

Scout's research (`docs/research/event-page-stat-expansion/research_odds_api_markets.md`, post-correction 2026-05-02T22:42Z) curl-verified all 9 candidate NBA player-prop markets against The Odds API v4 with `event_id=a37e80a2e3cf3aaa3ae84a9124987058` and `event_id=be60e6f50fc77fc3a3cf6925472bad91`. Two findings drive this decision:

1. **Per-market billing confirmed** (Scout §2.4): `x-requests-last = N` where N = number of *populated* markets in URL. 5-market call charged 5 units. Empty-bookmakers and 422 INVALID_MARKET both charge 0. Branch B applies — plan v1's "9 markets without quota guardrail" assumption is invalid.
2. **9-market classification** (Scout §3 + §4.1):
   - 6 markets return `200 OK` with populated bookmakers (Tier A — hard-supported)
   - 2 markets return `200 OK` with `bookmakers: []` and 0-unit cost (Tier B — schema-valid but currently empty)
   - 1 market returns `422 INVALID_MARKET` on every plausible variant and is absent from the docs (Defer — no API contract)

This decision converts that evidence into an implementation-ready Phase 1 spec, sets the snapshot-cadence cost guardrail, and locks in the DD binary-parser requirement for Forge.

---

## Decision

### 1. Final market-key list with classification tier

| Stat | Canonical market key | Tier | Phase 1? | Outcome shape | Why |
|---|---|---|---|---|---|
| 3PM | `player_threes` | **A — hard-supported** | yes | Over/Under + `point` | curl 200 + populated; standard parser path |
| STL | `player_steals` | **A — hard-supported** | yes | Over/Under + `point` | curl 200 + populated; standard parser path |
| R+A | `player_rebounds_assists` | **A — hard-supported** | yes | Over/Under + `point` | curl 200 + populated; native combo line — **no derive math needed** (kills v1's vig-double-count concern) |
| P+R | `player_points_rebounds` | **A — hard-supported** | yes | Over/Under + `point` | curl 200 + populated; native combo line |
| P+A | `player_points_assists` | **A — hard-supported** | yes | Over/Under + `point` | curl 200 + populated; native combo line |
| DD | `player_double_double` | **A — hard-supported** | yes (with binary parser) | **Yes/No, no `point`** | curl 200 + populated; **outcome shape differs** — Forge needs binary-aware code path (§4) |
| FTM | `player_frees_made` | **B — graceful-degrade** | **no (deferred to Phase 2 monitoring window)** | Over/Under + `point` (when populated) | curl 200 + `bookmakers: []` × 2 events; 0-cost while empty; per Eason's 22:42Z note "the odds api 的 document其實是有 FTM 的" — schema-valid, just no inventory today |
| FGA | `player_field_goals` | **B — graceful-degrade** | **no (deferred to Phase 2 monitoring window)** | Over/Under + `point` (when populated) | curl 200 + `bookmakers: []`; 0-cost while empty; FGM-vs-FGA semantics ambiguous (likely FGM by docs convention — `player_frees_made`/`player_frees_attempts` analogy) — disambiguate from first populated response |
| 3PA | (none — not in The Odds API NBA market list per docs) | **Defer (no API path)** | **no (cut from Phase 1 selector entirely)** | n/a | All 3 plausible variants returned 422; docs cross-check confirmed absent. Distinct from FTM/FGA's "valid but empty" — no contract to graceful-degrade *from* |

**Net Phase 1 delta to `SUPPORTED_MARKETS`:** 4 → 10 (add 6 Tier-A keys). Tier B (FTM, FGA) explicitly NOT added in Phase 1.

### 2. Phase 1 scope decision: Tier A only

**Selected:** Tier A only (6 markets) for Phase 1. Defer Tier B (FTM, FGA) to a Phase 2 monitoring task. Defer 3PA entirely.

**Reasoning:**

- **Cleaner narrative.** "Ship 6 stat tiles that work end-to-end" is a story Eason can demo on day one. "Ship 8 tiles, 2 of which show 'no bookmaker line right now' indefinitely" is a story that erodes user trust in tile content even when the dimming is technically correct.
- **Phase-2-friendly promotion path.** Per-market billing (Scout §2.4) means adding Tier B later costs 0 units while bookmakers don't post inventory and N units when they do — there is **no quota cost** to deferring. The scheduled Phase 2 monitoring task (`[Sentinel] FTM/FGA inventory watchlist`) probes once weekly and pages CTO when ≥1 bookmaker populates either key for ≥3 consecutive probes; promotion to Tier A is then a one-config-list-line Forge ticket.
- **Sentinel + Lens budget.** Phase 1 with 6 Tier-A markets needs ~1 integration test (Yes-case live API hit) + 1 Lens review pass. Adding Tier B doubles the test matrix (populated-empty-state and populated-populated-state both must be covered) for marginal user value.
- **3PA cut is uncontroversial.** No API path means the only way to surface 3PA is "historical CSV + projection only, no bookmaker line ever" — a UX class we don't have anywhere else and would have to invent for one stat. Cheaper to omit and let Eason raise it again post-Phase-1 if needed (Phase 2 selector revamp covers it).

**Material change vs plan v1 (Eason must re-confirm):**

- v1 implied all 9 stats ship in Phase 1. v2 ships 6 (A) and explicitly defers 2 (B → Phase 2 monitoring) + 1 (3PA → cut).
- The combo `[derive-needed]` math (v1 §4.1 / Phase 0 decision §2) is **dead** — combos are native single keys, no backend sum, no vig-double-count concern. Scout §3.6 footnoted this. It's good news but it's a material change to plan v1's reasoning.
- DD moves from "Phase 2 deferred" to "Phase 1 Tier A with binary parser sub-task". Scope expansion within the Forge ticket; net Phase 1 stat count still goes up vs v1's "high-confidence 6 = 3PM/STL/FTM/R+A/P+R/P+A".

### 3. Snapshot cadence + Redis TTL guardrail (gates Forge merge)

**Current cadence (verified in `backend/app/services/scheduler.py:160-205`):**

- **3 odds snapshots/day** (UTC 16:05, 22:05, 23:35) via `_run_odds_snapshot_job` — each pulls all NBA events for the day and calls `/v4/sports/basketball_nba/events/{event_id}/odds?markets=<SNAPSHOT_MARKETS>` once per event.
- **`SNAPSHOT_MARKETS` = 4 markets today** (`player_points,player_rebounds,player_assists,player_points_rebounds_assists`) → 4 paid units per event per snapshot under the per-market billing model.
- **`hot_key_prewarm` job** runs every 30 seconds (`scheduler.py:206-212`) — its quota cost depends on how many keys are in the prewarm set; flagged for the Forge audit.
- Daily-analysis job runs at UTC 12:00 once per day; its quota cost is bundled into `daily_analysis.SUPPORTED_MARKETS` which is also being expanded.

**Quota-burn estimate (1 game day, conservative):**

| Cadence layer | Calls/day | Markets/call | Units/day @ 4-mkt | Units/day @ 10-mkt | Δ |
|---|---|---|---|---|---|
| Odds snapshot (3×/day × 10 events × 1 call/event) | 30 | 4 → 10 | 120 | 300 | +180 |
| Daily analysis (1×/day × 10 events × 1 call/event) | 10 | 4 → 10 | 40 | 100 | +60 |
| Hot-key prewarm (every 30s, scope TBD by audit) | ≤ 2880 | TBD | TBD | TBD | TBD — could be dominant |
| **Conservative known-job total / day** | — | — | **≥ 160** | **≥ 400** | **2.5×** |
| **Conservative monthly (game-day-weighted ~22 days)** | — | — | **≥ 3520** | **≥ 8800** | — |

The Odds API plan tier matters: if the running plan is the 500-unit free tier, current usage is already over-quota (Scout §4.2 noted `used` advanced 4 units between probes with no Scout-attributable calls — confirms a paid plan is in use). At Tier A merge, monthly burn rises to **≥ 2.5× current** depending on hot-key-prewarm scope. This is a `[Major]` cost regression per `CLAUDE.md § Domain Lenses` ("API rate-limit / cost-per-call: Budget per query > 1 cent is a `[Major]` cost regression").

**Decision:** Forge merge of any Tier-A `SUPPORTED_MARKETS` change is **gated** on completion of the snapshot-cadence + Redis-TTL audit, delivered as a separate Forge ticket whose acceptance criteria are:

1. **Quantified current burn**: Forge audits the actual past-month `x-requests-used` arc (from snapshot logs + `OddsGateway` counter) and reports current monthly burn against plan limit.
2. **Quantified post-merge burn**: Forge calculates projected burn under the 10-market `SNAPSHOT_MARKETS`, with an **explicit number** (not "approximately 2.5x").
3. **Cadence proposal**: if projected burn would exceed 80% of the current plan's monthly limit, Forge proposes ONE of:
   - drop one snapshot (e.g. retire `odds_snapshot_early` if early-line tracking has < 5% CLV signal vs mid+final)
   - tighten `hot_key_prewarm` scope (e.g. only prewarm Tier-A markets for the next 2 hours of game-time, not all keys forever)
   - upgrade plan tier (with Eason approval — costs USD/month)
4. **Sentinel sanity test**: a `@pytest.mark.integration` test that simulates a 1-week scheduler run against a mocked `time.time()` and asserts projected `x-requests-used` delta ≤ Forge's claimed number ± 5%. Gated behind `RUN_INTEGRATION=1`. Per `CLAUDE.md § External API Wrappers` rule #2, this test must hit live API at least once for a single Tier-A market to ground-truth the unit-per-call cost (Forge documents the actual quota burn of the Sentinel run itself).

**Why not just upgrade the plan and skip the audit?** Two reasons: (a) we don't yet know whether the current plan is being silently over-burned (Scout §6 "used advanced 4 units between probes with no Scout-attributable calls" suggests yes); (b) `hot_key_prewarm` running every 30 seconds is a dominant-cost candidate that no plan tier will outrun if it's mis-scoped — the audit is cheaper than buying more quota.

### 4. DD binary-handling requirement (Forge)

DD's outcome shape from Scout §3.9 differs from every other Phase 1 market:

```json
"outcomes": [
  {"name": "Yes", "description": "Jayson Tatum",   "price": -156},
  {"name": "Yes", "description": "Joel Embiid",    "price":  128},
  {"name": "Yes", "description": "Jaylen Brown",   "price":  265}
]
```

Three structural differences from Over/Under markets:
- `name = "Yes" | "No"` (binary), not `"Over" | "Under"`
- **No `point` field** — DD is binary, not threshold-based
- Often only `Yes` is posted (no `No` row); the implicit `No` price is derived from de-vigged `Yes`

**Forge contract (binding for the DD sub-ticket):**

1. **Parser path separation.** `OddsGateway` and `daily_analysis` must dispatch to a binary-aware parser when `market_key == "player_double_double"`. Reusing the `compute_over_probability` / Over-Under parser will silently produce `point=None` rows or worse, swallow DD entries.
2. **Historical estimator** (in `csv_player_history`):
   ```python
   def player_dd_history(player_name: str, season: str | None = None) -> dict:
       # P(DD = 1) = #games where ≥2 of {PTS, REB, AST, STL, BLK} ≥ 10 / total games
   ```
   Returns `{"prob_dd": float, "games": int, "dd_games": int}`. **Reject** any attempt to compute "P(DD ≥ threshold)" — DD is 0/1, threshold is meaningless.
3. **De-vigging single-leg lines.** When only `Yes` is posted, Forge computes implied `P(Yes)` via `american_to_prob`, then de-vigs by assuming the book's effective vig matches the league average for binary props (Forge: pull the vig estimator from `prob.py:devig`; if a `No` price IS posted, use it). **Do NOT publish a "fair probability" if vig cannot be estimated** — leave `over_fair_prob = None` and let the frontend render bookmaker-implied only.
4. **Frontend tile shape.** `MarketSelect.tsx` needs a third group ("Binary") separate from Single-Stat / Combo; the DD tile renders `Yes price + Yes implied probability + historical P(DD=1)` and labels `ML projection` as `N/A (Phase 2)` per Phase-0 decision §4.
5. **Test coverage** (Sentinel): one unit test for `player_dd_history` against a known CSV slice (e.g. Tatum 2024-25 with hand-counted DD-game count) and one integration test against live `player_double_double` to confirm the parser handles real Yes-only rows.

### 5. 3PA disposition: cut from Phase 1 selector

**Selected:** remove 3PA from the Phase 1 `MarketSelect` list entirely. No selector entry, no historical-only tile.

**Reasoning:**
- No API contract — confirmed via Scout §3.5 + docs cross-check (`player_threes` is in the docs, `player_threes_attempts` is not).
- Including 3PA as a "historical CSV + projection only" tile would invent a UX class for **one** stat — bad ROI on UX coherence (we don't have a precedent for "no bookmaker line ever — historical only" in the codebase, and creating one for one stat is over-engineering).
- 3PA usage in Sports Lab CSV ranks behind PTS, REB, AST, 3PM by ≥10× per existing query logs (Eason's prior usage, not telemetry-grounded — flagging for re-validation if Eason objects).
- If Eason wants 3PA back post-Phase-1, the path is a Phase 2 selector revamp ticket that would also surface FTM/FGA monitoring promotion. Bundling makes sense; one-off does not.

**If Eason overrides** (i.e. wants 3PA in Phase 1 selector): the override path is a static `MarketSelect` entry pointing at a backend route that returns `{odds: null, history: <CSV-derived>, projection: <SportsData FGA-distinct>}`. Forge can wire this up in ~1 heartbeat, but the UI must explicitly say "no live bookmaker line for this stat" with a permanent (not transient) tooltip — distinct from the Tier B "currently empty" wording.

### 6. `player_field_goals` semantics: defer disambiguation to Phase 2 monitoring

**Selected:** defer FGM-vs-FGA disambiguation. FGA is in Tier B (deferred to Phase 2 monitoring per §2 above), so the question doesn't need a Phase 1 answer.

**Reasoning:**
- Tier-A-only Phase 1 means `player_field_goals` does NOT enter `SUPPORTED_MARKETS` in Phase 1. The "is this FGM or FGA?" question is therefore not load-bearing on any Phase 1 deliverable.
- Scout's prior (FGM by docs convention — `player_frees_made`/`player_frees_attempts` analogy applies; bare `player_field_goals` is most likely "made") is plausible but unverified. Burning a curl unit today to confirm is wasteful when the first populated bookmaker response in the Phase 2 monitoring window will reveal the `point` distribution (FGM thresholds cluster 5–10, FGA cluster 10–20) for free.
- The Phase 2 Sentinel watchlist task (`[Sentinel] FTM/FGA inventory watchlist`, opened post-Phase-1) is the right place to record the disambiguation result and gate Tier-B promotion on it.

**Forge instruction:** when Forge eventually adds `player_field_goals` to `SUPPORTED_MARKETS` in Phase 2, the metric label MUST be derived from the watchlist's classification (`fgm` or `fga`), not hardcoded. If watchlist data is inconclusive after 14 days, escalate back to CTO with the populated-response samples for a fresh decision.

---

## Alternatives considered

### Alternative A1 — Phase 1 Tier A + B (8 markets, ship FTM/FGA behind graceful-degrade)

Rejected. Per §2 reasoning: Tier B costs 0 units while empty (no quota argument against), but the UX cost of indefinite "no bookmaker line right now" tiles is real. Defers cleanly to Phase 2 with no quota penalty.

### Alternative A2 — Phase 1 Tier A only, but ship 3PA as historical-only

Rejected. Inventing a UX class for one stat is over-engineering. If Eason wants it, Phase 2 selector revamp is the right home.

### Alternative B1 — Skip the snapshot cadence audit; just merge Tier A and watch quota in production

Rejected. `hot_key_prewarm` runs every 30s and could be the dominant cost line — no plan tier will outrun a mis-scoped prewarm. The audit is cheaper than buying more quota AND it's required by the `CLAUDE.md` Domain Lens cost-regression policy. Skipping it is a concrete `[Major]` regression risk.

### Alternative B2 — Move snapshot cadence audit to a post-Phase-1 hotfix ticket

Rejected. Cost regressions are easiest to fix before they hit production billing. Post-merge audits routinely get deprioritized when nothing is visibly broken.

### Alternative C1 — DD reuses Over/Under parser (treat `Yes/No` as `Over/Under` with implicit `point=0.5`)

Rejected. Misleading abstraction — `point` is a real number on the bookmaker side for Over/Under markets and there is no equivalent for DD. The de-vigging logic for binary single-leg markets is genuinely different from the two-leg de-vig used by `prob.py:devig` today (single-leg requires assuming a vig prior; two-leg derives vig from the leg pair). Forcing them through one path will produce wrong probabilities for DD and is an actual `[Major]` correctness bug, not a stylistic concern.

### Alternative C2 — Defer DD to Phase 2 (revert Scout's tier-A promotion)

Rejected. The original Phase 0 decision had DD in "Phase 2 deferred" because of low confidence in API support. Scout's curl confirmed DD IS direct-supported (against the "low" prior). Pulling DD out now wastes the research finding AND ships a Phase 1 that Eason will read as "we kept the easy ones and dropped the hard one." The Forge cost is one extra binary parser path, not a multi-week effort.

---

## Impact

- **Phase 2 (Forge backend)** scope is now: snapshot cadence audit (gating) → Tier A `SUPPORTED_MARKETS` parser (5 standard markets) → DD binary parser (separate code path). 3 sub-tickets, of which only the audit can start before Eason confirms plan v2.
- **Phase 3 (Forge frontend)** unchanged in shape from v1; concrete delta is a `Binary` selector group for DD plus removing 3PA from the static list.
- **Phase 4 (Sentinel)** gains the cadence-audit sanity test (1-week mocked clock) and the binary-parser live integration test. Test count: 3-4 new `@pytest.mark.integration` tests (was 1 in v1).
- **Phase 5 (Lens)** unchanged in shape.
- **Phase 6 (CTO follow-up)** gains a Phase 2 Sentinel watchlist task for FTM/FGA inventory monitoring, opened immediately after Phase-1 Lens close.

**Total**: Phase 2 effort is now 3-4 heartbeats (was 2-3 in v1) due to audit + DD binary; Phase 4 is 2-3 heartbeats (was 1-2). Net epic estimate: 9-11 heartbeats from plan v2 confirmation to SPO-10 done (was 7-9 in v1).

---

## Links

- Scout research: `docs/research/event-page-stat-expansion/research_odds_api_markets.md`
- Scout exploration script (re-runnable): `scripts/explore_odds_api_extensions.py`
- Scout task summary: `docs/task-summaries/SPO-12-odds-api-9-markets-research.md`
- Phase 0 decision: [`decision_20260502_phase0-research-first-and-derive-strategy.md`](decision_20260502_phase0-research-first-and-derive-strategy.md)
- Plan v1: [SPO-11 plan revision pre-2026-05-02T23:00Z](/SPO/issues/SPO-11#document-plan)
- Anti-hallucination policy: `CLAUDE.md § External API Wrappers` (rules #1-#4)
- Existing 4-market baseline: `backend/app/services/odds_snapshot_service.py:45`, `backend/app/services/daily_analysis.py:41-46`
- Scheduler cadence reference: `backend/app/services/scheduler.py:160-212` (3 daily snapshots + 30s hot-key prewarm)
- Domain Lens (cost regression policy): `CLAUDE.md § Domain Lenses` ("API rate-limit / cost-per-call")

---

## Addendum 1 — Board override (2026-05-02T23:05Z): FTM/FGA pulled into Phase 1; quota plan upgrade pre-approved

**Trigger**: Eason rejected confirmation `f4fa39da-6ccb-4154-b460-21b93032dc50` (bound to plan v2 revision `0bc07525`) at 2026-05-02T23:05Z via `local-board`. Reject reason (verbatim, source-of-truth):

> FTM (`player_frees_made`) + FGA (`player_field_goals`) 也要在phase 1做完

CEO's routing comment (`488700ec`) integrated this with Eason's adjacent comment 「我之後會升級，現在你先不用管成本問題」 and the Q1 acceptance into a single 3-question resolution. This addendum locks those overrides into the decision record.

### Override 1 — Tier B (FTM, FGA) pulled into Phase 1

**Reverses**: §2 selection ("Phase 1 = Tier A only, defer Tier B to Phase 2 monitoring"). Was justified on UX-narrative grounds; board explicitly rejects that justification.

**New decision**: `player_frees_made` (FTM) and `player_field_goals` (FGA) **enter `SUPPORTED_MARKETS` in Phase 1**. Tier-B → Tier-A promotion is immediate, not gated on a monitoring window.

**UX path** (this is the change that drops out of the override): the original plan v1 §3 graceful-degrade UX is restored — selector renders FTM and FGA tiles like any other; the odds panel renders bookmaker line if `bookmakers != []`, otherwise renders a "no bookmaker line right now — historical + projection only" state per the existing graceful-degrade convention from `decision_20260502_phase0-research-first-and-derive-strategy.md` §3. Tier-B tiles MUST distinguish "currently empty" from "broken" — text reads as state, not error. No fabricated O/U thresholds (anti-hallucination).

**Why §2's "uncontroversial cut" reasoning loses**: I framed the cut as "cleaner narrative" + "doubled test matrix" + "easier to validate." Board read the same evidence and said: completeness against the original 9-stat ask matters more than narrative cleanliness; per-market billing means Tier-B is free while empty (Scout §2.4 confirmed); empty-state tile is not a UX bug, just a state to render correctly. Both views are coherent — board's call wins. The override is not a research surprise, it is a product judgment call where board has authority.

**Forge implication**: backend ticket adds 2 entries to `SUPPORTED_MARKETS` (`player_frees_made` → `ftm`, `player_field_goals` → `fgm` — see Override 3 on FGM-vs-FGA disambiguation). Frontend ticket adds 2 entries to `MARKETS` array under the Single group, plus the empty-bookmakers tile state handling that v2 had punted to Phase 2.

### Override 2 — Quota plan upgrade pre-approved (Q3)

**Reverses**: §3 "Forge merge of any Tier-A `SUPPORTED_MARKETS` change is **gated** on completion of the snapshot-cadence + Redis-TTL audit" (specifically the merge-gate aspect, NOT the audit itself).

**New decision**: the quota-burn audit (§3 steps 1-4) **still runs as the first sub-task of Forge backend** (engineering hygiene, ground-truth on actual cost), but it is **no longer a hard pre-merge gate**. If the audit reports projected monthly burn >80% of plan cap, the prescribed action is:

1. CTO posts the audit numbers + recommended action in the SPO-11 thread (or its successor)
2. CEO is paged, takes the upgrade decision to Eason as a heads-up — NOT a `request_confirmation` round
3. Forge proceeds to merge in parallel; plan upgrade is a billing op that doesn't gate technical merge

**Why this safer-by-default removal works**: Eason said 「現在你先不用管成本問題」 — that's an explicit pre-approval of "spend whatever it takes for Phase 1 plan-tier compliance, don't open another `request_confirmation` for it." Without that pre-approval the audit gate was correct (cost regressions are easiest to fix before they hit billing); with it, the gate becomes pure friction.

**Audit STILL runs** because: (a) `hot_key_prewarm` running every 30s is still a dominant-cost candidate that no plan tier outruns if mis-scoped — fixing scope is cheaper than buying quota; (b) the `[Major]` cost-regression Domain Lens policy still requires quantification; (c) when CTO eventually pages Eason for the plan upgrade, an audit-derived number ("we need plan tier $80/month, not $20") makes the conversation crisp.

### Override 3 — `player_field_goals` semantics: needs upfront resolution (was: defer to Phase 2 watchlist)

**Reverses**: §6 "defer FGM-vs-FGA disambiguation. FGA is in Tier B (deferred to Phase 2 monitoring)." Tier B is no longer deferred per Override 1, so the disambiguation deferral is invalid.

**New decision**: Forge backend treats `player_field_goals` as **`fgm`** (field goals made) by working hypothesis, on three grounds:
1. The Odds API docs convention uses the `_attempts` suffix for "attempted" markets (e.g. `player_frees_attempts` for FTA). Bare `player_field_goals` is the made-side analogue of bare `player_frees_made`'s "made" stem — likely FGM.
2. When a populated response eventually arrives, the `point` distribution will be ground-truth: FGM thresholds cluster 5-10, FGA cluster 10-20. Forge must add a `RUN_INTEGRATION=1` check that on the first populated `player_field_goals` response, asserts the median `point` is < 10 (FGM signature). If the assertion fails, escalate to CTO.
3. This means the Phase 1 selector ships **FGM, not FGA** — Eason's reject reason said "FGA" but the actual market key is `player_field_goals` and the docs analogy points to FGM. CEO's routing comment used "FGA (`player_field_goals`)" inline; CTO needs to call this out in the v3 plan and the new `request_confirmation` so Eason isn't blindsided. This may itself trigger another `request_confirmation` round if Eason actually wanted FGA-attempted (which has no API contract) and not FGM.

**If Eason actually wanted FGA-attempted**: there is no API path. The historical-only "no bookmaker line ever" UX class would have to be invented for that one stat, same trap §5 of this decision rejected for 3PA. CTO will surface this risk in the plan v3 confirmation card so Eason can clarify before approval.

### Process note (file under "lessons" for CTO future-self)

Eason's comment ("可以直接執行計劃了") and the `request_confirmation` API result (rejected + reason) were mixed signals. The `request_confirmation` API result is binding (CEO's process note in the routing comment, codified). When this happens again, CTO MUST NOT auto-reconcile — surface the contradiction back to the board via a comment + new confirmation rather than picking one interpretation unilaterally. Plan v3 + new confirmation is exactly that surfacing.

### Net Phase 1 scope after addendum

| Tier | Markets in Phase 1 | Count |
|---|---|---|
| A — hard-supported (populated today) | 3PM, STL, R+A, P+R, P+A, DD | 6 |
| Tier-A-by-board-override (schema-valid + currently empty, graceful-degrade UX) | FTM (`player_frees_made`), FGA-as-FGM (`player_field_goals`) | 2 |
| Cut from selector | 3PA | (1) |
| **Phase 1 total `SUPPORTED_MARKETS` delta** | 4 → **12** (was 4 → 10 in v2) | — |

Forge backend / frontend / Sentinel test-matrix all expand by 2 markets vs v2. Audit math in §3 also bumps: 4-market baseline → 12-market post-merge ≈ 3.0× burn (was 2.5× in v2). Audit still runs but does not merge-gate.

### Forge contract delta (binding for Phase 2 ticket spec)

Plan v3's Subtask 2 (Forge backend) ticket spec MUST include:
1. Add `("player_frees_made", "ftm")` and `("player_field_goals", "fgm")` to `SUPPORTED_MARKETS` and `SNAPSHOT_MARKETS`
2. Empty-bookmakers tile rendering path on the frontend (`PlayerHistoryStats.tsx` and `MarketSelect.tsx`) — text wording: "no bookmaker line right now — historical + projection only" (see Override 1 above)
3. `csv_player_history.get_player_stats()` metric supports new metrics `ftm` and `fgm` (column names exist in CSV: `FTM`, `FGM`)
4. `projection_provider.normalize_projection()` exposes `free_throws_made` and `field_goals_made` already (FIELD_MAPPING has them) — no Forge change needed there, just verify the keys are surfaced in the projection response
5. Quota audit runs as Subtask 2's first step; CTO receives audit doc; if projected burn >80% of plan limit, CTO pages Eason for plan upgrade out-of-band (no `request_confirmation` round)
6. Integration test (`RUN_INTEGRATION=1`) probes `player_field_goals` once on a populated response, asserts median `point` < 10 (FGM signature); fails CI loud if FGA-pattern detected — see Override 3
