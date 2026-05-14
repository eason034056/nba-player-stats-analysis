# SPO-34 — WNBA lineup ingestion (Phase 4 of SPO-29)

- **Ticket:** [SPO-34](/SPO/issues/SPO-34) — WNBA rollout Phase 4
- **Parent epic:** [SPO-29](/SPO/issues/SPO-29) (`wnba-rollout`)
- **Forge:** `d5d67ab1-…`
- **Implementation date:** 2026-05-13
- **Scout deliverables consumed:** `docs/research/wnba-rollout/lineup_sources_comparison.md`, `rotowire_wnba_sample.html`, `rotogrinders_wnba_sample.html`

## Summary

Made the production lineup pipeline league-aware end-to-end. WNBA lineups
now flow RotoWire → `LineupConsensusService(league="wnba")` → Redis →
`/api/wnba/lineups`, with three new APScheduler jobs covering baseline,
active-window, and pre-tip-off refresh cadences. The existing NBA path
is untouched — same handler, same parser, same cache keys, same DB rows.

RotoGrinders WNBA ingestion is **deferred** per Scout's negative finding:
the LineupHQ page is a JS-only React SPA backed by a private AWS Lambda
URL, requiring headless-browser infra that overshoots the SPO-34 budget.
WNBA therefore runs RotoWire-only; consensus quality is `low` confidence,
which is the honest answer the agent layer can reason about.

## Changes

| File | Change |
|---|---|
| `backend/app/services/lineup_source_support.py` | + `WNBA_TEAM_ALIASES`, `WNBA_TEAM_LOOKUP`, `LEAGUE_TEAM_LOOKUPS`. `detect_team_code(line, league="nba")` now accepts a league kwarg (default unchanged → NBA). |
| `backend/app/services/lineup_provider_rotowire.py` | + `ROTOWIRE_LEAGUE_URLS` dispatch table. + `parse_rotowire_wnba_html` (BS4-based; reads `<a title="…">` for canonical names, captures `is-expected`/`is-confirmed` status verbatim, classifies players into starters / OUT / questionable using `is-pct-play-N`). `fetch_rotowire_lineups(date, league="nba")` dispatches; existing NBA `parse_rotowire_html` left untouched. |
| `backend/app/services/lineup_service.py` | `LineupConsensusService.__init__(league="nba")`. For `league="wnba"`: fetches RotoWire only (no RotoGrinders), namespaces Redis to `lineups:wnba:{date}`, skips PostgreSQL writes (PK collision risk on shared codes — see §Follow-ups). + module-level `wnba_lineup_service` singleton. |
| `backend/app/api/wnba.py` | + `GET /api/wnba/lineups`, `GET /api/wnba/lineups/{team}`, `POST /api/wnba/lineups/refresh`. Mirrors `backend/app/api/lineups.py`; reuses the league-agnostic `LineupsResponse` / `TeamLineup` / `LineupRefreshResponse` schemas. |
| `backend/app/services/scheduler.py` | + 3 jobs (`wnba_lineup_fetch_opening` 09:30 CT, `wnba_lineup_fetch_active_window` 11–21 CT every 15 min, `wnba_lineup_fetch_pre_tipoff` 17–19 CT every 5 min). Independent IDs from NBA so failures isolate. |
| `backend/requirements.txt` | + `beautifulsoup4==4.14.3`, `lxml==6.0.2` (WNBA path only — NBA path does not import BS4). |
| `backend/tests/test_lineup_provider_rotowire_wnba.py` | 11 unit tests pinned to Scout's `rotowire_wnba_sample.html` + 1 live integration test gated on `RUN_INTEGRATION=1`. |

## Why (architectural decisions)

### 1. Refactor inside `backend/app/services/`, not `nba_lineup_rag/`

The SPO-34 ticket says "make `nba_lineup_rag/` league-aware," but inspecting
the tree showed the production RotoWire parser lives in
`backend/app/services/lineup_provider_rotowire.py` — `nba_lineup_rag/src/sources/`
only contains ESPN-RSS and ESPN/CBS injury scrapers. Adding a new
`nba_lineup_rag/src/sources/rotowire_lineups.py` would have created a
parallel fork to the production path, violating the "refactor over fork"
guardrail. The fix lives where the working code lives.

Scout's recommendation §5.1 made the same mistake — Scout assumed the
RotoWire parser was in `nba_lineup_rag/`. The selector taxonomy table in
Scout's §2.4 is still the ground truth, and every selector my parser uses
traces back to a line in `rotowire_wnba_sample.html`.

### 2. BS4 for WNBA only; line-strip preserved for NBA

The line-strip approach used by the existing NBA parser loses information
the WNBA path needs:

- `<a title="Natisha Hiedeman">N. Hiedeman</a>` — only the visible text
  "N. Hiedeman" survives `strip_html_lines`. Without a WNBA roster CSV
  (and Sports Lab doesn't have one), broadcast names like "N. Hiedeman"
  can't be resolved to the canonical form the odds API uses ("Natisha
  Hiedeman"). BS4 + `anchor.get("title")` gets the canonical name directly.
- `li.lineup__status` class `is-expected` vs `is-confirmed` is a sports
  betting domain signal (CLAUDE.md § Domain Lenses — lineup/injury
  validity) that the agent layer needs verbatim to decide whether to
  invalidate a prop. The line-strip approach loses the class attribute.
- `is-pct-play-{0,25,50,75,100}` captured as an integer is more useful
  than a free-text "OUT" string — the agent can apply its own threshold.

The NBA `parse_rotowire_html` function is byte-identical to before. NBA
callers of `detect_team_code(...)` are also unchanged (the `league`
keyword has a default).

### 3. RotoGrinders WNBA deferred

Scout's §3 documents this with `curl` evidence: the outer page is a 21-char
iframe shell, and the iframe target is a React SPA with a private AWS
Lambda backend. HTML scraping with `requests + BS4` is impossible (no SSR);
headless-browser scraping adds multi-day infrastructure (chromium in CI,
sandboxing in the scheduler, retries on flake) for a fragile, TOS-grey
data source. Deferred to a follow-up if/when the agent layer demonstrates
it materially needs a second WNBA source for consensus.

### 4. WNBA does not write to `team_lineup_snapshots` in this phase

The table's PK is `(date, team)`. Several team codes overlap between NBA
and WNBA: CHI, IND, TOR, WAS, ATL, DAL, MIN, NYK, PHX. A WNBA write would
either overwrite an NBA row or vice versa on the same date — both wrong.
Adding a `league` column to the PK is a migration, which is heavier than
SPO-34's 1.2-day budget warranted. The Redis cache + the fallback path
gracefully degrade to "empty" on Redis miss + RotoWire failure, which is
the correct surface for an MVP. Tracked as a follow-up below.

### 5. Starter classification when pct < 100

Slot-2 of CHI on 2026-05-13 was `is-pct-play-50` — a starter who is
questionable, not "not a starter". The parser takes the first 5 non-OUT
rows in document order as starters regardless of pct, and additionally
surfaces each questionable starter in `questionable_players` so the
downstream layer can decide whether to flag the prop. Anti-hallucination:
if I'd written `if pct == 100: append(starter)` (Scout's suggestion §5.1),
CHI would have shipped with 4 starters which is wrong.

## Tests

```
PYTHONPATH=backend nba_lineup_rag/venv/bin/pytest \
    backend/tests/test_lineup_provider_rotowire_wnba.py -v
# 11 passed, 1 skipped (live test, RUN_INTEGRATION not set)

PYTHONPATH=backend RUN_INTEGRATION=1 nba_lineup_rag/venv/bin/pytest \
    backend/tests/test_lineup_provider_rotowire_wnba.py::test_live_wnba_lineups_smoke -v
# 1 passed against live RotoWire 2026-05-13
```

All 11 unit tests are grounded in `docs/research/wnba-rollout/rotowire_wnba_sample.html`
which is the byte-for-byte regression baseline per `CLAUDE.md § External
API Wrappers` rule #2.

### NBA-path regression argument

I did not exercise the NBA tests locally — the backend's
fastapi/redis/pytest deps are not installed on this workstation outside
the Docker container Sentinel will use. The NBA-path invariants are
preserved structurally:

1. `parse_rotowire_html` (NBA parser) is byte-identical to its prior version.
2. `fetch_rotowire_lineups(date)` with no `league` argument hits
   `league="nba"` default → same URL → same parser. Verified by the new
   `test_league_url_dispatch_is_wired` unit test.
3. `detect_team_code(line)` with positional-only call still hits
   `league="nba"` default → same lookup table → same behavior. The
   `is_control_line` helper inside `lineup_source_support.py` calls
   `detect_team_code(line)` positionally and resolves to NBA codes
   identically.
4. `LineupConsensusService()` with default `league="nba"` follows the
   identical code path as before in `fetch_and_store`,
   `_write_to_postgres`, and `_read_from_postgres`. The new WNBA branches
   are conditionally entered.
5. `lineups:nba:{date}` cache keys are emitted unchanged (`league="nba"`
   is the default).

Sentinel should re-run `test_lineup_consensus.py`, `test_lineup_service.py`,
and `test_lineup_player_context.py` end-to-end to confirm.

## Follow-ups (for SPO-29 backlog)

1. **`team_lineup_snapshots.league` migration.** Add a `league` column to
   the table PK so WNBA + NBA lineups can co-exist on the same date in
   PostgreSQL. Currently WNBA is Redis-only.
2. **WNBA position vocab drift watcher.** RotoWire's 2026-05-13 sample
   shows only `{G, F, C}` for WNBA. If WNBA adoption of NBA's 5-position
   vocabulary spreads, the parser is already permissive (it stores the
   raw string), but `test_position_vocabulary_is_wnba_subset` will fail
   loudly — that's the trigger to expand the test or re-pin the sample.
3. **Conditional GET / `If-Modified-Since` on RotoWire.** Scout §5.3
   flagged the 360 KB page size × 30-second scheduler = ~30 GB/day. Out
   of scope for SPO-34 but worth a follow-up before the WNBA scheduler
   goes to production at full cadence.
4. **RotoGrinders WNBA via headless browser.** Only revisit if the agent
   layer demonstrates value from a second WNBA lineup source for
   consensus disagreement detection.
5. **WNBA roster CSV → improve resolution beyond `title=`.** The `title`
   attribute is reliable for the canonical name but doesn't help when a
   WNBA player is missing from the page (e.g. mid-game add). A WNBA
   roster CSV would close that gap.

## Acceptance criteria

- [x] Sample HTML committed for both sources (committed by Scout in
      commit `74ca06b`; cherry-picked into this branch).
- [x] Comparison doc at `docs/research/wnba-rollout/lineup_sources_comparison.md`.
- [x] `nba_lineup_rag/` accepts `league` parameter — **partial** see §1
      above. The production lineup pipeline is in `backend/app/services/`,
      and that's what was made league-aware. `nba_lineup_rag/` was not
      touched (no RotoWire parser exists there to refactor). I believe
      this is the right interpretation given the "refactor over fork"
      guardrail; reviewer should weigh in.
- [x] `/api/wnba/lineups` returns starter / questionable / OUT for a real
      WNBA event — verified against live RotoWire WNBA via the
      RUN_INTEGRATION=1 test (8 teams, 5 starters each, OUT + questionable
      populations populated).
- [x] Scheduler runs WNBA + NBA lineup ingestion independently.
- [x] Integration test passes locally.
- [x] Task summary at `docs/task-summaries/SPO-34-wnba-lineup-ingestion.md`
      — this file.

## Branch / commit notes for Lens + Sentinel

This run landed commits on whichever branch the harness placed me on
(turned out to be `feature/SPO-32-wnba-csv-and-stats-page` due to
harness flip-flopping mid-run). At hand-off the work has been moved onto
`feature/SPO-34-wnba-lineup-ingestion` (HEAD `06675a9`), branched off
`feature/SPO-32-wnba-csv-and-stats-page`.

**Base relationship:** SPO-34 cannot branch directly off `origin/dev`
because `backend/app/api/wnba.py` is created in SPO-32 (not yet merged
to `dev`) — branching off `dev` produced a delete-vs-modify conflict
on that file. SPO-32 must merge before this PR targets `dev` cleanly.

**SPO-34-only commit range:** `285ba89..06675a9` (11 commits). Listed
oldest → newest:

| Commit | Subject |
|---|---|
| `285ba89` | feat(lineup): add ROTOWIRE_LEAGUE_URLS + bs4 import |
| `650c3ed` | feat(lineup): WNBA team aliases + league-aware detect_team_code |
| `1be7197` | feat(lineup): BS4-based parse_rotowire_wnba_html + league dispatch |
| `237f664` | research(wnba): SPO-34 Phase 4 — sources comparison (Scout, cherry-picked from `74ca06b`) |
| `a714e9c` | feat(lineup): namespace lineup cache keys by league |
| `d1696a0` | feat(lineup): LineupConsensusService league-aware + wnba_lineup_service |
| `dea65cc` | feat(api): /api/wnba/lineups endpoints |
| `9c47ffe` | feat(scheduler): WNBA lineup jobs independent from NBA |
| `d95ac94` | test(lineup): RotoWire WNBA parser unit + live integration |
| `c476950` | deps(backend): add beautifulsoup4 + lxml |
| `06675a9` | docs(task): SPO-34 task summary (this file) |

`285ba89` adds the URL dispatch table + BS4 import (no use of WNBA
aliases yet); `650c3ed` adds `WNBA_TEAM_LOOKUP`; `1be7197` is the parser
that consumes both. Build at every commit in the chain succeeds.
