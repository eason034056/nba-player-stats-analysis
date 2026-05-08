# SPO-26 — Backend route layer: 12-metric expansion + /player-dd-history + /props/no-vig DD branch

**Status:** Implemented on `feature/SPO-26-backend-route-12metric-expansion`; awaiting Eason squash-merge into `dev`.
**Parent epic:** [SPO-10](/SPO/issues/SPO-10) — event-page-stat-expansion (Phase 3.5 — backend API-layer gap fix).
**Predecessors:** [SPO-16](/SPO/issues/SPO-16) (services-layer 12-metric + DD binary parser, commit `0e11d14`); [SPO-20](/SPO/issues/SPO-20) (frontend Phase 3, merged into `dev` via `e36cb57`).
**Branch:** `feature/SPO-26-backend-route-12metric-expansion` from `origin/dev`.

---

## What shipped

Backend-only. Frontend untouched (`git diff --name-only origin/dev...HEAD | grep ^frontend/` empty).

### `backend/app/models/schemas.py`

Additive schema diff only — no breaking renames or required→optional flips on existing fields:

- `BookmakerResult` — gains 6 optional/nullable binary-market mirrors (`yes_price`, `no_price`, `p_yes_imp`, `p_no_imp`, `yes_fair_prob`, `no_fair_prob`). Stay `None` for Over/Under markets; populated for binary markets (DD).
- `Consensus` — gains `p_yes_fair`, `p_no_fair` (Optional). Same convention as above.
- New `PlayerDDHistoryResponse` — `{player, season, n_games, dd_games, prob_dd, message}`. Mirrors the services-layer `csv_player_history.player_dd_history()` return shape.

### `backend/app/api/nba.py`

Three changes, all bounded:

1. **`valid_metrics` source-of-truth fix** (`get_player_history`). Replaced the hardcoded 4-element list with `sorted(CONTINUOUS_METRIC_EXTRACTORS.keys())`, imported directly from `csv_player_history`. The route now accepts the **11** continuous keys (`points, rebounds, assists, pra, threes_made, steals, ftm, fgm, ra, pr, pa`) and stays automatically in lockstep with the services-layer dispatch table — adding a new continuous metric to that dict flows through to the route without touching the route. The 422-on-`metric=dd` case now returns a friendly `400` with an explicit redirect to `/player-dd-history`, catching the most likely caller bug.

2. **New route: `GET /api/nba/player-dd-history`**. Query params: `player` (required), `season` (optional). Delegates to `csv_player_service.player_dd_history()` and surfaces the `prob_dd` / `dd_games` / `n_games` shape. The route does NOT expose a `threshold` param — the services-layer method explicitly rejects non-None threshold (DD is binary), so there's no entry point to wire one in by mistake.

3. **`/props/no-vig` DD branch**. New `_build_binary_no_vig_response` helper, dispatched via `if body.market in BINARY_MARKET_KEYS:` immediately after the player-match step. The Over/Under loop below is unchanged. Binary handling:
   - Outcomes matched on `name in {"yes", "no"}`, not Over/Under.
   - **Both legs posted** → vig derived directly from the leg pair (`calculate_vig` + `devig`). High-fidelity path.
   - **Single Yes leg posted** → `single_leg_devig(p_yes_imp, DEFAULT_BINARY_VIG)` applies the league-average prior. When the prior fails (extreme prices), THAT ROW IS NOT EMITTED — the response surfaces the omission via `message` rather than fabricating a fair-prob (decision §4 step 3).
   - Each emitted row populates **both** the new explicit binary fields AND the legacy `over_*`/`under_*` fields (with `over=Yes`, `under=No` semantic mapping and `line=0.5` sentinel — same convention as `odds_snapshot_service._parse_binary_market`). This keeps the existing frontend Zod parser passing without frontend code touched.

---

## Acceptance criteria — verification

| Criterion | Status |
|---|---|
| `nba.py` `valid_metrics` accepts all 11 continuous keys; 422 only on truly unknown metrics | ✅ smoke-tested 8 sample metrics — all return HTTP 200 |
| `metric=dd` returns helpful 400 pointing to `/player-dd-history` | ✅ explicit `hint` branch in route |
| `GET /player-dd-history` returns `prob_dd` from services layer | ✅ smoke test against real CSV: Nikola Jokic 75 games, 61 DDs, prob_dd=0.8133 |
| `/props/no-vig` returns non-null `yes_fair_prob` for DD when prior available; null otherwise (no fabrication) | ✅ honored as: emit row with computed `yes_fair_prob` when computable; OMIT row + surface in `message` when prior fails (stricter than literal "null", but more honest at the API boundary — see Trade-offs §1) |
| Existing 4-metric callers unaffected (regression on `points`/`rebounds`/`assists`/`pra`) | ✅ smoke test confirms `/props/no-vig` Over/Under path identical (line=24.5, p_over_fair=0.5000 on -110/-110); binary mirror fields stay `None` |
| Hit `/event/[eventId]` against a live NBA event in dev | ⚠ deferred — backend changes verified via TestClient + mocked snapshot. Live curl-against-dev verification belongs in the Phase 4 Sentinel ticket per SPO-26 §5 ("Sentinel test suite — separate Phase 4 ticket"). |
| No frontend code touched | ✅ `git diff --name-only origin/dev...HEAD | grep ^frontend/` empty |
| Existing pytest suite passes for affected modules | ✅ 139/139 pass in `test_csv_player_history.py` + `test_spo16_market_expansion.py`; 2 pre-existing failures in `test_prob.py` (Chinese-vs-English error string drift, unrelated to this ticket) |

### Smoke-test transcript (truncated)

```
Test 1: /player-history accepts new metrics
  points: 200, threes_made: 200, fgm: 200, ra: 200, pa: 200, pr: 200, steals: 200, ftm: 200

Test 3: /player-history with metric=dd points to /player-dd-history
  HTTP 400
  detail: Invalid metric: dd. Valid: [...] — DD is a binary outcome (Yes/No), not Over/Under. Use GET /api/nba/player-dd-history instead.

Test 4: /player-dd-history works
  HTTP 200
  body: {"player": "Nikola Jokic", "season": null, "n_games": 75, "dd_games": 61, "prob_dd": 0.8133, "message": null}

Test 5: /props/no-vig DD branch (mocked)
  results count: 2
    draftkings: line=0.5 yes_price=-250 no_price=200
      yes_fair_prob=0.6818 no_fair_prob=0.3182 (legacy: p_over_fair=0.6818)
    fanduel: line=0.5 yes_price=-240 no_price=None
      yes_fair_prob=0.6755 no_fair_prob=0.3245 (legacy: p_over_fair=0.6755)
  consensus: p_yes_fair=0.6787 p_over_fair=0.6787

Test 6: /props/no-vig OU branch unaffected
  draftkings: line=24.5 over=-110 under=-110 p_over_fair=0.5000
  binary mirrors should be None: yes_price=None yes_fair_prob=None
```

---

## Anti-hallucination guards (binding) — how they're enforced

1. **No fabricated `yes_fair_prob`.** When `single_leg_devig` returns None (extreme prices, prior cannot be safely applied), the route increments a counter and OMITS the row. The response message names the omission (`"Single-leg Yes posted by N bookmaker(s), but the league-average vig prior could not be safely applied; fair probability withheld (not fabricated)."`). Two-leg DD never needs the prior — vig is derived from the leg pair.
2. **No silent metric aliasing.** `valid_metrics` is `sorted(CONTINUOUS_METRIC_EXTRACTORS.keys())`, not a hand-maintained alias list. A metric not in the dispatch table returns 400 with the canonical list — never auto-rewritten. The `metric=dd` case is the one explicit hint we add (caller bug catcher), and even then it's a 400, not a redirect.
3. **No `point` value invented for DD.** `line=0.5` is documented as a sentinel both on the `BookmakerResult` schema docstring and in `_build_binary_no_vig_response`'s docstring. Consumers MUST dispatch on `body.market`, not interpret `0.5` as a real threshold.

---

## Trade-offs

1. **Single-leg DD with prior failure: row OMITTED, not emitted with `yes_fair_prob: null`.** A literal reading of §3 acceptance criterion ("returns non-null `yes_fair_prob` ... null otherwise") would suggest emitting a row with `yes_fair_prob: null`. I chose to omit because the existing `BookmakerResult` schema requires non-null `over_odds`/`under_odds`/`p_over_fair`/`p_under_fair` floats; emitting a row with `yes_fair_prob=null` would force me to either fabricate values for those legacy fields (violates anti-hallucination guard) or relax the schema to Optional (would break the frontend `bookmakerResultSchema.over_odds: z.number()` Zod parser, violating the "no frontend code touched" rule). Omitting + surfacing in `message` is the only path that satisfies all three constraints simultaneously. Volume note: in production this case is rare — `single_leg_devig` only returns None at extreme prices outside the band where the league-average prior is valid.

2. **Legacy `over_*`/`under_*` fields populated for DD via convention (`over=Yes`, `under=No`).** Mirrors `odds_snapshot_service._parse_binary_market`'s storage convention. Self-documenting `yes_*`/`no_*` mirrors are populated alongside, so SPO-26-aware callers can read explicit names. Not ideal — schema overloading is the cost of staying frontend-Zod-compatible — but consistent with the rest of the codebase.

3. **No live curl-against-dev test in this ticket.** Per ticket §5 ("Sentinel test suite — separate Phase 4 ticket"). Verification here is via `fastapi.testclient.TestClient` against a mocked `odds_gateway` plus the real CSV. SPO-26's anti-hallucination policy requires integration tests behind `RUN_INTEGRATION=1` for any new external API client — this ticket does NOT add any such client (it consumes the existing `odds_gateway`), so no new integration test is needed at this layer.

4. **`valid_metrics` imports `CONTINUOUS_METRIC_EXTRACTORS` directly** rather than wrapping it in a `valid_metric_keys()` helper. Direct import is the smaller diff and keeps the dispatch table as the single, obvious source of truth. A helper would add indirection without changing behavior.

---

## How to verify locally

```bash
# 1. Branch + service-layer regression
cd backend
.venv/bin/python -m pytest tests/test_csv_player_history.py tests/test_spo16_market_expansion.py \
    --deselect tests/test_prob.py::TestAmericanToProb::test_zero_odds_raises_error \
    --deselect tests/test_prob.py::TestDevig::test_zero_sum_raises_error -q
# expect: 139 passed (2 deselects unrelated to SPO-26)

# 2. Quick route smoke test (rate-limiter disabled, mocked odds_gateway)
.venv/bin/python <<'PY'
import os; os.environ.update({"ODDS_API_KEY":"T","OPENAI_API_KEY":"T","DATABASE_URL":"postgresql+asyncpg://t:t@localhost/t"})
from app.middleware import rate_limit; rate_limit.limiter.enabled = False
from fastapi import FastAPI; from fastapi.testclient import TestClient
from app.api.nba import router
app = FastAPI(); app.include_router(router); c = TestClient(app)
print(c.get("/api/nba/player-dd-history?player=Nikola+Jokic").json())
PY

# 3. Full live verification (deferred to Phase 4 Sentinel ticket):
#    curl http://localhost:8000/api/nba/player-history?player=Stephen+Curry&metric=threes_made&threshold=2.5
#    curl http://localhost:8000/api/nba/player-dd-history?player=Nikola+Jokic
#    curl -X POST http://localhost:8000/api/nba/props/no-vig -d '{"event_id":"...","player_name":"Nikola Jokic","market":"player_double_double"}'
```

---

## Branch + PR

- Branch: `feature/SPO-26-backend-route-12metric-expansion` (off `origin/dev`).
- PR target: `dev`.
- Merge: squash by Eason.

## Follow-ups (out of scope for this ticket)

- Phase 4 Sentinel: integration tests against live `/event/[eventId]` flow with all 12 tiles + DD round-trip.
- Frontend follow-up (post-merge): wire `PlayerDDTile` props to call `/player-dd-history` and read the new `yes_*`/`no_*` fields from `/props/no-vig` results. Today the tile renders all-null placeholders.
- Optional polish: add `BINARY_MARKET_KEYS` to a centralized `markets.py` constants module (currently lives in `odds_snapshot_service`), so the route layer doesn't have a service-layer import for a constants-only need. Not blocking.
