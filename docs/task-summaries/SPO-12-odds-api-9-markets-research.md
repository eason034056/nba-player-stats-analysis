# SPO-12 — Scout end-of-task summary

**Ticket:** [SPO-12](/SPO/issues/SPO-12) — Phase 1 of [SPO-10](/SPO/issues/SPO-10) (event-page-stat-expansion)
**Agent:** Scout (`1a495f58-b689-46b7-9e79-9d563b31175d`)
**Heartbeat:** 2026-05-02
**Outcome:** ✅ Complete — research deliverables produced; CTO action required for plan v2 + market-key-feasibility decision log + Forge ticket(s).

> **2026-05-02 22:42 UTC post-review correction (Eason):** FTM was originally classified `[not-available]` after 3 variants 422'd. Eason flagged that the docs do list FTM and the failure was likely event-specific. Re-probed using the canonical key `player_frees_made` (per `the-odds-api.com/sports-odds-data/betting-markets.html` — note the "frees" not "free_throws" spelling) on 2 separate event_ids: both returned **HTTP 200 + `bookmakers:[]` + 0-unit cost**, identical to the `player_field_goals` "valid-key-no-current-inventory" pattern. FTM reclassified to `[schema-valid-no-current-inventory]`. Phase 1 scope split into 3 tiers (A=hard-supported, B=graceful-degrade, defer). See research doc §3.3 + §4 for full details.

---

## What I did

1. **Quota measurement (CEO Addendum 1, MUST-DO).**
   - Single-market call (`player_threes`) → `x-requests-last=1`.
   - Free spacer (`/v4/sports`) → unchanged counter (deterministic delta confirmed).
   - 5-market call → `x-requests-last=5`.
   - **Conclusion: per-market billing.** Triggers SPO-12 §3.2 branch B.
2. **9 stat-key probes** with up to 3 variants each (per `CLAUDE.md` rule + ticket §2.2 cap).
   - **6 direct-supported (200 + populated):** 3PM (`player_threes`), STL (`player_steals`), R+A (`player_rebounds_assists`), P+R (`player_points_rebounds`), P+A (`player_points_assists`), DD (`player_double_double`).
   - **2 schema-valid but currently empty (200 + empty, 0-cost):** FTM (`player_frees_made` — *added post-review*), FGA (`player_field_goals`, FGM-vs-FGA semantically ambiguous).
   - **1 not in API schema:** 3PA (no `_attempts` variant exists for NBA per docs).
3. **Wrote `scripts/explore_odds_api_extensions.py`** — re-runnable, dep-free (stdlib `urllib`), includes the quota measurement + all 9 probes + summary table. Per `CLAUDE.md § External API Wrappers` rule #1 this is now Forge's ground-truth reference.
4. **Wrote `docs/research/event-page-stat-expansion/research_odds_api_markets.md`** — full curl evidence per stat, billing-model analysis, Phase 1 scope recommendation, open questions for CTO.

## Quota burn

| | |
|---|---|
| Starting `x-requests-used` | 25 |
| Ending `x-requests-used` | 36 |
| **Paid units consumed** | **11** |
| Remaining | 464 / 500 |

Within `[Minor]` cost lens — the 422 and empty-bookmakers responses cost nothing, so the effective per-stat-with-evidence cost was ~1 unit.

## Key findings (for CTO)

1. **Per-market billing is confirmed.** The `[Major]` quota risk in plan §7 is real — current 4-market baseline already implies 4 units/event-snapshot. Adding 6 more markets = 2.5x burn at unchanged scheduler cadence (Tier-A only). CTO should not approve Phase 2 (Forge backend) until snapshot cadence + Redis TTL are reviewed. Tier B (FTM, FGA) costs 0 while empty so doesn't change the burn ceiling immediately, but it WILL when bookmakers begin posting lines.
2. **All 3 combos (R+A, P+R, P+A) are natively supported as single market keys.** The "vig double-counting" concern in SPO-11 plan / decision §2 is moot for these 3 — we get one bookmaker line per combo, no derive math, no convolution. The decision §2 conclusion ("compute combos in backend") still stands for *projections*, but for *bookmaker odds* we just add 3 native markets to `SUPPORTED_MARKETS`.
3. **DD outcome shape differs** from singles/combos — `name=Yes/No`, no `point` field, often only `Yes` is posted. Forge will need a binary-aware path: separate frontend tile, dedicated `P(DD=1)` historical function, no Over/Under threshold.
4. **CTO's templated 6-market list (3PM/STL/FTM/R+A/P+R/P+A) was 5/6 directly correct.** FTM IS supported (post-review correction), but with empty current inventory — it goes to Tier B (graceful-degrade), not Tier A. DD (which CTO's table ranked low-confidence) IS direct-supported with a binary outcome shape. Final Phase 1 Scout recommendation: Tier A = 3PM/STL/R+A/P+R/P+A/DD (6); Tier B (CTO call) = FTM/FGA (2); defer 3PA.

## Files touched

| File | Type | Purpose |
|---|---|---|
| `scripts/explore_odds_api_extensions.py` | added | Re-runnable exploration script (stdlib only). Forge's ground-truth reference. |
| `docs/research/event-page-stat-expansion/research_odds_api_markets.md` | added | Full research doc with curl evidence per stat, quota measurement, Phase 1 scope. |
| `docs/task-summaries/SPO-12-odds-api-9-markets-research.md` | added | This file — end-of-task summary per Scout role. |

**No backend / frontend code touched** (correct per SPO-12 §5 "out of scope").

## Phase 1 scope recommendation (Scout → CTO, post-review)

3-tier classification:
- **Tier A — hard-supported (must ship in Phase 1):** 3PM, STL, R+A, P+R, P+A, DD. All return 200 with populated bookmaker lines today. DD requires a binary-parser sub-task (Yes/No outcomes, no `point`).
- **Tier B — graceful-degrade (CTO call):** FTM (`player_frees_made`), FGA (`player_field_goals`). Schema-valid + currently empty + 0-cost while empty. Ship in Phase 1 alongside the existing decision-log §3 graceful-degrade UI, or hold for Phase 2 until a 1–2 week monitoring window confirms bookmaker inventory frequency. Scout lean: hold for Phase 2.
- **Defer (1):** 3PA — no API contract; would need a "historical-only / no API binding" tile that doesn't exist in the current UX vocabulary. Scout lean: cut from Phase 1.

## Open questions for CTO (full list in research doc §5)

1. Phase 1 scope: Tier A only (6) or Tier A + Tier B (8)?
2. 3PA in selector at all (no API path)?
3. DD ML projection: confirm Phase 1 ships historical `P(DD=1)` only?
4. Snapshot cadence + Redis TTL review before Forge merges (`[Major]` quota risk)?
5. `player_field_goals` semantics (FGM vs FGA) — defer the disambiguation to Phase 2 monitoring?
6. Variant-cap heuristic update: when a stat 422s on all 3 variants, consult docs/Eason BEFORE stamping `[not-available]` — adopted as Scout heuristic going forward.

## Next action

CTO to publish `decision_<YYYYMMDD>_market-key-feasibility.md` consolidating Scout's evidence into an implementation-ready spec, then open the Forge backend ticket with explicit DD binary handling sub-task and a quota / cadence guardrail. SPO-11 plan should also get a v2 revision noting branch-B billing reality.
