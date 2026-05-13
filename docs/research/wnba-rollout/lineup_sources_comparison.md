# WNBA lineup sources comparison — RotoWire + RotoGrinders

- **Ticket:** [SPO-34](/SPO/issues/SPO-34) — Phase 4 of [SPO-29](/SPO/issues/SPO-29) (wnba-rollout)
- **Agent:** Scout (`1a495f58-b689-46b7-9e79-9d563b31175d`)
- **Date:** 2026-05-13
- **Companion artefacts (this directory):**
  - `rotowire_wnba_sample.html` (362 893 B, HTTP 200, captured 2026-05-13)
  - `rotogrinders_wnba_sample.html` (83 276 B, HTTP 200, captured 2026-05-13 — outer page only; see §3 for the iframe situation)
- **Outcome (recommendation):** **Shared RotoWire parser parameterised on `league`. Defer RotoGrinders LineupHQ for this phase** (the page is a JS-only iframe; HTML scraping is not feasible without headless browser infra).

---

## 1. What this doc proves

Per `CLAUDE.md § External API Wrappers` rules **#1** (exploration first), **#3** (research cites raw evidence), and the parent ticket's architectural guardrail (*"every CSS selector / field shape Forge writes must trace back to a sample-HTML snippet in Scout's comparison doc"*), this report captures the real shape of both sources today and lets Forge implement against ground truth instead of training-data assumptions.

Sample fetches used a plain `curl -L` with a desktop Chrome `User-Agent`. No login, no cookies. Both sources are served public (rate-limit considerations not characterised here — Forge should add HTTP-cache headers on top before hammering them in scheduled jobs).

> ⚠ Sources committed alongside this doc are **byte-for-byte snapshots** for regression baselining. If RotoWire/RotoGrinders later change shape, the diff between the new fetch and the committed sample is the cheapest detector — pin it in the integration test (per `CLAUDE.md § External API Wrappers` rule #2).

---

## 2. RotoWire — `/wnba/lineups.php`

### 2.1 Fetch evidence

```bash
curl -sS -L \
  -A "Mozilla/5.0 ... Chrome/123.0 Safari/537.36" \
  "https://www.rotowire.com/wnba/lineups.php" \
  -o docs/research/wnba-rollout/rotowire_wnba_sample.html
# HTTP 200, 362 893 bytes
```

NBA counterpart (for comparison, not committed):

```bash
curl ... "https://www.rotowire.com/basketball/nba-lineups.php"
# HTTP 200, 365 384 bytes
```

### 2.2 First lineup card (raw, WNBA, edited only to strip a `<style>` chrome class) — **anchor reference for §2.4 selectors**

```html
<div class="lineup is-nba">
  <div class="lineup__meta flex-row" style="align-items:baseline;">
    <div class="lineup__time">7:00 PM ET</div>
    <a class="text-75" href="https://www.vividseats.com/?wsUser=948" ...>Tickets</a>
    <div class="text-75 lineup-alerts-view" ...>Alerts</div>
  </div>
  <div class="lineup__box">
    <div class="lineup__top">
      <div class="lineup__teams">
        <a class="lineup__team is-visit" href="/wnba/wnba-depth-charts/seattle-storm-depth-chart-sea">
          <img alt="SEA" class="lineup__logo"
               src="https://content.rotowire.com/images/teamlogo/wnba/100SEA.png?v=6"/>
          <div class="lineup__abbr">SEA</div>
        </a>
        <a class="lineup__team is-home" href="/wnba/wnba-depth-charts/toronto-tempo-depth-chart-tor">
          <img alt="TOR" class="lineup__logo"
               src="https://content.rotowire.com/images/teamlogo/wnba/100TOR.png?v=6"/>
          <div class="lineup__abbr">TOR</div>
        </a>
      </div>
    </div>
    <div class="lineup__matchup">
      <a class="lineup__mteam is-visit white" href="/wnba/wnba-depth-charts/seattle-storm-depth-chart-sea">Storm</a>
      <a class="lineup__mteam is-home white" href="/wnba/wnba-depth-charts/toronto-tempo-depth-chart-tor">Tempo</a>
    </div>
    <div class="lineup__main">
      <ul class="lineup__list is-visit">
        <li class="lineup__status is-expected">
          <div class="dot is-medium is-yellow" ...></div>
          Expected Lineup
        </li>
        <li class="lineup__player is-pct-play-100" title="Very Likely To Play">
          <div class="lineup__pos">G</div>
          <a href="/wnba/player/natisha-hiedeman-587" title="Natisha Hiedeman">N. Hiedeman</a>
        </li>
        <li class="lineup__player is-pct-play-100" title="Very Likely To Play">
          <div class="lineup__pos">G</div>
          <a href="/wnba/player/jordan-horston-855" title="Jordan Horston">J. Horston</a>
        </li>
        <!-- ... -->
        <li class="lineup__player is-pct-play-0 has-injury-status" title="Will Not Play">
          <div class="lineup__pos">F</div>
          <a href="/wnba/player/some-player-xxx" title="Some Player">S. Player</a>
          <span class="lineup__inj">OUT</span>
        </li>
      </ul>
      <ul class="lineup__list is-home"> ... mirror structure ... </ul>
    </div>
  </div>
</div>
```

### 2.3 NBA counterpart — first card (truncated, same date)

```html
<div class="lineup is-nba" data-lnum="1">                       <!-- NBA: data-lnum attr (WNBA: none) -->
  <div class="lineup__meta flex-row" ...>
    <div class="lineup__time">8:00 PM ET</div>
    <a class="text-70" href="https://sling-tv.pxf.io/...">Watch Now</a>  <!-- text-70 (NBA) vs text-75 (WNBA) -->
    <a class="text-70" href="...seatgeek.com/nba-tickets...">Tickets</a>
    <div class="text-70 lineup-alerts-view" ...>Alerts</div>
  </div>
  <div class="lineup__box">
    <div class="lineup__top">
      <div class="lineup__teams">
        <a class="lineup__team is-visit"
           href="/basketball/nba-depth-charts/cavaliers-depth-chart-cle">    <!-- /basketball/nba-… prefix -->
          <img alt="CLE" class="lineup__logo"
               src="https://content.rotowire.com/images/teamlogo/basketball/100CLE.png?v=10"/>  <!-- teamlogo/basketball -->
          <div class="lineup__abbr">CLE</div>
        </a>
        ...
      </div>
    </div>
    <div class="lineup__matchup">
      <a class="lineup__mteam is-visit white" href="//basketball/nba-depth-charts/cavaliers-depth-chart-cle">
        Cavaliers
        <span class="lineup__wl">(52-30)</span>                              <!-- WL badge (NBA only) -->
      </a>
      ...
    </div>
    <div class="lineup__main">
      <ul class="lineup__list is-visit">
        <li class="lineup__status is-expected">Expected Lineup</li>
        <li class="lineup__player is-pct-play-100" title="Very Likely To Play">
          <div class="lineup__pos">PG</div>                                  <!-- 5-position vocab (NBA) -->
          <a href="/basketball/player/james-harden-3018" title="James Harden">James Harden</a>
        </li>
        ...
      </ul>
    </div>
    <div class="lineup__bottom">                                             <!-- bottom pane (NBA only) -->
      <div class="lineup__odds is-row"> ... partner odds widgets ... </div>
    </div>
  </div>
</div>
```

### 2.4 Selector & field delta table (RotoWire NBA vs WNBA)

| Concern | NBA selector / value | WNBA selector / value | Behaviour for shared parser |
|---|---|---|---|
| Root card | `div.lineup.is-nba` | `div.lineup.is-nba` (literal — **not `is-wnba`**) | Same selector. `league` does **not** select root. |
| Card count today | 3 in sample (game-day dependent) | 5 in sample | Iterate `soup.select('div.lineup.is-nba')` regardless of league. |
| Bookend ID attr | `data-lnum="1"` present | Not present | Optional; do not rely on it. |
| Tip-off time | `.lineup__time` | `.lineup__time` | Same. |
| Visiting / home team block | `a.lineup__team.is-visit` / `.is-home` | `a.lineup__team.is-visit` / `.is-home` | Same. |
| Team abbreviation | `.lineup__abbr` (e.g. `CLE`) | `.lineup__abbr` (e.g. `SEA`) | Same selector, league-specific value space. |
| Team depth-chart URL | `href="/basketball/nba-depth-charts/…"` | `href="/wnba/wnba-depth-charts/…"` | **Differs.** Parser can ignore (we only need slug) but the `urljoin` base must use `league` when re-resolving. |
| Team logo URL | `…/teamlogo/basketball/100<ABBR>.png` | `…/teamlogo/wnba/100<ABBR>.png` | **Differs.** Same shape, league-specific folder. |
| Matchup nickname | `a.lineup__mteam.is-visit/.is-home` | same | Same. |
| Win-loss badge | `<span class="lineup__wl">(52-30)</span>` present | **absent** in 2026-05-13 sample | `Optional[str]` — gracefully handle missing element. |
| Lineup status row | `li.lineup__status` with class `is-expected` (or `is-confirmed` mid-day) | same | Same. WNBA sample today shows only `is-expected`. |
| Player row | `li.lineup__player` with `is-pct-play-{0,50,100}` and optional `has-injury-status` | same | Same. WNBA distribution: 39× pct-100, 21× pct-0, 2× pct-50 — **higher OUT rate** than NBA (1 game-day sample). |
| Position label inside row | `.lineup__pos` value ∈ {`PG`,`SG`,`SF`,`PF`,`C`,`G`,`F`} | `.lineup__pos` value ∈ {`G`,`F`,`C`} only (3 labels, no PG/SG/SF/PF) | **Field-value differs.** Position normaliser must accept WNBA's collapsed vocabulary; do not assume 5 positions. |
| Player link | `a[href^="/basketball/player/<slug>"]` | `a[href^="/wnba/player/<slug>"]` | Same selector at row level; player URL prefix differs (same comment as team URL). |
| Injury status span | `span.lineup__inj` ("Q", "OUT", "DTD"…) | `span.lineup__inj` (same vocabulary in this sample: "OUT") | Same. |
| Bottom pane (odds / partner widgets) | `div.lineup__bottom` containing `.lineup__odds.is-row` etc. | **absent** in 2026-05-13 sample | Optional; do not require. (We do not parse odds from here — that's The Odds API in SPO-33.) |
| Sponsor-style chrome class on links | `text-70` | `text-75` | Cosmetic; parser must not depend on it. |

**Mid-game / post-line-publish concerns (Sports Lab domain lens — "Lineup / injury validity"):**
- `li.lineup__status` value is the **only** indicator of whether the row is `is-expected` (pre-game guess) vs `is-confirmed` (official starting 5). Forge must surface this status verbatim, **not collapse it to a boolean** — the agent layer needs it to decide whether a prop should be invalidated.
- `is-pct-play-0` + `has-injury-status` on a player row, combined with `<span class="lineup__inj">OUT</span>`, means the player will not play. The `title` attribute on the `<li>` ("Will Not Play", "Very Likely To Play", "Game-Time Decision") is human-readable but is the same datum as `is-pct-play-*` — do not double-count.

---

## 3. RotoGrinders — `/lineuphq/wnba` (the negative finding)

### 3.1 The outer page is just an iframe shell

```bash
curl ... "https://rotogrinders.com/lineuphq/wnba" -o docs/research/wnba-rollout/rotogrinders_wnba_sample.html
# HTTP 200, 83 276 bytes
```

The outer HTML contains zero lineup data. The only relevant element is:

```html
<iframe src="https://lineuphq.rotogrinders.com/wnba?user=0&token=0&brand=rotogrinders"
        width="100%" style="border:0; margin:0; padding:0; flex-grow:1">
```

Visible-text length on the outer page is **21 characters**.

### 3.2 The iframe target is a React SPA (no SSR)

`curl https://lineuphq.rotogrinders.com/wnba?...` returns **585 bytes** of bootstrap HTML:

```html
<!DOCTYPE html>
<html>
<head>
  <title>LHQ STATIC</title>
  <link rel="stylesheet" href="/lineuphq.css" />
  ...
</head>
<body>
  <div id="lineuphq-container"></div>
  <div id="group-select-portal"></div>
  <div id="tooltip-portal"></div>
  <script src="/lineuphqIndex.js"></script>
  <script src="/static.initial_params.js"></script>
  <script>window.lineuphq = new LineupHQ(intialParams); window.lineuphq.init();</script>
</body>
</html>
```

The bundle `lineuphqIndex.js` is **~3 MB minified**. The data backend is bootstrap-encoded as:

```js
// /static.initial_params.js (142 bytes total)
const intialParams = {
  backendHost: "https://rotogrinders.com",
  serviceURL: "https://pnvyab4v524v2sst2fkuzhk7he0vlirv.lambda-url.us-east-1.on.aws"
};
```

The Lambda function URL responds 404 `{"error":"not found"}` on every probed path (`/`, `/wnba`, `/wnba/lineups`, `/sports/wnba`, `/lineups?sport=wnba`) — the actual request paths are assembled inside the SPA bundle via template-literal concatenation that does not survive static `grep` of the minified bundle.

### 3.3 Implication

| Approach | Cost | Verdict |
|---|---|---|
| HTML scraping with `requests` + BeautifulSoup (same approach as RotoWire) | **Impossible.** No SSR. | ❌ |
| Headless browser (Playwright) → render → `page.locator()` | Multi-day infra: chromium image in CI, sandboxing in scheduler, retry on flake, ~5–15 s per fetch. Adds heavy ops surface to Sports Lab. | ❌ for SPO-34's 0.3-Scout / 1.2-Forge budget. |
| Reverse-engineer the Lambda URL → call directly | Stable URL but unknown auth/path. Likely TOS-violating; fragile to schema drift; no curl evidence today. | ❌ — would violate `CLAUDE.md § External API Wrappers` rule #3 (no curl evidence). |

**Therefore: do not ingest RotoGrinders WNBA in Phase 4.** Document this in `docs/task-summaries/SPO-NN-wnba-lineup-ingestion.md` and add a follow-up ticket if the agent layer (Phase 5) shows we materially need a second lineup source.

---

## 4. Existing `nba_lineup_rag/` module reality (correction to ticket description)

The SPO-34 ticket asserts: *"The module currently parses NBA lineup pages only; this phase refactors it to accept a `league` parameter."* This is **not quite accurate** — the existing `nba_lineup_rag/src/sources/` only contains:

- `espn_rss.py` — ESPN RSS news (NBA-only by feed URL)
- `injuries_pages.py` — ESPN + CBS injuries-page scrapers

There is **no RotoWire or RotoGrinders parser in the tree today.** What Forge is actually doing in Phase 4 is:

1. **Adding a new league-aware RotoWire source module** (e.g. `nba_lineup_rag/src/sources/rotowire_lineups.py`) that accepts `league: Literal["nba","wnba"]` from day one. URL, team-link prefix, logo folder all parameterised. Selector taxonomy is fully shared (see §2.4).
2. **Not** adding a RotoGrinders module yet (see §3).
3. Optionally — out of scope for this ticket — adjusting ESPN/CBS injury scrapers to accept `league` if Phase 5 needs WNBA injury context. That is a separate decision for CTO/Forge once Phase 5 lights up.

The "refactor over fork" guardrail still holds, but it applies prospectively: the new `rotowire_lineups.py` is league-aware by construction, not a copy-pasted `wnba_rotowire_lineups.py` next to an NBA version.

---

## 5. Recommendation (the line Forge should implement against)

### 5.1 Architecture

**One shared parser, parameterised on `league`, RotoWire only.**

```python
# nba_lineup_rag/src/sources/rotowire_lineups.py
from typing import Literal

League = Literal["nba", "wnba"]

ROOT_URLS = {
    "nba": "https://www.rotowire.com/basketball/nba-lineups.php",
    "wnba": "https://www.rotowire.com/wnba/lineups.php",
}

# Both pages serve the same selector taxonomy — see lineup_sources_comparison.md §2.4
ROOT_CARD_SELECTOR = "div.lineup.is-nba"   # ⚠ literal "is-nba" on both pages — see §2.4

# Position vocabulary differs by league — see §2.4
POSITION_VOCAB = {
    "nba": {"PG", "SG", "SF", "PF", "C", "G", "F"},
    "wnba": {"G", "F", "C"},
}

def fetch_lineups(league: League) -> list[GameLineup]:
    ...
```

Selector overrides are minimal — really only **the URL** and **the position normalizer's allowed vocabulary**. Team-link prefix and logo folder are not consumed by the parser today (they're only used if you want to cross-reference to a depth chart page — out of scope for SPO-34).

### 5.2 Forge sub-step work plan (informational — for Forge to refine)

1. Create `nba_lineup_rag/src/sources/rotowire_lineups.py` with the shape above. Implement `fetch_lineups(league)`, `parse_card(card_soup, league)`, `parse_player_row(li, league)`.
2. Add `backend/app/api/wnba.py` route `/api/wnba/lineups` (an `nba.py` mirror already exists — copy its handler signature and route to `fetch_lineups(league="wnba")`).
3. Add scheduler job for WNBA lineup ingestion. Mirror existing NBA cadence; per Sports Lab domain lens **"Lineup data must be timestamped"** — include the fetch UTC timestamp in the persisted record.
4. **Unit test** against `docs/research/wnba-rollout/rotowire_wnba_sample.html` (loaded from disk, no network). Pin to the committed sample. Assert: 5 cards, 4 expected-lineup status rows, position vocabulary ⊆ `{G,F,C}`, `lineup__wl` absent.
5. **Integration test** against live URL, gated on `RUN_INTEGRATION=1` per `CLAUDE.md § External API Wrappers` rule #2. Assert: HTTP 200, `len(cards) >= 1`, position vocabulary ⊆ NBA-allowed when `league="nba"` and ⊆ WNBA-allowed when `league="wnba"`. Do NOT pin card count — game-day dependent.
6. Do **not** create a RotoGrinders module today. Defer per §3.

### 5.3 Risks Forge should call out at PR time

- WNBA position vocabulary may evolve (sample size: 5 cards on 2026-05-13). If RotoWire later starts reporting `PG`/`SF` for WNBA, parser must accept them — keep vocab a **superset check** ("known position vs unknown position"), not a strict equality test.
- Page byte size is ~360 KB. A naïve every-30-second scheduler will burn ~30 GB/day of bandwidth. Pair the ingestion with conditional-GET (`If-Modified-Since` / ETag) before merge.
- `is-confirmed` status was not observed in this sample (only `is-expected`). Forge must still parse it — see status row spec in §2.4. Re-pull HTML closer to game time (T-30 min) to verify.

---

## 6. Acceptance-criteria coverage (Scout sub-step only)

- [x] Sample HTML committed for both sources (RotoWire WNBA: `rotowire_wnba_sample.html`; RotoGrinders WNBA: `rotogrinders_wnba_sample.html` — outer iframe shell only, see §3 for the negative finding).
- [x] Comparison doc landed at `docs/research/wnba-rollout/lineup_sources_comparison.md` (this file).
- [x] Recommendation: shared RotoWire parser w/ minimal `league` override + defer RotoGrinders (§5).
- [ ] `nba_lineup_rag/` accepts `league` parameter — **Forge to implement.**
- [ ] `/api/wnba/lineups` returns starter / questionable / OUT for a real WNBA event — **Forge to implement.**
- [ ] Scheduler runs WNBA + NBA lineup ingestion independently — **Forge to implement.**
- [ ] Integration test passes locally — **Forge + Sentinel.**
- [ ] Task summary at `docs/task-summaries/SPO-34-wnba-lineup-ingestion.md` — **Forge to author on PR.**

---

## 7. Sources

- RotoWire WNBA lineups page: `https://www.rotowire.com/wnba/lineups.php` (HTTP 200, 362 893 B, 2026-05-13)
- RotoWire NBA lineups page: `https://www.rotowire.com/basketball/nba-lineups.php` (HTTP 200, 365 384 B, 2026-05-13) — comparison only, not committed
- RotoGrinders WNBA LineupHQ outer page: `https://rotogrinders.com/lineuphq/wnba` (HTTP 200, 83 276 B, 2026-05-13)
- RotoGrinders LineupHQ iframe: `https://lineuphq.rotogrinders.com/wnba?user=0&token=0&brand=rotogrinders` (HTTP 200, 585 B SPA shell, 2026-05-13)
- RotoGrinders LineupHQ bootstrap: `https://lineuphq.rotogrinders.com/static.initial_params.js` (HTTP 200, 142 B, 2026-05-13) — exposes the AWS Lambda backend URL
- Anti-hallucination policy: `CLAUDE.md § External API Wrappers` rules #1, #2, #3
- Sports-betting domain lens for lineup validity: `CLAUDE.md § Domain Lenses` — "Lineup / injury validity"
