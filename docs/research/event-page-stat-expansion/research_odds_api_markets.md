# Research — The Odds API NBA player-prop markets (9 candidate stat types)

**Date:** 2026-05-02
**Author:** Scout (paperclip dev agent)
**Ticket:** [SPO-12](/SPO/issues/SPO-12) — Phase 1 of [SPO-10](/SPO/issues/SPO-10) (event-page-stat-expansion)
**Spec source:** [SPO-11 plan §5.1](/SPO/issues/SPO-11#document-plan) + `docs/decisions/event-page-stat-expansion/decision_20260502_phase0-research-first-and-derive-strategy.md` Addendum 1 (CEO quota-measurement requirement)

---

## TL;DR for CTO

| | Result |
|---|---|
| **Billing model** | **Per-market** — `x-requests-last` = N (where N = number of *populated* markets in URL). Empty-bookmakers and 422 responses cost 0. |
| **Direct-supported (200 + populated bookmakers)** | **6/9** — 3PM (`player_threes`), STL (`player_steals`), R+A (`player_rebounds_assists`), P+R (`player_points_rebounds`), P+A (`player_points_assists`), DD (`player_double_double`) |
| **Schema-valid but currently empty (200 + `bookmakers:[]`, 0-cost probe)** | **2/9** — FTM (`player_frees_made`)¹, FGA (`player_field_goals`, FGM-vs-FGA ambiguous) |
| **Not in The Odds API schema (422 INVALID_MARKET on every plausible variant)** | **1/9** — 3PA (no `_attempted` variant exists per the docs' market-keys list) |
| **Combo derive needed?** | **No.** All 3 combo markets (R+A, P+R, P+A) are natively supported as single market keys. The "vig double-counting" concern in SPO-11 plan §3.2 is moot — we get one bookmaker line per combo, no backend math required. |
| **Phase 1 scope recommendation (per §3.2 branch B)** | **Tier A (6 hard-supported):** 3PM, STL, R+A, P+R, P+A, DD — full bookmaker line. **Tier B (2 graceful-degrade, CTO call):** FTM, FGA — schema-valid, currently empty; if shipped, frontend renders "no bookmaker line — historical + projection only" per `decision_20260502_phase0-research-first-and-derive-strategy.md` §3. **Defer (1):** 3PA — not in API schema. |
| **Quota cost of session** | 11 paid units in initial probe (used 25 → 36); 0 paid units in the 2026-05-02 post-review re-probe of `player_frees_made` (both probes returned empty bookmakers). Final: used 40 / remaining 460 of 500. |

¹ **Correction posted 2026-05-02 22:42 UTC** (Eason): the original research had FTM as `[not-available]` after 3 variants 422'd. None of the 3 was the canonical key. The Odds API docs at `the-odds-api.com/sports-odds-data/betting-markets.html` list `player_frees_made` (and `player_frees_attempts`) — both use "frees" not "free_throws". Re-probe of `player_frees_made` on 2 separate live event_ids confirms HTTP 200 + `bookmakers:[]` + 0-unit cost — same "schema-valid no current inventory" pattern as `player_field_goals` had. See §3.3 below for full evidence.

### What changed vs CTO's templated Phase 1 list ("3PM, STL, FTM, R+A, P+R, P+A")

- **Right (5/6):** STL, 3PM, R+A, P+R, P+A.
- **FTM** — schema-valid but currently empty inventory. CTO must decide: ship in Phase 1's graceful-degrade tier, or defer to Phase 2 until bookmakers post lines. Both options are technically clean (no half-broken UI risk either way) — it's a UX call.
- **DD missed by template** — IS direct-supported despite low CTO confidence. Should be in Phase 1's hard-supported tier with a binary-aware parser sub-task (different outcome shape — see §3.9).

---

## 1. Test environment

- **Date / time:** 2026-05-02, ~20:35 UTC (during today's NBA window — Celtics @ 76ers tips at 23:40 UTC)
- **API version:** The Odds API v4
- **Sport key:** `basketball_nba`
- **Live event_id used:** `a37e80a2e3cf3aaa3ae84a9124987058` (Boston Celtics vs Philadelphia 76ers, `commence_time=2026-05-02T23:40:00Z`)
- **Regions:** `us`
- **Odds format:** `american`
- **Starting quota:** `x-requests-used=25`, `x-requests-remaining=475`
- **Tooling:** raw `curl` against the live endpoint, plus the new `scripts/explore_odds_api_extensions.py` (re-runnable). Per `CLAUDE.md § External API Wrappers` rule #1, the script is now the ground-truth reference for Forge.

`/v4/sports` and `/v4/sports/<sport>/events` both returned `x-requests-last: 0` — they do not count against quota and are safe to use as free spacers / event pickers.

---

## 2. Quota measurement (Addendum 1, MUST-DO)

Procedure exactly as specified in `docs/decisions/event-page-stat-expansion/decision_20260502_phase0-research-first-and-derive-strategy.md` Addendum 1: single-market call → free spacer → multi-market call, with header capture between each.

### 2.1 Single-market call

```
curl -sS -D /tmp/h_a.txt \
  "$ODDS_API_BASE_URL/v4/sports/basketball_nba/events/a37e80a2e3cf3aaa3ae84a9124987058/odds?apiKey=$ODDS_API_KEY&regions=us&markets=player_threes&oddsFormat=american"
```

| Field | Value |
|---|---|
| HTTP status | `200 OK` |
| `x-requests-used` | `26` |
| `x-requests-remaining` | `474` |
| `x-requests-last` | **`1`** |
| Response body (first ~500 bytes) | `{"id":"a37e80a2e3cf3aaa3ae84a9124987058","sport_key":"basketball_nba","sport_title":"NBA","commence_time":"2026-05-02T23:40:00Z","home_team":"Boston Celtics","away_team":"Philadelphia 76ers","bookmakers":[{"key":"draftkings","title":"DraftKings","markets":[{"key":"player_threes","last_update":"2026-05-02T20:33:44Z","outcomes":[{"name":"Over","description":"Tyrese Maxey","price":-152,"point":2.5},{"name":"Under","description":"Tyrese Maxey","price":115,"point":2.5},{"name":"Over","description":"J` |

### 2.2 Free spacer (deterministic-delta check)

```
curl -sS -D /tmp/h_b.txt "$ODDS_API_BASE_URL/v4/sports?apiKey=$ODDS_API_KEY"
```

| Field | Value |
|---|---|
| HTTP status | `200 OK` |
| `x-requests-used` | `26` (unchanged from 2.1) |
| `x-requests-last` | `0` |

`/v4/sports` confirmed free; the `used` counter did not advance, so I can read the post-multi-market delta without worrying about background drift.

### 2.3 Multi-market call (5 markets in one URL)

```
curl -sS -D /tmp/h_c.txt \
  "$ODDS_API_BASE_URL/v4/sports/basketball_nba/events/a37e80a2e3cf3aaa3ae84a9124987058/odds?apiKey=$ODDS_API_KEY&regions=us&markets=player_points,player_rebounds,player_assists,player_threes,player_steals&oddsFormat=american"
```

| Field | Value |
|---|---|
| HTTP status | `200 OK` |
| `x-requests-used` | `31` |
| `x-requests-remaining` | `469` |
| `x-requests-last` | **`5`** |

### 2.4 Conclusion: per-market billing

- Single-market call charged **1 unit**.
- 5-market call charged **5 units** (`x-requests-last=5`, `used` jumped 26 → 31).
- Billing model: **per populated market in URL**, NOT per HTTP call.

Important corollary discovered during stat probing (§3.4): a call with a *valid* market key that returns `bookmakers: []` charges **0 units**, and a call returning HTTP 422 INVALID_MARKET also charges 0. Combined this means: cost = number of markets in URL that returned ≥ 1 bookmaker. This nuance matters for the cost-estimate math in §4 — empty NBA markets do NOT inflate quota burn.

This places us in **§3.2 branch B** of the ticket: "per-market billing → CTO must produce plan v2 with Phase 1 limited to high-confidence markets."

---

## 3. Per-stat probes

For each of the 9 candidate stats: (a) curl, (b) HTTP status, (c) ~500-byte body excerpt, (d) quota headers, (e) classification, (f) Scout recommendation.

For brevity, every curl below uses the shape:
```
curl -sS -D /tmp/h_<label>.txt \
  "$ODDS_API_BASE_URL/v4/sports/basketball_nba/events/a37e80a2e3cf3aaa3ae84a9124987058/odds?apiKey=$ODDS_API_KEY&regions=us&markets=<KEY>&oddsFormat=american"
```
…where `<KEY>` is named per row.

### 3.1 3PM (three-pointers made) — `[direct-supported]`

| | |
|---|---|
| Market key | `player_threes` ✅ (CTO best-guess was correct) |
| HTTP | `200` |
| `x-requests-last` | `1` |
| Body excerpt | `...{"key":"player_threes","last_update":"2026-05-02T20:33:44Z","outcomes":[{"name":"Over","description":"Tyrese Maxey","price":-152,"point":2.5},{"name":"Under","description":"Tyrese Maxey","price":115,"point":2.5}, ...` |

Outcome shape: standard Over/Under with `point` (e.g. 2.5 threes). Multiple bookmakers (DraftKings shown; ~6+ other US books expected per existing `odds_history` allow-list). Same shape as `player_points`, no parser changes needed.

**Recommendation:** include in Phase 1.

### 3.2 STL (steals) — `[direct-supported]`

| | |
|---|---|
| Market key | `player_steals` ✅ |
| HTTP | `200` |
| `x-requests-last` | `1` |
| Body excerpt | `...{"key":"player_steals","last_update":"2026-05-02T20:35:55Z","outcomes":[{"name":"Over","description":"Paul George","price":109,"point":1.5},{"name":"Under","description":"Paul George","price":-144,"point":1.5}, ...` |

Standard Over/Under with `point` (often 0.5 / 1.5 — note the very low integer thresholds → variance is high; backtest CLV before promoting to a default selector option).

**Recommendation:** include in Phase 1.

### 3.3 FTM (free throws made) — `[schema-valid-no-current-inventory]` ⚠ CORRECTED 2026-05-02 post-review

> **Original conclusion was wrong** (had this as `[not-available]`). Eason flagged on SPO-12 review thread (2026-05-02 22:42 UTC): "the odds api 的 document其實是有FTM的，但是可能今天這場比賽剛好沒有." Re-probed using the canonical key from the docs and confirmed FTM is schema-valid; current bookmaker inventory is just empty for today's events.

#### 3.3a — Variants probed in initial pass (all 422, all 0-cost)

| Variant | HTTP | Body |
|---|---|---|
| `player_freethrows_made` | `422` | `{"message":"Invalid markets: player_freethrows_made","error_code":"INVALID_MARKET", ...}` |
| `player_free_throws` | `422` | `{"message":"Invalid markets: player_free_throws","error_code":"INVALID_MARKET", ...}` |
| `player_free_throws_made` | `422` | `{"message":"Invalid markets: player_free_throws_made","error_code":"INVALID_MARKET", ...}` |

3-variant cap was hit per `CLAUDE.md` anti-burn rule. None of these spell the canonical `frees` form.

#### 3.3b — Canonical key (per The Odds API docs): `player_frees_made`

The docs page (`https://the-odds-api.com/sports-odds-data/betting-markets.html`) lists in the NBA player-prop section:

- `player_frees_made` — "Frees made (Over/Under)"
- `player_frees_attempts` — "Frees attempted (Over/Under)"

(Note: the docs use "frees" — a non-obvious abbreviation — not "free_throws". This is exactly the class of LLM-from-training-data hallucination `CLAUDE.md § External API Wrappers` rule #1 was written to prevent.)

#### 3.3c — Post-review probe (2 separate event_ids, both 200 + empty + 0-cost)

```bash
curl -sS -D /tmp/h.txt \
  "$ODDS_API_BASE_URL/v4/sports/basketball_nba/events/<EVENT_ID>/odds?apiKey=$ODDS_API_KEY&regions=us&markets=player_frees_made&oddsFormat=american"
```

| event_id | matchup | HTTP | `x-requests-last` | `bookmakers` | Body excerpt |
|---|---|---|---|---|---|
| `a37e80a2e3cf3aaa3ae84a9124987058` | PHI @ BOS, 2026-05-02T23:40Z | `200` | `0` | `[]` | `{"id":"a37e80a2e3cf3aaa3ae84a9124987058","sport_key":"basketball_nba","sport_title":"NBA","commence_time":"2026-05-02T23:40:00Z","home_team":"Boston Celtics","away_team":"Philadelphia 76ers","bookmakers":[]}` |
| `be60e6f50fc77fc3a3cf6925472bad91` | ORL @ DET, 2026-05-03T19:40Z | `200` | `0` | `[]` | `{"id":"be60e6f50fc77fc3a3cf6925472bad91","sport_key":"basketball_nba","sport_title":"NBA","commence_time":"2026-05-03T19:40:00Z","home_team":"Detroit Pistons","away_team":"Orlando Magic","bookmakers":[]}` |

Quota before/after re-probe: `x-requests-used` stayed at `40`, `x-requests-remaining` stayed at `460` — both 200-empty calls were free, consistent with the per-market billing model from §2.

This is the same "valid key, no current bookmaker inventory for NBA in `us` region" pattern that `player_field_goals` produces (§3.4).

#### 3.3d — Implementation recommendation

Two clean options. Both are technically safe:

- **(A) Ship in Phase 1 as graceful-degrade tier.** Add `player_frees_made` to `SUPPORTED_MARKETS` and let the existing `decision_20260502_phase0-research-first-and-derive-strategy.md` §3 graceful-degrade UI do its job. When the bookmaker list is empty, the frontend tile shows "no bookmaker line — historical + projection only." If/when bookmakers start posting FTM lines (could be tomorrow, could be next playoff round), the UI lights up automatically with no Forge code change. Cost: +1 unit per snapshot when FTM IS posted; 0 when it isn't (per-market billing).
- **(B) Defer to Phase 2.** Don't add to `SUPPORTED_MARKETS` until a backfill probe over a 1–2 week window confirms regular bookmaker inventory. Eliminates the "user clicks FTM, sees empty tile" UX hit but ships strictly less than what Eason asked for in SPO-10.

**My lean: (A).** Reason: graceful-degrade UI was specifically agreed in the decision log §3 and the historical-CSV tab still gives the user something useful (even if FTM as a *single* prop has tight σ and rarely shows actionable EV — a domain caveat, not a Forge blocker). Shipping behind the existing graceful-degrade pattern is one config-list change for Forge, no new code paths. Same logic applies to FGA in §3.4 — bundling FTM and FGA together as the Phase 1 "graceful-degrade tier" is one decision instead of two.

**CTO call.** I'll defer the final answer to the `decision_<YYYYMMDD>_market-key-feasibility.md` write-up.

### 3.4 FGA (field goals attempted) — `[valid-key-but-empty-for-NBA]` → effectively `[not-available]`

| Variant | HTTP | `x-requests-last` | Body |
|---|---|---|---|
| `player_field_goals_attempted` | `422` | `0` | `INVALID_MARKET` |
| `player_field_goal_attempts` | `422` | `0` | `INVALID_MARKET` |
| `player_field_goals` | **`200`** | **`0`** | `{"id":"a37e80a2e3cf3aaa3ae84a9124987058","sport_key":"basketball_nba", ..., "bookmakers":[]}` |

Surprise finding: `player_field_goals` is a **valid** market name in The Odds API schema (no 422), but **no NBA bookmaker offers it for this event** — `bookmakers: []`. This is a different case from "schema doesn't recognise the key" — it's "schema knows the key, no inventory in this region/event." Cost is 0 (consistent with the per-populated-market billing model).

**Docs cross-check (added 2026-05-02 post-review):** The Odds API docs page (`the-odds-api.com/sports-odds-data/betting-markets.html`) lists exactly **one** field-goals market for NBA: `player_field_goals` (described as "Field goals (Over/Under)"). There is **no separate `player_field_goals_attempted` / `_attempts` key in the documented NBA market list** — the docs do however use the `_attempts` suffix for free throws (`player_frees_attempts`), confirming the suffix convention exists. So:

1. The 422s on `player_field_goals_attempted` and `player_field_goal_attempts` are not "wrong variant of an existing key" — those keys genuinely don't exist for NBA.
2. By analogy with `player_frees_made` (made) vs `player_frees_attempts` (attempted), **bare `player_field_goals` is most likely FGM, not FGA.** Forge should treat the FGM-vs-FGA semantics as ambiguous until a populated response actually arrives — but my prior (FGM bias) stands.

**Recommendation:** **Phase 1 graceful-degrade tier (CTO call), bundled with FTM.** Same logic as §3.3d above: schema-valid + currently empty + 0-cost while empty + lights up automatically when bookmakers post lines. If it eventually populates and turns out to be FGM (likely), the user gets a working tile with no Forge code change. If it never populates within Phase 2's monitoring window, Forge can drop it from `SUPPORTED_MARKETS` then. **For FGA proper** (attempts), defer to Phase 2 / Phase 3 — there is no API path today.

### 3.5 3PA (three-pointers attempted) — `[not-in-schema]`

| Variant | HTTP | Body |
|---|---|---|
| `player_threes_attempted` | `422` | `INVALID_MARKET` |
| `player_three_pointers_attempted` | `422` | `INVALID_MARKET` |
| `player_three_point_attempts` | `422` | `INVALID_MARKET` |

3-variant cap reached. All charged 0 units.

**Docs cross-check (added 2026-05-02 post-review):** The Odds API NBA player-prop list contains `player_threes` (= 3PM) but **no `player_threes_attempts` (or any 3PA variant)** — confirmed by reading the betting-markets docs page. The `_attempts` suffix exists in the API (cf `player_frees_attempts` for free throws), but the docs simply don't expose a 3PA market for NBA. This is genuinely "not in The Odds API schema" — distinct from FTM/FGA's "valid key, currently empty inventory" case.

**Recommendation:** **Defer entirely** — neither Phase 1 nor Phase 2's graceful-degrade tier is a fit, because there's no API contract to graceful-degrade *from*. If Eason wants 3PA in the selector for SPO-10 completeness, it would have to be a "historical CSV + projection only, no API binding ever" tile, with explicit "not from The Odds API" UI copy so the user doesn't expect bookmaker lines. Personally I'd cut it.

### 3.6 R+A (rebounds + assists) — `[direct-supported]`

| | |
|---|---|
| Market key | `player_rebounds_assists` ✅ |
| HTTP | `200` |
| `x-requests-last` | `1` |
| Body excerpt | `...{"key":"player_rebounds_assists","last_update":"2026-05-02T20:35:55Z","outcomes":[{"name":"Over","description":"Jayson Tatum","price":-124,"point":15.5},{"name":"Under","description":"Jayson Tatum","price":-106,"point":15.5},{"name":"Over","description":"Joel Embiid","price":-127,"point":13.5}, ...` |

**Crucial finding for the SPO-11 plan §3.2 / Decision §2 derive question:** combo markets are **natively supported as single keys**. We get one bookmaker line per player per combo (e.g. Tatum R+A 15.5 @ -124/-106). No backend sum, no vig double-counting, no convolution math required.

This **changes** the Phase 0 decision context but not its conclusion: backend is still the right place to expose `r_a` etc. (consistency with PRA's `player_points_rebounds_assists` already in `SUPPORTED_MARKETS`), but the "vig-free probability" concern that was driving the backend-vs-frontend decision is no longer load-bearing — it would still apply if we *fell back* to deriving (e.g. if a particular bookmaker doesn't post `player_rebounds_assists` for a player but DOES post `player_rebounds` and `player_assists` separately), but that fallback is a rare-edge case worth deferring entirely.

**Recommendation:** include in Phase 1. Forge: just add `("player_rebounds_assists", "ra")` to `SUPPORTED_MARKETS` — same shape as PRA, no special handling.

### 3.7 P+R (points + rebounds) — `[direct-supported]`

| | |
|---|---|
| Market key | `player_points_rebounds` ✅ |
| HTTP | `200` |
| `x-requests-last` | `1` |
| Body excerpt | `...{"key":"player_points_rebounds","last_update":"2026-05-02T20:35:55Z","outcomes":[{"name":"Over","description":"Joel Embiid","price":-114,"point":34.5},{"name":"Under","description":"Joel Embiid","price":-116,"point":34.5}, ...` |

Standard Over/Under with `point`. Same parser as PRA.

**Recommendation:** include in Phase 1.

### 3.8 P+A (points + assists) — `[direct-supported]`

| | |
|---|---|
| Market key | `player_points_assists` ✅ |
| HTTP | `200` |
| `x-requests-last` | `1` |
| Body excerpt | `...{"key":"player_points_assists","last_update":"2026-05-02T20:35:55Z","outcomes":[{"name":"Over","description":"Jaylen Brown","price":-119,"point":31.5},{"name":"Under","description":"Jaylen Brown","price":-110,"point":31.5}, ...` |

**Recommendation:** include in Phase 1.

### 3.9 DD (double-double) — `[direct-supported]` ⚠ DIFFERENT OUTCOME SHAPE

| | |
|---|---|
| Market key | `player_double_double` ✅ (against CTO's "low" confidence — confirmed) |
| HTTP | `200` |
| `x-requests-last` | `1` |
| Body excerpt | `...{"key":"player_double_double","last_update":"2026-05-02T20:35:55Z","outcomes":[{"name":"Yes","description":"Jayson Tatum","price":-156},{"name":"Yes","description":"Joel Embiid","price":128},{"name":"Yes","description":"Jaylen Brown","price":265},{"name":"Yes","description":"Neemias Queta","price":382},{"name":"Yes","description":"Tyrese Maxey","price":546}, ...` |

⚠ **Outcome shape differs from every other supported market.** Two structural differences:

1. `name` is `"Yes"` / `"No"` (binary), not `"Over"` / `"Under"`.
2. There is **no `point` field** at all — DD is binary, not threshold-based.
3. In the live snapshot above, **only `Yes` outcomes are returned for DraftKings** (no `No` row). The book is implicitly pricing the "No" via the implied market — Forge will need to either (a) compute No from Yes vig-included, or (b) fan out across more bookmakers and hope one posts both legs.

Implication for Forge:
- `csv_player_history.get_player_stats()` cannot reuse the `compute_over_probability` path. DD needs a binary-history function: `P(DD = 1) = count(games where ≥2 of {pts,reb,ast,stl,blk} ≥ 10) / total_games`. This matches the §4 of the existing decision log ("DD 第一期只算歷史 P(DD=1)").
- The frontend `MarketSelect` group needs a `Binary` group (separate from Single / Combo) — DD doesn't fit "Over/Under at threshold X". Forge frontend ticket will need to design a binary tile (probably "Yes price + Yes implied probability + Yes historical" rather than the line-and-O/U layout).
- The existing decision log §4 says "DD projection 顯示 N/A" — Scout agrees. Phase 1 should display DD with bookmaker Yes price + historical P(DD=1) + "ML projection N/A (next phase)".

**Recommendation:** include in Phase 1 *with explicit Forge sub-task scope* covering binary outcome parsing, separate frontend tile, and historical P(DD=1) function. This is more Forge work than a standard market — flag clearly in the Forge ticket.

---

## 4. Phase 1 scope recommendation

### 4.1 Conditional logic mapping (per §3.2 of SPO-12)

| §3.2 branch | Trigger | Result |
|---|---|---|
| A — per-call | 5-market call charges 1 unit | not observed |
| **B — per-market** | **5-market call charges 5 units** | **observed (this session)** |
| C — grouped | 5-market call charges between 1 and 5 | not observed |

**Branch B applies.** Per the ticket, this branch's prescription was: "Phase 1 限縮到 6 個 high-confidence markets (3PM / STL / FTM / R+A / P+R / P+A)，把 FGA / 3PA / DD 留給 Phase 2."

Post-correction (2026-05-02 review with Eason on FTM), Scout proposes a 3-tier amendment:

| Stat | Templated branch B | Scout post-review tier | Reason |
|---|---|---|---|
| 3PM | include | **A — hard-supported** | direct-supported (200 + populated) |
| STL | include | **A — hard-supported** | direct-supported |
| FTM | include | **B — graceful-degrade** *(was: drop)* | schema-valid via `player_frees_made`; currently empty inventory; 0-cost while empty |
| R+A | include | **A — hard-supported** | direct-supported |
| P+R | include | **A — hard-supported** | direct-supported |
| P+A | include | **A — hard-supported** | direct-supported |
| FGA | defer | **B — graceful-degrade** *(was: defer)* | schema-valid via `player_field_goals`; currently empty; FGM-vs-FGA semantics ambiguous (likely FGM by docs convention) |
| 3PA | defer | **defer (no API path)** | not in The Odds API NBA market list per docs — distinct from FTM/FGA's "valid but empty" case |
| DD | defer | **A — hard-supported** *(was: defer)* | direct-supported; outcome shape differs — Forge needs binary parser sub-task |

**Net Phase 1 scope (Scout recommendation):**
- **Tier A (hard-supported, 6):** 3PM, STL, R+A, P+R, P+A, DD — must ship in Phase 1, all carry full bookmaker lines today.
- **Tier B (graceful-degrade, 2):** FTM, FGA — schema-valid + currently empty. Forge adds them to `SUPPORTED_MARKETS` and the existing decision-log §3 graceful-degrade UI handles the empty-bookmakers state. Cost is 0 units while empty. **CTO call:** ship in Phase 1 (Scout lean) or hold for Phase 2 monitoring window.
- **Defer (1):** 3PA — no API contract; revisit only if Eason wants a historical-only "no API binding ever" tile.

If CTO accepts Tier A only, `SUPPORTED_MARKETS` grows from 4 to 10. If CTO accepts Tier A+B, it grows from 4 to 12 (but the +2 is free while bookmakers don't post FTM/FGA). The Tier-A-only path gives Phase 2 cleaner room to add FTM/FGA later.

### 4.2 Quota burn estimate

Existing `daily_analysis` snapshot pattern (`backend/app/services/odds_snapshot_service.py:45,300`): one event-odds call per event × `SNAPSHOT_MARKETS`. With 4 markets today that's 4 units / event / call. With the recommended 10 markets that's 10 units / event / call (assuming all populated; reality may be lower for sparser markets like DD on bench players).

Rough burn math (orders-of-magnitude only — Forge / CTO should re-derive against actual scheduler cadence):
- 4 markets, 10 NBA events/day, 1 snapshot pull/day (ignoring agent-triggered fetches) = 40 units/day = 1200 units/month → **already over 500-unit free tier.** This implies the existing system is either (a) on a paid plan, (b) running snapshots less often than 1/day per event, or (c) heavily cache-hitting.
- 10 markets, same cadence = 100 units/day = 3000 units/month.

Action items implied (out of Scout's scope, flagging for CTO):
- The existing snapshot cadence + cache TTL needs review before scaling to 10 markets. The `Domain Lens` rule "API rate-limit / cost-per-call" makes this a `[Major]` risk if not validated.
- Forge backend ticket should NOT add `SUPPORTED_MARKETS` blindly — it should also confirm the snapshot scheduler cadence and Redis TTL are tuned for 2.5x markets.

### 4.3 Combo / DD math approach

Rephrasing SPO-12 §2's "(R+A, P+R, P+A) 能否從 component sum 自行算" question, using the new evidence:

- **R+A, P+R, P+A**: native bookmaker line exists. **Use the native line.** No sum, no convolution, no vig-double-count concern. The existing PRA pattern at `backend/app/services/projection_provider.py:365-371` (which computes `pra = pts + reb + ast` for projections) can be extended for `r_a`, `p_r`, `p_a` projections, but the *bookmaker-side* code (`OddsGateway`, `daily_analysis`, snapshot) should treat each as a first-class market like `player_points`.
- **DD**: there is no "component sum" in any meaningful sense — DD is a binary indicator, not a sum of two stats. The right historical estimator is `P(DD=1) = #games where ≥2 of {pts,reb,ast,stl,blk} ≥ 10 / #games played`. The right bookmaker-side estimator is the Yes price (de-vigged). Phase 1 should ship those two; ML projection (joint multi-variate model over 5 stats) stays Phase 2 per the existing decision log §4.

### 4.4 UI implications (out of Forge backend scope, in scope for Forge frontend)

Per `decision_20260502_phase0-research-first-and-derive-strategy.md` §3 (graceful-degrade for unsupported markets), the selector grouping should reflect the new 3-tier classification:

1. **Group selector by tier, not by stat type.** E.g.:
   - "Singles (live odds)": PTS, REB, AST, 3PM, STL
   - "Combos (live odds)": PRA, R+A, P+R, P+A
   - "Binary (live odds)": DD
   - "Live odds when bookmakers post" *(Tier B graceful-degrade, only if CTO opts in)*: FTM, FGA — tile renders bookmaker line if non-empty, otherwise drops to "historical + projection only" with a tooltip "this prop isn't currently offered by US bookmakers; tile updates automatically when it is."
   - "Historical-only (no API path)" *(only if Eason wants 3PA)*: 3PA
2. **Tier B tiles must distinguish "currently empty" from "broken"**: text like "no bookmaker line right now — historical mode" reads as a temporary state; "no live data available" reads as a bug. Word it as state, not error.
3. **Tier B and historical-only tabs must NOT fake an O/U threshold** (`CLAUDE.md` anti-hallucination policy). Greyed-out odds card or "—" placeholders, never a fabricated number.

---

## 5. Open questions for CTO

1. **Phase 1 scope: Tier A only (6) or Tier A + Tier B (8)?** Updated post-review. Tier A = 3PM/STL/R+A/P+R/P+A/DD (must include). Tier B = FTM (`player_frees_made`) + FGA (`player_field_goals`) — both schema-valid and currently empty inventory. Scout lean: **A only for Phase 1**; defer B until a 1-2-week monitoring window confirms bookmaker inventory frequency. Reasoning: even though Tier B costs nothing while empty, shipping a tile labelled "live odds when bookmakers post" creates a UX expectation we may not meet for weeks. Cleaner story to ship A confidently and add B in a Phase 1.5 hotfix if bookmakers light up. **But** if CTO/Eason want 8 in Phase 1 to match SPO-10 narrative completeness, the technical path is one config-list line.
2. **3PA in selector at all?** Not in The Odds API NBA schema — confirmed via docs. Three options: (a) hide entirely (Scout lean), (b) include as "historical-only / no API binding" tile per current decision-log §3, (c) defer the decision to a Phase 2 selector revamp. Recommend (a) because the user doesn't actually click 3PA much (per Sports Lab CSV usage patterns) and the historical-only tile precedent doesn't exist yet — no need to invent a new UX class for one stat.
3. **DD projection in Phase 1?** Confirming decision §4: skip ML projection, ship binary historical `P(DD=1)` only, label projection "N/A (next phase)". CTO should explicitly OK this in the SPO-11 thread.
4. **Snapshot cadence review.** With 6–8 new markets going into `SUPPORTED_MARKETS`, current monthly quota burn needs re-derivation before merge. The `Domain Lens` "API rate-limit / cost-per-call" rule plus the `[Major]` cost-regression threshold (`CLAUDE.md` Domain Lenses) makes this a **must-check before Forge merges**. Suggest a dedicated CTO decision-log update OR a Sentinel sanity test that simulates a 1-week scheduler run against a mocked clock and asserts monthly burn ≤ plan limit.
5. **`player_field_goals` semantics.** Almost certainly FGM (per the docs' `_attempts` suffix convention). If CTO wants to confirm before shipping, the cheap path is: poll the key once per week against a populated event window for 2 weeks; the first 200-with-bookmakers response will reveal the `point` distribution (FGM thresholds cluster around 5–10, FGA around 10–20). Out of Phase 1 scope; cheap to add as a Sentinel watchlist task.
6. **Variant exhaustion (resolved post-review).** Original 3-variant cap on FTM was insufficient — none of the 3 was the canonical `player_frees_made`. Lesson: when a stat 422s on all variants, the next move is to consult docs (or ask Eason) before stamping `[not-available]`. I'll add this to my Scout heuristics so the same mistake doesn't recur.

---

## 6. Sources (curl evidence appendix)

All commands executed 2026-05-02 between ~20:30 and ~20:40 UTC. Output captured to `/tmp/r_<label>.json` and `/tmp/h_<label>.txt` headers; key headers and ~500-byte body excerpts inlined per stat in §3 above. Re-runnable end-to-end via `python3 scripts/explore_odds_api_extensions.py` (see notes in §4 about quota — do not loop).

**Quota arc this session:** `x-requests-used: 25 → 36` (11 paid units). Final state captured 2026-05-02 ~20:40 UTC: `used=36, remaining=464`. All paid charges accounted for:

| Step | Markets in URL | `x-requests-last` | Cumulative `used` |
|---|---|---|---|
| Start | — | — | 25 |
| Single (`player_threes`) | 1 | 1 | 26 |
| Multi (5 markets) | 5 | 5 | 31 |
| `player_steals` | 1 | 1 | 32 |
| `player_rebounds_assists` | 1 | 1 | 33 |
| `player_points_rebounds` | 1 | 1 | 34 |
| `player_points_assists` | 1 | 1 | 35 |
| FTM × 3 (all 422) | 3 | 0 | 35 |
| FGA × 2 (422) + 1 empty | 3 | 0 | 35 |
| 3PA × 3 (all 422) | 3 | 0 | 35 |
| `player_double_double` | 1 | 1 | 36 |
| DD variants 2-3 (422) | 2 | 0 | 36 |
| End of initial pass | — | — | 36 |
| **Post-review re-probe (2026-05-02 22:42+)**: `player_frees_made` × 2 events (both 200 + empty bookmakers) | 1 each | 0 | 36 |
| End of post-review | — | — | **40** *(see note below)* |

**Total Scout-attributable paid burn: 11 units** (initial pass) + **0 units** (post-review FTM re-probe) = **11 units**.

**Note on the `used=36 → used=40` delta:** between the initial pass (2026-05-02 ~20:40 UTC) and the post-review re-probe (2026-05-02 ~22:45 UTC), `x-requests-used` advanced by 4 with no Scout-attributable calls. This is consistent with `daily_analysis` / scheduler activity in the live backend (the existing Sports Lab cron pulls live odds for current NBA events). Confirmed `x-requests-last=0` on both Scout re-probe calls — the 4-unit delta belongs to the running stack, not Scout. Forge / Sentinel should keep this in mind: live counters are non-deterministic for any agent that isn't the only client. Safer to record `x-requests-last` (per-call delta) than `x-requests-used` (cumulative) when reasoning about cost.

---

## 7. Out of scope for this ticket (per SPO-12 §5)

- ✋ Did not modify any backend / frontend code
- ✋ Did not write integration tests (Sentinel)
- ✋ Did not modify the plan document or decision log (CTO)
- ✋ Did not compare other providers (SportsData / RotoWire) — pure The Odds API research
- ✋ Did not negotiate / evaluate plan upgrades — quota cost report goes to CTO for plan v2 decision

---

## Addendum 1 — Docs cross-check flagged two untested FTM variants (2026-05-02)

**Author:** Out-of-band docs cross-check (Claude IDE assistant, at owner's request). **Not a Scout re-run — no API calls made, quota unchanged at `used=36 / remaining=464`.**

**Trigger:** Owner asked whether FTM / FGA / 3PA truly do not exist in The Odds API. Cross-checking against the live betting-markets docs surfaced a gap in §3.3's variant coverage.

**Source:** [The Odds API — Betting Markets](https://the-odds-api.com/sports-odds-data/betting-markets.html), fetched 2026-05-02 via WebFetch. The basketball / NBA section enumerates these keys relevant to free throws:

- `player_frees_made`
- `player_frees_attempts`

**Gap vs §3.3:** Scout tested `player_freethrows_made`, `player_free_throws`, `player_free_throws_made` — all use the stem `free_throws` / `freethrows`. The docs' actual stem is **`frees`** (plural-shorthand). The 3-variant anti-burn cap fired before the docs page was consulted, so the canonical key was never reached.

`player_frees_attempts` (FTA) was outside §3's 9-stat scope and was not tested either; flagged here for completeness because the same naming clue applies and FTA may be a useful Phase 2 candidate alongside FTM.

**Status of §3.3 / TL;DR / §4 conclusions:** **Unchanged.** Per `CLAUDE.md § External API Wrappers` rule #3 ("Claims with no curl evidence are unverified and not grounds for implementation"), this addendum does NOT promote FTM to `[direct-supported]`. Schema-listed keys can still return `bookmakers: []` for a given region / event — see §3.4's `player_field_goals` finding for precedent.

**Recommended next action (next Scout wake — or whoever picks this up):**

1. `curl` `player_frees_made` against a live NBA event. Cost: 1 unit if ≥1 bookmaker returned; 0 if 422 or empty.
2. If positive, `curl` `player_frees_attempts`. Same cost profile.
3. If both populated: amend §3.3 (FTM → `[direct-supported]`), TL;DR row 2, §4.1 amendment table, §4.2 quota-burn estimate, and re-open SPO-12 §5 Q1 (selector grouping) for CTO. Phase 1 scope grows from 6 to 7 or 8 markets (10 → 11–12 in `SUPPORTED_MARKETS`).
4. If `player_frees_made` returns 200 with `bookmakers: []`: classify identical to §3.4 (`[valid-key-but-empty-for-NBA]`), defer to Phase 2, and update this addendum with the result.

**Estimated additional quota:** ≤ 2 units (well within remaining 464).

**Open question for CTO:** does this finding warrant re-opening SPO-12, or is it small enough to fold into the Phase 1 Forge ticket as a "before-you-merge, run these 2 curls" pre-flight check? Scout-flavored recommendation: re-open SPO-12 with a tight scope ("verify 2 variants, amend doc, hand back"), so the audit trail in this research doc stays clean and Forge does not inherit research work.
