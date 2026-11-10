# SPO-110a — Design system, app shell, and Today

## Summary

The first slice of the November 2026 redesign. The app is No-Vig on a light canvas: deep purple `#3E0F8D`, yellow `#E4DA72`, background `#EEEEEE`. Instrument Sans is the UI face and JetBrains Mono is the face for numbers. The shell has a desktop header (Today, Picks, Bet Slip, Method, Ask the agent) and mobile bottom tabs. An NBA/WNBA switch keeps the section and routes between the existing pages. Today, on `/` and `/wnba`, shows tonight's best reads and each game's top read from the events and daily-picks APIs. A missing read is a labeled empty state. `formatPercent(null)` returns `—`.

Picks, Bet Slip, and Method keep their current pages. The design reference is `docs/design/redesign-2026-11/`.

## Changes

| File | Change |
|---|---|
| `docs/design/redesign-2026-11/` | Prototype, source, and screenshots, kept as the design reference. |
| `frontend/tailwind.config.ts` | Brand, accent, canvas, ink, muted, and line colors. Radii 10 / 14 / 20 / 28. Fonts read `--font-sans` and `--font-mono`. |
| `frontend/app/globals.css` | Light canvas. `text-dark` is `#1D1530`. `text-gray` is `#625B70`. `text-yellow` is `#5A5310` while `bg-yellow` stays `#E4DA72`. `text-on-dark` and `text-on-dark-muted` for the dark agent panel. |
| `frontend/app/layout.tsx` | Instrument Sans and JetBrains Mono via `next/font/google`. `AppShell` wraps the tree. |
| `frontend/components/AppShell.tsx` | Header, mobile tabs, league switch, slip badge, Ask the agent. |
| `frontend/lib/shell-nav.ts` | Path helpers: league, section, section href, league-switch href. |
| `frontend/components/TodayBoard.tsx` | Tonight's reads, see-all link, games list. Loading, empty, and error states. |
| `frontend/lib/today-board.ts` | Ranks picks, formats the prop and the clock, and leaves a game with no pick unlabeled. |
| `frontend/lib/team-abbr.ts` | NBA abbreviations through the existing map. WNBA abbreviations from the backend alias list. |
| `frontend/app/page.tsx` | NBA Today. |
| `frontend/app/wnba/page.tsx` | WNBA Today, with the roster search kept underneath. |
| `frontend/lib/player-dd.ts` | `formatPercent(null)` and `formatPercent(undefined)` return `—`. |
| `frontend/components/Navbar.tsx` | Removed. The shell replaces it. |
| `frontend/components/agent-widget/*`, `AgentWidget.tsx` | Dark-panel text uses the on-dark tokens. The launcher sits above the mobile tabs. |
| `frontend/components/PickContextMenu.tsx` | Light menu so `text-dark` stays readable. |
| `frontend/app/about/page.tsx` | Formula lines on the dark block use `text-accent`. |
| `frontend/components/AppShell.test.tsx` | Nav, tabs, league switch, slip count, Ask the agent. |
| `frontend/components/TodayBoard.test.tsx` | Data, empty, loading, error, and WNBA. |
| `docs/decisions/decision_20261110_redesign_design_system.md` | Tokens, fonts, contrast, component conventions. |
| `docs/progress.md` | SPO-110a in flight. |

Contrast on older pages is a token change plus a few class swaps where a 500-weight green or blue was white-on-fill or body text under 4.5:1 (`picks`, both bet slips, projection and history panels, lineup badges). Those pages are not restyled.

## Why

`text-dark` cannot be both the old near-white (`#ebf1fb`, 1.13:1 on a white card) and a readable ink. The canvas goes light, and the dark agent panel gets its own light tokens. `text-yellow` as `#E4DA72` fails on white, so the word color and the fill color split.

Today does not reuse the prototype's sample players or its sentence about a blended probability. `DailyPick.probability` is a historical hit rate. The hero says that. A game with no stored pick shows "No read on this game" and no percent. The daily-picks service only keeps rows at `probability >= 0.65` (`HIGH_PROBABILITY_THRESHOLD`) and `n_games >= 10` (`MIN_SAMPLE_GAMES`) before the query filter, so asking for 0.50 would not add leans and would split the picks-page cache. Today uses the default query (`["daily-picks", date]` on NBA, `["wnba-daily-picks", date]` on WNBA).

The league switch is a real control. The prototype only draws a static NBA pill. Method stays `/about` for both leagues. The WNBA roster search stays under the board so `/wnba/player/[name]` is still reachable. Today has no date picker; other dates stay on the picks pages.

## Tests / Verification

- `npx vitest run` — 29 files, 171 tests, passed.
- `npx tsc --noEmit` — passed.
- `npm run lint` — passed, 0 warnings.
- Integration test: SKIPPED. Today reads the existing events and daily-picks routes. No new external client.
- Fabrication scan: PASS. Card numbers come from the API payloads. Tests and screenshots use fixture players (Bam Adebayo, Joel Embiid, Tyrese Haliburton, A'ja Wilson, Breanna Stewart), not the prototype's sample board.

| Behavior | Test |
|---|---|
| Today is current on `/`, Picks and Method hrefs, NBA slip count | `highlights Today and shows the NBA bet slip count` |
| Mobile tabs, Picks current on `/picks` | `renders mobile tabs for the same four sections` |
| WNBA switch from Today, NBA switch from `/wnba/picks` | `routes the league switch between NBA and WNBA sections` |
| WNBA route reads the WNBA slip | `uses the WNBA slip count on a WNBA route` |
| Ask the agent opens the widget | `opens the betting agent from Ask the agent` |
| Hero reads, top read, a game with no percent | `renders tonight's reads and each game's top read from the API` |
| Empty slate | `shows empty states when the slate and the board have no rows` |
| Loading | `shows a loading state without player names` |
| Games error and retry | `shows an error and retries the games request` |
| Reads error hides percents | `keeps the games and withholds percents when reads fail` |
| WNBA endpoints and abbreviations | `renders the WNBA board from the WNBA endpoints` |
| `formatPercent(null)` is `—` | `returns an em dash for null instead of 0.0%` |

Screenshots in `docs/task-summaries/SPO-110a-screenshots/` are the running app against a local fixture API, desktop and mobile, NBA and WNBA.

## Data gaps

These are fields the prototype draws, or that a reader might expect on Today, which this API does not return. The page hides them or shows a labeled empty state.

| Missing field | What the page does |
|---|---|
| `event.top_read`, `event.top_probability` | Not on the events payload. The top read is the highest `DailyPick` with the same `event_id`. A game with none shows "No read on this game" and no percent. |
| A stored pick with `probability` < `0.65` or `n_games` < `10` | `HIGH_PROBABILITY_THRESHOLD` and `MIN_SAMPLE_GAMES` drop the row before the query filter. `min_probability` (floor 0.5) and `min_games` (floor 5) cannot bring it back. |
| `combined_probability`, `signals[]` (market price, last-10 hits, season rate, projection edge, opponent defense) | Not on `DailyPick`. Separate optional fields exist (`projected_value`, `edge`, `opponent_rank`, `opponent_position_rank`, `n_games`, `lineup_confirmed`, `injury_status`) and are not a blend. Today shows `probability` only. |
| `commence_time` timezone | The value is an ISO timestamp. The clock is the browser's local zone (`h:mm a`). There is no zone field, so the page does not print "ET". |
| `lineup_confirmed` on the event, per team | The flag is per pick. The Today games list does not show lineup chips. |
| `position` on `DailyPick` | Not on the payload. Today does not show a position. |

## Follow-ups

- [ ] PR C restyles Picks, Bet Slip, and Method.
- [ ] Today has no date picker. Other dates remain on the picks pages.
- [ ] The floating agent launcher still exists beside "Ask the agent". It is offset above the mobile tabs.
