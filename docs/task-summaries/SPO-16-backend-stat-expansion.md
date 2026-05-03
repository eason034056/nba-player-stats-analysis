# SPO-16 — Forge backend stat expansion (Phase 2B)

**Status:** must-fix addressed (SPO-17) — re-review pending · **Branch:** `feature/SPO-16-backend-stat-expansion`
**Parent epic:** [SPO-10](/SPO/issues/SPO-10) · **Plan:** [SPO-11 v3](/SPO/issues/SPO-11#document-plan)
**Decision log:** `docs/decisions/event-page-stat-expansion/decision_20260502_market-key-feasibility.md` (Phase 1.5 + Addendum 1)

---

## What

Extended the backend's stat-type plumbing so the event page can offer **8 new player prop markets** end-to-end (odds snapshot, historical probability, projection):

| Stat | Market key | Type | Phase 1 status |
|---|---|---|---|
| 3PM | `player_threes` | Single Over/Under | hard-supported, populated today |
| STL | `player_steals` | Single Over/Under | hard-supported, populated today |
| FTM | `player_frees_made` | Single Over/Under | graceful-degrade (currently empty) |
| FGM | `player_field_goals` | Single Over/Under | graceful-degrade (currently empty); FGM hypothesis pending live disambiguation |
| R+A | `player_rebounds_assists` | Native combo Over/Under | hard-supported, populated today |
| P+R | `player_points_rebounds` | Native combo Over/Under | hard-supported, populated today |
| P+A | `player_points_assists` | Native combo Over/Under | hard-supported, populated today |
| DD  | `player_double_double` | Binary Yes/No (separate parser path) | hard-supported, populated today |

Total `SNAPSHOT_MARKETS`: **4 → 12**. Total `SUPPORTED_MARKETS` (Over/Under flow): 4 → 11. New `BINARY_MARKETS` list: 1 (DD).

3PA explicitly NOT added — no API path per Scout §3.5 + docs cross-check.

---

## Why

Drives the SPO-10 epic deliverable: the event page selector goes from 4 stat types to 12, matching the original product ask. Every market key in this PR is curl-evidenced in Scout's research (`docs/research/event-page-stat-expansion/research_odds_api_markets.md`) — none are guessed, none are renamed, none are "improved." The DD binary parser path is a structural requirement, not a stylistic one: forcing DD through the Over/Under code path produces silently wrong probabilities, which decision §4 calls out as a `[Major]` correctness bug.

---

## How

### 1. Constants — single source of truth (acceptance criterion 1)

- `backend/app/services/odds_snapshot_service.py:43-100` — `SNAPSHOT_MARKETS` extended; new sets `OVER_UNDER_MARKET_KEYS` (11 entries) and `BINARY_MARKET_KEYS` (1 entry: DD) split out so the parser can dispatch by market type without hardcoded magic strings.
- `backend/app/services/daily_analysis.py:41-95` — `SUPPORTED_MARKETS` extended from 4 tuples to 11 (no DD — it's binary, lives in the new `BINARY_MARKETS`). New `PROJECTION_FIELD_ALIASES` map translates CSV metric keys (`threes_made`) to SportsDataIO projection field names (`three_pointers_made`) so the edge column populates for new metrics.
- `backend/app/api/odds_history.py:25-145` — allow-list now imports the canonical sets from `odds_snapshot_service` (no duplicate hardcoded list).

### 2. Combo derived fields in projection_provider (acceptance criterion 7)

- `backend/app/services/projection_provider.py:367-405` — `normalize_projection()` now exposes `r_a`, `p_r`, `p_a` alongside the existing `pra`. **No `dd` field added** — DD ML projection is Phase 2 scope (decision §4 step 4).
- `FreeThrowsMade` / `FieldGoalsMade` were already in `FIELD_MAPPING`; verified they surface as `free_throws_made` / `field_goals_made` in the normalized output (test in `test_spo16_market_expansion.py::TestNormalizeProjectionDerivedFields`).

### 3. Historical-metric extension (acceptance criterion 8)

- `backend/app/services/csv_player_history.py:24-100` — new module-level `CONTINUOUS_METRIC_EXTRACTORS` dispatch table maps each metric key to a per-game-row extractor. Adding a future metric is now a one-line addition.
- `backend/app/services/csv_player_history.py:540-560` — `get_player_stats()` consults the dispatch table; falls back to direct `game[key]` lookup for legacy callers.
- `backend/app/services/csv_player_history.py:618-720` — **new** `player_dd_history(player_name, season=None) -> dict` method. DD is a `≥2 of {PTS, REB, AST, STL, BLK} ≥ 10` count over DNP-excluded games. **Rejects non-null `threshold`** with a `ValueError` (binary metric, threshold meaningless).

### 4. DD binary parser (acceptance criterion 2 + 3)

- `backend/app/services/prob.py:111-160` — **new** `single_leg_devig(p_implied, assumed_vig=DEFAULT_BINARY_VIG)`. Used when only `Yes` is posted; refuses to publish (returns `None`) when the prior cannot be safely applied. Constant `DEFAULT_BINARY_VIG = 0.045` documented as a league-average prior (decision §4.3).
- `backend/app/services/odds_snapshot_service.py:325-460` — **new** `_parse_binary_market()` method. Dispatch in `_process_event` routes DD outcomes to it; the standard Over/Under loop never sees them. When both Yes and No prices are posted, derives vig from the leg pair (preferred). When only Yes is posted, applies the league-average prior. When the prior fails or only `No` is posted (no anchor), refuses to publish a fair-prob.
- DD storage uses `line=0.5` as a sentinel (DD has no real `point` field). Frontend/API consumers must dispatch on `market` and ignore `line` for binary markets — documented inline at the parser definition.
- **Grep proof:** `compute_over_probability` does not exist anywhere in the codebase; `_parse_binary_market` is the only DD code path. Asserted by `test_spo16_market_expansion.py::TestDdBinaryParser::test_grep_no_over_under_compute_for_dd`.

### 5. FTM / FGM graceful-degrade (acceptance criterion 4)

No special-cased "if empty" branch needed — the existing parser flow handles it for free:

- `_get_props_for_market()` returns `data.get("bookmakers", [])` which is `[]` when inventory is empty.
- `_group_props_by_player()` returns `{}` for `[]`, so `_analyze_single_event` simply contributes nothing to the day's picks for that market — no fake number is ever published.
- For the snapshot path, `for bookmaker in []:` runs zero iterations, no rows written.

Verified by inspection. The frontend (separate ticket) is responsible for rendering "no bookmaker line right now" tile copy when the response carries no odds for a given market.

### 6. Tests

- **Unit** (`backend/tests/test_spo16_market_expansion.py`, **45 tests, 100% pass**):
  - constants — single source of truth, sets are disjoint, union covers SNAPSHOT_MARKETS, no 3PA leak
  - 7 new continuous metrics behave exactly like the existing 4 (probability arithmetic on a fixed CSV)
  - `player_dd_history` — shape, threshold-rejection, exact `dd_games` count vs hand-computed truth, fuzzy match, season filter, DNP exclusion
  - `single_leg_devig` — basic algebra, custom vig, bad-input return-None, default vig matches the documented prior
  - DD binary parser — Yes-only/Yes+No paths, no-Yes-anchor skip, sentinel line=0.5
  - `normalize_projection` — `r_a`/`p_r`/`p_a` present, `dd` absent, FieldGoalsMade/FreeThrowsMade surface
  - alias map — `threes_made`/`ftm`/`fgm` aliased correctly; `ra`/`pr`/`pa` intentionally not aliased
- **Integration** (`backend/tests/test_spo16_integration.py`, gated behind `RUN_INTEGRATION=1`, 0 cost when gated):
  - `test_player_threes_returns_populated_payload` — Tier-A live hit (`CLAUDE.md § External API Wrappers` rule #2), asserts outcome shape
  - `test_player_field_goals_disambiguation_fgm_signature` — SPO-16 §4: skips on empty inventory; on populated, asserts `median(point) < 10` (FGM signature). Failure message instructs the runner to escalate to CTO with the saved sample at `/tmp/spo16_player_field_goals_populated.json`.

### 7. Existing-test impact

- `tests/test_daily_analysis.py::TestAnalyzeSingleEvent::test_returns_player_team_and_edge_with_projections` had `assert prop_count == 4` — that count was implicitly the size of `SUPPORTED_MARKETS`. Updated to `assert prop_count == len(SUPPORTED_MARKETS) == 11` and now references the canonical constant. **No contract break for the original 4 metrics** — they still pass through the same flow with identical behavior; only the count moved.

---

## Testing

### Local pytest snapshot

```
tests/test_spo16_market_expansion.py        45 passed
tests/test_spo16_integration.py              skipped (RUN_INTEGRATION not set)
tests/test_csv_player_history.py             68 passed
tests/test_daily_analysis.py                 16 passed (1 expected count update)
tests/test_projection_provider.py             8 passed
tests/test_odds_snapshot.py                  21 passed
tests/test_prob.py                            2 pre-existing failures (Chinese-vs-English regex mismatch on test side, NOT caused by this PR — verified by inspection of `prob.py:36, 102` raise statements which already used English before this PR)
```

Targeted: **247 passed, 1 skipped, 2 pre-existing failures** (`test_prob.py` Chinese localization mismatch — unrelated).

### Live integration (manual, opt-in only)

```bash
RUN_INTEGRATION=1 .venv/bin/pytest backend/tests/test_spo16_integration.py -v
```

Cost: ≤ 2 quota units (1 for `player_threes`, 1 for `player_field_goals` if populated; 0 if empty). Run before merge.

### Sanity grep

```
$ grep -r "compute_over_probability" backend/ scripts/
# (no matches — only referenced as a hypothetical "wrong path" in docs/)
```

---

## Trade-offs

1. **DD storage uses `line=0.5` sentinel.** The `odds_line_snapshots` table has a `line FLOAT` column that's NOT NULL in the production schema (per the existing UPSERT pattern). Adding a separate `binary_lines` table or a `line_kind` column would have been cleaner but requires a migration. We use `0.5` as a sentinel and require consumers to dispatch on `market`. Documented inline at `_parse_binary_market`. If this becomes painful (e.g., line-movement charts try to plot 0.5 values), the next pass should add a `line_kind` column.

2. **FTM/FGM in `SUPPORTED_MARKETS` even though currently empty.** Per Override 1 of decision Addendum 1. The `bookmakers: []` empty-state propagates harmlessly (no rows written, no fake numbers). When inventory eventually populates, the tile lights up automatically without code change.

3. **Single-leg de-vig uses a 4.5% prior.** Documented in `prob.py:DEFAULT_BINARY_VIG` with the source. Returns `None` when the prior fails (per decision §4 step 3: "Do NOT publish a fair probability if vig cannot be estimated"). Two-leg de-vig is preferred whenever Both legs are posted.

4. **No `dd` projection field.** Decision §4 step 4 explicitly leaves DD ML projection to Phase 2. Frontend tiles render "ML projection N/A (Phase 2)" — backend response simply doesn't carry one.

5. **Pre-existing `test_prob.py` failures left in place.** Two tests assert Chinese error-message regexes against `prob.py` which has always raised English error strings. These are pre-existing and unrelated to this PR. Out of scope per ticket §7 (Sentinel pass).

---

## Out of scope (left for later tickets, per ticket §7)

- Frontend changes — `MarketSelect.tsx`, `PlayerHistoryStats.tsx`, `lib/schemas.ts` are Forge frontend (Phase 3, separate ticket).
- Sentinel full integration test suite — Phase 4. The two integration tests in this PR are minimum hygiene per `CLAUDE.md` rules, not full Sentinel coverage.
- Quota plan upgrade negotiation — handled by CTO/CEO out-of-band per Override 2.
- Cadence audit — that's [SPO-15](/SPO/issues/SPO-15), running in parallel; does NOT block this ticket.
- DD ML projection — Phase 2 per Phase-0 decision §4 + Phase-1.5 decision §4 step 4.
- 3PA / FGA-attempted — no API path; explicitly NOT added.

---

## Files touched

| File | Lines added | Lines removed |
|---|---|---|
| `backend/app/services/odds_snapshot_service.py` | +220 | -7 |
| `backend/app/services/csv_player_history.py` | +200 | -3 |
| `backend/app/services/daily_analysis.py` | +60 | -8 |
| `backend/app/services/prob.py` | +68 | -0 |
| `backend/app/services/projection_provider.py` | +35 | -6 |
| `backend/app/api/odds_history.py` | +28 | -7 |
| `backend/tests/test_daily_analysis.py` | +9 | -3 |
| `backend/tests/test_spo16_market_expansion.py` | +new (~365) | — |
| `backend/tests/test_spo16_integration.py` | +new (~165) | — |
| `docs/task-summaries/SPO-16-backend-stat-expansion.md` | +new | — |

---

## Next-action signal

CTO can:
1. Open the Forge-frontend Phase 3 ticket — backend contract is now stable for `MarketSelect.tsx` to consume the 12 markets + binary DD shape.
2. Schedule the FGM disambiguation integration test to run on the next event with populated `player_field_goals` inventory. If it fails the `median(point) < 10` assertion, the next-action is plan v4 with a "FGA-attempted historical-only UX class" path (per Override 3).

---

## Lens review (2026-05-02)

### Verdict: NEEDS CHANGES

One concrete edge-calculation bug for 3 of the 7 new continuous markets (R+A, P+R, P+A) — `daily_analysis` looks up combo projections with the wrong key, so `edge` and `projected_value` will be silently `None` for every pick on those three markets even when the projection is fully populated. Everything else is solid: the constants/dispatch split is clean, the DD binary path is genuinely separate (grep-verified), `single_leg_devig` math checks out, and the integration tests + exploration script satisfy the External-API-Wrappers anti-hallucination policy.

### Must-fix

- **`backend/app/services/daily_analysis.py:86-91` — `PROJECTION_FIELD_ALIASES` is missing `ra → r_a`, `pr → p_r`, `pa → p_a`.** `projection_provider.normalize_projection()` writes the underscored keys (`projection_provider.py:386,391,396`); `daily_analysis._analyze_single_event()` reads with `proj.get(metric_key)` where `metric_key ∈ {"ra","pr","pa"}`. Reproduced live:

  ```
  market=player_rebounds_assists  metric=ra -> proj_field=ra  value=None   ← projection has "r_a"=15.0
  market=player_points_rebounds   metric=pr -> proj_field=pr  value=None   ← projection has "p_r"=28.0
  market=player_points_assists    metric=pa -> proj_field=pa  value=None   ← projection has "p_a"=27.0
  ```

  Net effect: every R+A / P+R / P+A pick will publish with `edge=None` and `projected_value=None`, defeating the value-edge component for the new combo markets. Acceptance criterion 7 is met at the projection layer but broken at the consumption layer.

  Fix: add the three entries to `PROJECTION_FIELD_ALIASES` and **delete or invert** `test_spo16_market_expansion.py::TestProjectionFieldAliases::test_combos_not_aliased` (lines 530–534) — that test currently codifies the bug as a "feature" by asserting the absence of the very aliases that need to exist. Add a positive assertion: walk every `(market, metric)` in `SUPPORTED_MARKETS`, run a sample raw payload through `normalize_projection()`, and confirm `proj.get(PROJECTION_FIELD_ALIASES.get(metric, metric)) is not None` for every metric whose components were provided. That single test would have caught this.

### Suggestions

- **`backend/app/services/odds_snapshot_service.py:389-401` — tighten the dispatcher.** `if market_key in BINARY_MARKET_KEYS: ... else: <Over/Under>` falls through to the OU parser for any unknown market key. Today this is safe because `SNAPSHOT_MARKETS` is the only writer, but a typo in a future market addition would produce silent `point=None` rows. Prefer `elif market_key in OVER_UNDER_MARKET_KEYS: ... else: log.warning("unknown market key %s", market_key); continue`. Test `test_union_covers_all_snapshot_markets` already enforces the invariant on the constants side; this would enforce it on the runtime side too.
- **`backend/app/services/prob.py:174` — `single_leg_devig` docstring example output `0.5933` is shown with `# rounds vary` but the function returns the unrounded float; the actual return is `0.5933014...`. Either round in the function or correct the example to match the unrounded result. Cosmetic.
- **`backend/app/services/odds_snapshot_service.py:494-500` — `line=0.5` sentinel for DD.** Accepted in trade-offs §1, but the docstring's "Frontend/API consumers must dispatch on `market` and ignore `line` for binary markets" is an unenforced invariant. A `line_kind` enum or making `line` nullable in a follow-up migration would be safer; for now, please add a `# pragma: SPO-17 follow-up — replace 0.5 sentinel with line_kind column` marker so the deferred work is grep-able.

### Praise

- **DD parser separation is real, not nominal.** The `_parse_binary_market` method, the `BINARY_MARKET_KEYS` frozenset, the dispatch site, and the `test_grep_no_over_under_compute_for_dd` regression-guard collectively make it structurally impossible to silently funnel DD through the OU parser. This is exactly the discipline decision §4 demanded.
- **`player_dd_history` rejecting non-null `threshold` with a `ValueError`** instead of silently dropping is the right call — surfaces the misuse loudly. Good docstring `⚠`.
- **Single source of truth for the 12-market set.** `odds_history.py` importing `OVER_UNDER_MARKET_KEYS | BINARY_MARKET_KEYS` from the snapshot service kills the duplicate-allow-list class of bug. Extending the markets set is now a one-place change.
- **`single_leg_devig` returns `None` for pathological inputs** rather than fabricating a probability — exactly the discipline decision §4 step 3 mandates.

### Patterns observed

- Strategy / dispatch table (`CONTINUOUS_METRIC_EXTRACTORS` in `csv_player_history.py`)
- Dispatcher by type-tag (`BINARY_MARKET_KEYS` vs `OVER_UNDER_MARKET_KEYS`)
- Defensive sentinel + invariant doc (`line=0.5` for DD with explicit "consumers must dispatch on `market`" contract)
- Negative invariant guarded by source-grep test (`test_grep_no_over_under_compute_for_dd`)
- Anti-hallucination layered defence (exploration script + RUN_INTEGRATION-gated live test + skip-on-empty + escalate-on-failure-with-saved-sample)

### Fixture grounding check: PASS

- New external API surface in this PR: extension of existing `OddsGateway.get_market_snapshot()` call with a longer `markets=` string. No new client.
- `scripts/explore_odds_api_extensions.py` — present (CLAUDE.md rule #1).
- `backend/tests/test_spo16_integration.py::test_player_threes_returns_populated_payload` — RUN_INTEGRATION-gated live hit on a Tier-A market new in this ticket (CLAUDE.md rule #2). Asserts the full outcome shape the parser depends on.
- `backend/tests/test_spo16_integration.py::test_player_field_goals_disambiguation_fgm_signature` — additional live probe with a populated-vs-empty branch and an escalate-to-CTO message that pins the next-action if FGM hypothesis fails.
- `docs/research/event-page-stat-expansion/research_odds_api_markets.md` — Scout's curl-evidenced research already cited in the task summary (CLAUDE.md rule #3).
- Unit tests construct synthetic CSVs and inline payload dicts rather than loading from `tests/fixtures/`. Acceptable here because the unit tests cover deterministic logic on synthetic input sets, not parser-of-known-external-response — and the integration test does exercise the live wire format.

### Out-of-scope observations (not blocking)

- `test_prob.py` carries 2 pre-existing failures (Chinese localization regex vs English raise messages). Forge correctly flagged this as pre-existing in the task summary §Trade-offs item 5; out of scope per ticket §7. Sentinel can decide whether to file a separate cleanup ticket.

---

## SPO-17 Forge fix (2026-05-02)

### What changed

- `backend/app/services/daily_analysis.py:86-99` — added `ra → r_a`, `pr → p_r`, `pa → p_a` to `PROJECTION_FIELD_ALIASES`, replaced the stale comment with a `⚠`-flagged invariant note that ties the alias map to `normalize_projection`'s underscored derived keys.
- `backend/tests/test_spo16_market_expansion.py` — replaced `test_combos_not_aliased` (which codified the bug) with two positive checks:
  - `test_combos_aliased` — direct assertion that the three new aliases exist with the correct underscored target.
  - `test_every_supported_market_metric_resolves_in_projection` — walks every `(market, metric)` in `SUPPORTED_MARKETS`, runs a fully-populated synthetic raw payload through `normalize_projection()`, and asserts `proj.get(PROJECTION_FIELD_ALIASES.get(metric, metric)) is not None`. This is the single test that would have caught the original bug, and it will catch any future combo / single-stat addition that forgets its alias.

### Verification

- `pytest backend/tests/test_spo16_market_expansion.py backend/tests/test_daily_analysis.py -v` → **106 passed, 1 warning** (Pydantic v2 class-Config deprecation, pre-existing).
- Live reproduction (mirrors Lens's failing snippet, post-fix):
  ```
  market=player_rebounds_assists  metric=ra -> proj_field=r_a  value=15
  market=player_points_rebounds   metric=pr -> proj_field=p_r  value=33
  market=player_points_assists    metric=pa -> proj_field=p_a  value=32
  ```
  All three combos now resolve to non-None values, so `edge = projected_value - mode_threshold` will compute correctly for every R+A / P+R / P+A pick.

### Suggestions deferred to a follow-up

The three Lens `[SUGGESTION]` items (`odds_snapshot_service` dispatcher tightening, `single_leg_devig` docstring rounding, SPO-17 sentinel TODO marker) are intentionally not in this commit — keeping the fix surgical so re-review is fast. CTO can fold them into a follow-up ticket or wave them in at next epic close.

### Handoff

Branch ready for Lens re-review on the must-fix only. No new commits expected from Forge until Lens responds.
