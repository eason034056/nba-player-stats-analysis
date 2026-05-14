# Odds API WNBA player-prop market verification (Phase 0)

- **Ticket:** [SPO-31](/SPO/issues/SPO-31) — Phase 0 of [SPO-29](/SPO/issues/SPO-29) (wnba-rollout)
- **Agent:** Scout (`1a495f58-b689-46b7-9e79-9d563b31175d`)
- **Date:** 2026-05-13
- **Outcome (Gate behaviour):** ✅ **Row 2 — "Some `hard-supported`, some `schema-valid+empty`."** All 3 core markets pass the gate; 3 of 12 (`player_steals`, `player_blocks`, `player_turnovers`) returned populated schema with `bookmakers=[]`.
- **2026-05-14 follow-up:** `player_frees_made` (FTM) and `player_field_goals` (FGM) added as Phase 0.5 probes by Forge during SPO-33 Lens review (see §3.2.4 + §4). Both classified `schema-valid+empty`. Total verified market count now 14 (10 `hard-supported` + 5 `schema-valid+empty` + 0 `not-in-schema`).

Companion script: `scripts/explore_odds_api_wnba.py` — re-run on demand to detect schema drift.

---

## 1. What this doc proves

Per `CLAUDE.md § External API Wrappers` rules #1 and #3, every claim about a real external API in this codebase must be backed by **(a) the curl that was actually run** and **(b) the first ~500 bytes of the response body**. This doc satisfies both for `basketball_wnba` on The Odds API v4, so subsequent WNBA phases (SPO-32 Forge backend, SPO-35 Sentinel integration tests) can build on verified ground truth rather than assumed schema.

> ⚠ The API key is redacted as `${ODDS_API_KEY}` throughout. Real responses were captured against the actual key on **2026-05-13** with `ODDS_API_BASE_URL=https://api.the-odds-api.com`. Raw bodies are saved to `/tmp/odds_wnba_<label>.json` after a script run.

## 2. Endpoints exercised

Two endpoint paths were exercised:

1. `GET /v4/sports/basketball_wnba/events` — free (`x-requests-last: 0`), used to find live event ids.
2. `GET /v4/sports/basketball_wnba/events/{eventId}/odds?regions=us&markets=<key>&oddsFormat=american` — per-market probe, 1 unit per populated market (per the SPO-12 NBA-side billing measurement; identical billing model observed on WNBA).

Path shape is identical to the NBA-side endpoints — the only difference is the sport key (`basketball_wnba` vs `basketball_nba`). No new authentication or query-parameter surface required.

## 3. Curl evidence

### 3.1 `/events` — events listing

**Command:**

```bash
curl -sS "https://api.the-odds-api.com/v4/sports/basketball_wnba/events?apiKey=${ODDS_API_KEY}" \
  | head -c 500
```

**Response (first ~500 bytes, raw, taken at 2026-05-13 ~17:00 UTC):**

```json
[{"id":"efb5e7faabc4ea9406b9b479ae805b38","sport_key":"basketball_wnba","sport_title":"WNBA","commence_time":"2026-05-13T23:00:00Z","home_team":"Toronto Tempo","away_team":"Seattle Storm"},{"id":"8d60431e967888aecd9f44a9419e0fd6","sport_key":"basketball_wnba","sport_title":"WNBA","commence_time":"2026-05-14T00:00:00Z","home_team":"Connecticut Sun","away_team":"Las Vegas Aces"},{"id":"5a8f677103c076b790518817973162fe","sport_key":"basketball_wnba","sport_title":"WNBA","commence_time":"2026-05-14T
```

**Headers:** `HTTP 200`, `x-requests-last: 0` (free), `x-requests-used: 160 → 160` (no change).

**Captured event ids for Phase 2 integration test reuse** (commit these into the SPO-35 fixture once Sentinel writes the integration test):

| event_id | matchup | commence_time (UTC) |
|---|---|---|
| `efb5e7faabc4ea9406b9b479ae805b38` | Seattle Storm @ Toronto Tempo | 2026-05-13T23:00:00Z |
| `8d60431e967888aecd9f44a9419e0fd6` | Las Vegas Aces @ Connecticut Sun | 2026-05-14T00:00:00Z |
| `5a8f677103c076b790518817973162fe` | Chicago Sky @ Golden State Valkyries | 2026-05-14T02:00:00Z |
| `9eb12a90128ff851c6046262b5c96292` | Indiana Fever @ Los Angeles Sparks | 2026-05-14T02:30:00Z |
| `dba1abeae3af736af155c7d406fb8e8b` | Minnesota Lynx @ Dallas Wings | 2026-05-15T00:00:00Z |
| `a256f82fff219346ff7ef9220053e452` | New York Liberty @ Portland Fire | 2026-05-15T02:00:00Z |

Six upcoming events on the API, including two newly-formed expansion teams (Toronto Tempo, Portland Fire, Golden State Valkyries) — confirms the WNBA dataset is current as of the 2026 season.

### 3.2 `/events/{eventId}/odds` — per-market probes

The script anchored on `event_id = efb5e7faabc4ea9406b9b479ae805b38` (Seattle Storm @ Toronto Tempo) for all 12 probes. One probe per market so each classification is independently observable (a multi-market URL would hide which specific key was empty vs schema-valid).

#### 3.2.1 `hard-supported` example — `player_points`

**Command:**

```bash
curl -sS "https://api.the-odds-api.com/v4/sports/basketball_wnba/events/efb5e7faabc4ea9406b9b479ae805b38/odds?regions=us&markets=player_points&oddsFormat=american&apiKey=${ODDS_API_KEY}" \
  | head -c 500
```

**Response (first ~500 bytes, raw):**

```json
{"id":"efb5e7faabc4ea9406b9b479ae805b38","sport_key":"basketball_wnba","sport_title":"WNBA","commence_time":"2026-05-13T23:00:00Z","home_team":"Toronto Tempo","away_team":"Seattle Storm","bookmakers":[{"key":"fanduel","title":"FanDuel","markets":[{"key":"player_points","last_update":"2026-05-13T17:01:08Z","outcomes":[{"name":"Over","description":"Flau'jae Johnson","price":-108,"point":14.5},{"name":"Under","description":"Flau'jae Johnson","price":-120,"point":14.5},{"name":"Over","description":"
```

**Headers:** `HTTP 200`, `x-requests-last: 1`, `x-requests-used: 160 → 161`. Three bookmakers populated (FanDuel + 2 others observed in the full body).

**Shape match with NBA:** identical — `bookmakers[*].markets[*].outcomes[*]` with `name ∈ {Over, Under}`, `description` = player name, `price` = American odds, `point` = line. No new parsing branch required in Forge's Phase-2 WNBA path; the existing NBA Over/Under parser (`backend/app/services/odds_snapshot_service.OVER_UNDER_MARKET_KEYS`) will work as-is.

#### 3.2.2 `schema-valid+empty` example — `player_steals`

**Command:**

```bash
curl -sS "https://api.the-odds-api.com/v4/sports/basketball_wnba/events/efb5e7faabc4ea9406b9b479ae805b38/odds?regions=us&markets=player_steals&oddsFormat=american&apiKey=${ODDS_API_KEY}" \
  | head -c 500
```

**Response (full body — well under 500 bytes):**

```json
{"id":"efb5e7faabc4ea9406b9b479ae805b38","sport_key":"basketball_wnba","sport_title":"WNBA","commence_time":"2026-05-13T23:00:00Z","home_team":"Toronto Tempo","away_team":"Seattle Storm","bookmakers":[]}
```

**Headers:** `HTTP 200`, `x-requests-last: 0` (cost: 0 — the empty-bookmakers shape is unbilled, same NBA-side behaviour as `player_field_goals` per SPO-12). `x-requests-used` was unchanged.

This is the same `[schema-valid-no-current-inventory]` shape the NBA side has been handling since SPO-12 for FTM and FGM. **Forge can reuse the existing graceful-degrade UI path on WNBA without code changes** — the snapshot writer accepts an empty `bookmakers` array as "no line posted yet," and the picks endpoint already silently drops markets that have no live lines.

#### 3.2.3 Binary market example — `player_double_double`

**Command:**

```bash
curl -sS "https://api.the-odds-api.com/v4/sports/basketball_wnba/events/efb5e7faabc4ea9406b9b479ae805b38/odds?regions=us&markets=player_double_double&oddsFormat=american&apiKey=${ODDS_API_KEY}" \
  | head -c 500
```

**Response (first ~500 bytes):**

```json
{"id":"efb5e7faabc4ea9406b9b479ae805b38","sport_key":"basketball_wnba","sport_title":"WNBA","commence_time":"2026-05-13T23:00:00Z","home_team":"Toronto Tempo","away_team":"Seattle Storm","bookmakers":[{"key":"fanduel","title":"FanDuel","markets":[{"key":"player_double_double","last_update":"2026-05-13T17:01:08Z","outcomes":[{"name":"Yes","description":"Dominique Malonga","price":100},{"name":"Yes","description":"Nyara Sabally","price":1000},{"name":"Yes","description":"Flau'jae Johnson","price":
```

**Headers:** `HTTP 200`, `x-requests-last: 1`. Two bookmakers (FanDuel + DraftKings observed in full body).

**Shape match with NBA's DD parser:** identical — `name=Yes` outcomes with `price` only and **no `point` field**. The WNBA DD path can reuse `BINARY_MARKET_KEYS` from `odds_snapshot_service.py` unchanged. Note: in this snapshot only `Yes` legs are present; if `No` legs surface intermittently in later snapshots, the NBA-side handler already tolerates both — no special-casing needed.

#### 3.2.4 Follow-up probes — `player_frees_made` (FTM) + `player_field_goals` (FGM)

**Added 2026-05-14 by Forge during SPO-33 Lens review.** Originally skipped in §6 because the two keys were not in the SPO-31 ticket §Scope list. Lens flagged them as **anti-hallucination unverified** — the shared frontend `MarketSelect` exposes 12 tiles, two of which were FTM/FGM, and the WNBA route accepts `body.market` as pass-through. Verifying both on the live API closes the gap without any UI gating change.

The Phase 0 anchor event (`efb5e7faabc4ea9406b9b479ae805b38`, Storm @ Tempo, 2026-05-13T23:00:00Z) had concluded by the follow-up run, so the helper script `scripts/explore_odds_api_wnba_ftm_fgm.py` auto-fell-back to the next live event: `9eb12a90128ff851c6046262b5c96292` (Indiana Fever @ Los Angeles Sparks, 2026-05-14T02:38:00Z UTC).

**Command — FTM:**

```bash
curl -sSi "https://api.the-odds-api.com/v4/sports/basketball_wnba/events/9eb12a90128ff851c6046262b5c96292/odds?regions=us&markets=player_frees_made&oddsFormat=american&apiKey=${ODDS_API_KEY}"
```

**Response (full body — under 500 bytes):**

```json
{"id":"9eb12a90128ff851c6046262b5c96292","sport_key":"basketball_wnba","sport_title":"WNBA","commence_time":"2026-05-14T02:38:00Z","home_team":"Los Angeles Sparks","away_team":"Indiana Fever","bookmakers":[]}
```

**Headers — FTM:** `HTTP 200`, `x-requests-last: 0` (unbilled — same `schema-valid+empty` shape as `player_steals` / `player_blocks` / `player_turnovers`), `x-requests-used: 199 → 199`.

**Command — FGM:**

```bash
curl -sSi "https://api.the-odds-api.com/v4/sports/basketball_wnba/events/9eb12a90128ff851c6046262b5c96292/odds?regions=us&markets=player_field_goals&oddsFormat=american&apiKey=${ODDS_API_KEY}"
```

**Response (full body — under 500 bytes):**

```json
{"id":"9eb12a90128ff851c6046262b5c96292","sport_key":"basketball_wnba","sport_title":"WNBA","commence_time":"2026-05-14T02:38:00Z","home_team":"Los Angeles Sparks","away_team":"Indiana Fever","bookmakers":[]}
```

**Headers — FGM:** `HTTP 200`, `x-requests-last: 0`, `x-requests-used: 199 → 199`.

**Classification (both):** `schema-valid+empty`. The WNBA sport key accepts both market keys, the response is well-formed (`bookmakers: []`), and the call is unbilled — identical Tier-B graceful-degrade contract as NBA-side FTM/FGM and as WNBA `player_steals`/`blocks`/`turnovers`. The existing SPO-26 empty-bookmakers UX guard handles them without code change.

**Total cost of this follow-up:** 0 paid units (both probes unbilled; `/sports` quota readback also free).

## 4. Support table (14 markets verified — 12 in SPO-31 ticket scope + 2 in SPO-33 follow-up)

| # | Market key | Classification | Bookmakers (snapshot) | Notes / Forge implication |
|---|---|---|---|---|
| 1 | `player_points` | **hard-supported** | 3 | Core. Identical Over/Under shape to NBA. |
| 2 | `player_rebounds` | **hard-supported** | 3 | Core. |
| 3 | `player_assists` | **hard-supported** | 3 | Core. |
| 4 | `player_threes` | **hard-supported** | 3 | Tier-A on NBA side too. |
| 5 | `player_steals` | `schema-valid+empty` | 0 | Same UX as NBA FTM/FGM empty path — graceful-degrade tile, no code change. |
| 6 | `player_blocks` | `schema-valid+empty` | 0 | Same as above. **Not in NBA `SUPPORTED_MARKETS` yet** — see §6 inventory-gap note. |
| 7 | `player_turnovers` | `schema-valid+empty` | 0 | Same as above. **Not in NBA `SUPPORTED_MARKETS` yet** — see §6. |
| 8 | `player_double_double` | **hard-supported** | 2 | Binary `Yes/No` shape (NBA-compatible DD parser path applies). |
| 9 | `player_points_rebounds` | **hard-supported** | 1 | Native combo. |
| 10 | `player_points_assists` | **hard-supported** | 1 | Native combo. |
| 11 | `player_rebounds_assists` | **hard-supported** | 1 | Native combo. Only FanDuel posting. |
| 12 | `player_points_rebounds_assists` | **hard-supported** | 3 | Native combo. |
| 13 | `player_frees_made` (FTM) | `schema-valid+empty` | 0 | Added 2026-05-14 follow-up — §3.2.4. Empty on WNBA same way as NBA's Tier-B graceful path. |
| 14 | `player_field_goals` (FGM) | `schema-valid+empty` | 0 | Added 2026-05-14 follow-up — §3.2.4. Empty on WNBA same way as NBA's Tier-B graceful path. |

**Counts:** 9 `hard-supported`, 5 `schema-valid+empty`, **0 `not-in-schema`**.

## 5. Gate-1 disposition (per SPO-31 §Gate behaviour)

Per the ticket's gate table:

> Some markets `hard-supported`, some `schema-valid+empty` → Close `done`. Comment "scope confirmed". Phase 2 auto-wakes on Forge. Phase 4 auto-wakes on Scout. **Flag the empty markets so Forge knows to deduplicate against the NBA empty-bookmakers UX (FTM/FGM path from SPO-26).**

Empty markets to flag in close comment: `player_steals`, `player_blocks`, `player_turnovers`.

Phase 2 (Forge, SPO-32) inherits the graceful-degrade contract — no new branch needed; reuse the NBA path established in SPO-26 (`backend/app/routes/...`'s 12-metric expansion) that already treats an empty `bookmakers` array as "no line" rather than an error.

## 6. Inventory gap (separate from gate decision — flagged for CTO awareness)

The 12-market list in the SPO-31 ticket scope is **not identical** to `backend/app/services/daily_analysis.SUPPORTED_MARKETS` (the actual production NBA market set). Specifically:

| Market | In NBA `SUPPORTED_MARKETS`? | Status on WNBA |
|---|---|---|
| `player_blocks`   | ❌ Not yet wired in NBA | `schema-valid+empty` on WNBA (SPO-31 run, 2026-05-13) |
| `player_turnovers`| ❌ Not yet wired in NBA | `schema-valid+empty` on WNBA (SPO-31 run, 2026-05-13) |
| `player_frees_made` (FTM) | ✅ Yes (Tier B) | `schema-valid+empty` on WNBA (2026-05-14 follow-up — §3.2.4) |
| `player_field_goals` (FGM/FGA) | ✅ Yes (Tier B) | `schema-valid+empty` on WNBA (2026-05-14 follow-up — §3.2.4) |

Why this matters: when Forge builds the WNBA `SUPPORTED_MARKETS` (or its league-scoped equivalent) in Phase 2, the canonical set is **not yet decided** — the ticket lists 12 markets that include `blocks` / `turnovers` (which NBA doesn't expose to the picks pipeline today) and the NBA production list (FTM/FGM in / BLK/TOV out) differs. Forge will likely need a one-line CTO decision in Phase 2 on whether the WNBA-side `SUPPORTED_MARKETS` follows the ticket list (12 = 11 OU + 1 binary) or mirrors NBA's current production list (11 = 10 OU + 1 binary), or — now that FTM/FGM are verified safe (`schema-valid+empty`, unbilled) — a superset including all 14 verified markets.

Scout recommendation (non-binding — CTO chooses):

- **Ship the WNBA-side list per the ticket** (BLK + TOV included as `schema-valid+empty` from day 1) so when WNBA bookmakers start posting blocks/steals/turnovers (likely as the season progresses — many WNBA bookmaker product launches lag NBA by ~4 weeks), the tile lights up with zero code change.
- **Expose FTM/FGM too** — verified `schema-valid+empty` post-Lens-review (§3.2.4). They cost 0 paid units when probed empty and reuse the same SPO-26 empty-bookmakers UX guard. Reachable today via the shared 12-tile MarketSelect; no additional gating required.

## 7. Quota burn

| | |
|---|---|
| Starting `x-requests-used` | 160 |
| Ending `x-requests-used`   | 169 |
| **Paid units consumed**    | **9** |
| Remaining                  | 331 / 500 |

Per-market billing reconfirmed: 9 populated markets × 1 unit each = 9 units. 3 `schema-valid+empty` markets cost 0 units (consistent with NBA-side SPO-12 measurement). The `/events` listing was free.

This is well within `[Minor]` cost — full Phase 0 verification cost less than 2% of the monthly quota.

## 8. Sources

- The Odds API v4 docs: `https://the-odds-api.com/liveapi/guides/v4/` (no curl needed; this doc only references endpoint paths the live calls already proved).
- Live API raw responses: `/tmp/odds_wnba_*.json` (12 market probes + 1 events list), captured on **2026-05-13** by `scripts/explore_odds_api_wnba.py`.
- NBA-side anti-hallucination precedent: [SPO-12](/SPO/issues/SPO-12) — `docs/research/event-page-stat-expansion/research_odds_api_markets.md`, format used as the model for this doc.
- Phase decomposition decision: `docs/decisions/wnba-rollout/decision_20260513_phase-decomposition.md`.

## 9. Recommended next actions

1. **Sentinel:** push branch `feature/SPO-31-odds-api-wnba-verification`, open PR base=`dev`. Owner squash-merges.
2. **Scout (this agent) → close SPO-31** with the "scope confirmed" comment per gate row 2, listing `player_steals`/`player_blocks`/`player_turnovers` as the empty markets Forge should expect.
3. **CTO:** decide WNBA `SUPPORTED_MARKETS` final shape before Phase 2 starts (12 per ticket vs 11 per NBA convention vs 13 including FTM/FGM). One-line decision log in `docs/decisions/wnba-rollout/`.
4. **Forge (Phase 2, SPO-32):** treat the 9 `hard-supported` markets as the populated path; reuse the NBA empty-bookmakers UX from SPO-26 for the 3 currently-empty markets. No new parsing branches required (Over/Under and DD-binary parsers transfer 1:1).
5. **Sentinel (later, SPO-35):** when writing the `@pytest.mark.integration` test for WNBA, reuse one of the event ids from §3.1 — keep the test gated behind `RUN_INTEGRATION=1` per `CLAUDE.md § External API Wrappers` rule #2.
