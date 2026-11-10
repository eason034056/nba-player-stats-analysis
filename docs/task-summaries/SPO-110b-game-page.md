# SPO-110b — Game page

## Summary

The NBA event page (`/event/[eventId]`) and the WNBA event page (`/wnba/event/[eventId]`) use the November 2026 No-Vig layout. Both routes still render `EventDetail`. The league argument picks the NBA or WNBA client.

The page shows the matchup and local clock, a lineup chip per team, the twelve markets the calculator already supports, and a player list. "Our read" shows the stored daily-pick rate when one exists, the no-vig consensus or the history split, add-to-slip, ask-the-agent, and five signal rows. The game log draws the last games against the posted line. Filters cover range, line, role, opponent, and teammates. Sportsbook prices stay in `ResultsTable`. On a narrow screen the same sections are tabs: Our read, Game log, Filters, Odds.

Numbers come from the events, daily-picks, suggest, lineup, no-vig, player-history, and (NBA only) projection routes. A field the API does not return is hidden or labeled empty. The prototype's sample board is not used.

## Changes

| File | Change |
|---|---|
| `frontend/components/EventDetail.tsx` | Composes the game page for both leagues. Keeps no-vig, `ResultsTable`, `PlayerHistoryStats`, `PlayerDDTile` (inside history), `PlayerProjectionPanel`, and `TeamLineupPanel`. |
| `frontend/components/event/EventHeader.tsx` | Matchup, clock, lineup chips, loading and error. |
| `frontend/components/event/StatChips.tsx` | PTS, REB, AST, 3PM, PRA, then the other markets in `MarketSelect`. |
| `frontend/components/event/PlayerRail.tsx` | Suggested names. A lean percent only when a daily pick exists. |
| `frontend/components/event/OurRead.tsx` | Tier, probability bar, slip, ask, five signals. |
| `frontend/components/event/GameLogChart.tsx` | Bars, the line, and the selected game. |
| `frontend/components/event/GameFilters.tsx` | Range, line, disabled venue, role, opponent, teammates. |
| `frontend/components/event/EventTabs.tsx` | Mobile tabs. `?tab=` opens one of them. |
| `frontend/lib/event-page.ts` | View models: chips, signals, rows, chart, slip seeds. |
| `frontend/lib/api.ts` | `getWNBATeamLineup` for `GET /api/wnba/lineups/{team}`. |
| `frontend/lib/event-page.test.ts` | Lineup, signals, rows, chart, slip, clock. |
| `frontend/components/event/event-ui.test.tsx` | Data, empty, loading, error, missing signal, WNBA. |
| `frontend/app/event/[eventId]/page.test.tsx` | MarketSelect mock keeps `isBinaryMarket`. |
| `docs/progress.md` | SPO-110b row. |

`PlayerHistoryStats`, `ResultsTable`, `PlayerProjectionPanel`, `TeamLineupPanel`, `PlayerDDTile`, and `MarketSelect` stay. Other pages and their tests still import them.

## Why

The prototype blends five signals into one percent and paints Supports / Neutral / Against. Those verdicts are not on daily picks, no-vig, history, or projection. The page shows the raw value. The headline percent is `DailyPick.probability` when a pick exists, and the caption says the tier is a display bucket on that rate (`readTier`: Strong ≥ 0.70, Playable ≥ 0.65, Lean ≥ 0.56, otherwise Pass). Without a pick there is no giant percent and no tier.

The other side of a slip is added only when history returns that side's `p_over` or `p_under` at the same line. The page does not store `1 - probability`. Pushes exist, so the complement is not the other side.

A lineup chip says "confirmed" only when every `source_snapshots.*.status` is `confirmed`. Consensus `status` is `projected | partial | unavailable` and is not treated as confirmed. WNBA lineups use the existing WNBA route. WNBA has no projection route, so that signal says projection is not available and the panel stays `SectionUnavailable`.

`commence_time` has no zone. The clock is the browser's local time and does not print "ET". Game logs have no home/away, so Venue is disabled. Teammate chips are names. The history route has `n`, not `season`, so the fifth-adjacent row is labeled "All-game hit rate".

Suggest returns names only. A no-vig request per name would call the odds provider for every player, so the list shows "No read" unless a daily pick stored a line and a rate. The selected player's posted line is the mode of the non-synthetic no-vig lines, then the pick threshold.

## Tests / Verification

- `npx vitest run` — 34 files, 224 tests, passed (`TZ=America/Chicago`), after merging the latest `feature/SPO-110a-design-system-shell-today`.
- `npx tsc --noEmit` — passed.
- `npm run lint` — passed, 0 warnings.

| Behavior | Test |
|---|---|
| Confirmed only when every snapshot says confirmed | `says confirmed only when every source snapshot says confirmed` |
| Mixed sources stay on the consensus word | `keeps the consensus word when sources disagree` |
| Missing lineup | `does not invent confirmed when the lineup is missing` |
| Five raw signals, no verdict | `shows raw rates and the stored rank without a verdict` |
| Missing signals | `leaves market, last-10, history, projection, and defense empty when the fields are missing` |
| WNBA projection gap | `says WNBA has no projection instead of a stand-in number` |
| Lean only for a stored pick | `prints a lean only for a stored pick` |
| Synthetic 0.5 is not a line | `ignores a synthetic double-double line` |
| Chart order and the line | `draws oldest to newest and marks the posted line` |
| Empty chart | `stays empty when the log is empty` |
| No invented other side | `uses the stored hit rate and does not invent the other side` |
| Other side is the history rate | `adds the other side from the history rate, not from one minus the pick` |
| No tier without a pick | `hides the tier when there is no stored pick` |
| No ET / UTC / PT | `does not print a timezone the payload does not carry` |
| Blank clock | `returns null for a blank time` |
| Header data | `renders the matchup and lineup chips from the payload` |
| Header loading | `shows a loading state without a matchup` |
| Header error | `shows an error and a retry` |
| Stat chips | `offers the prototype stats and the other markets the API supports` |
| Player rail | `renders stored leans and leaves the rest unlabeled` |
| Rail loading, empty, error | `shows loading, empty, and error states` |
| WNBA read | `renders a WNBA read with the projection gap and no verdict` |
| Read loading and error | `shows loading and error states` |
| Ask the agent | `asks the agent` |
| Chart bars | `renders bars for fixture games` |
| Chart loading, error, empty | `shows loading, error, and empty copy` |
| Venue disabled | `disables venue because home and away are not on the game log` |
| Route date | `uses the route date when fetching events for the detail page` |
| 3PM highlight, no DD edge on 0.5 | `highlights 3PM on its own card and does not edge a double-double against 0.5` |

Screenshots in `docs/task-summaries/SPO-110b-screenshots/` are the running app against a local fixture API. Players are Bam Adebayo, Tyler Herro, Jayson Tatum, A'ja Wilson, Breanna Stewart, and Jackie Young.

## Data gaps

| Missing field | Endpoint | What the page does |
|---|---|---|
| Signal verdict (Supports / Neutral / Against) | Not on daily picks, no-vig, player-history, or projection | Five rows show the raw value or "—". No verdict word. |
| Per-team confirmed as one lineup field | `GET /api/nba/lineups/{team}` and `GET /api/wnba/lineups/{team}`. Consensus `status` is `projected \| partial \| unavailable`. `source_snapshots.*.status` can be `confirmed \| expected \| projected` | Chip says confirmed only when every snapshot status is confirmed. Otherwise the consensus word. No lineup: "{abbr} lineup status unavailable". |
| Season-scoped hit rate | `GET /api/{nba\|wnba}/player-history` has `n`, not `season` | The row is "All-game hit rate" for `n=0`. |
| Opponent defense rank when null | `opponent_rank` and `opponent_position_rank` on projection and on `DailyPick` | "Opponent defense rank is not on this response." No rank and no Easy/Tough. |
| Tier as an API field | none | Badge is `readTier(DailyPick.probability)` only when a stored pick exists. |
| `home_or_away` on `GameLog` | Game log has opponent, `is_starter`, minutes, value | Venue stays disabled. "Home and away are not on the game log." |
| Games a teammate missed | `teammates` is a name list. `teammate_played` is a filter | Name chips only. "Names only. Games missed are not on this response." |
| Position on every player | Suggest returns names. `position` is on the selected player's projection | List meta is the team when a pick or a lineup roster has it. |
| Blended probability | no `combined_probability` or `signals[]` | Headline percent is `DailyPick.probability` when a pick exists. The bar is labeled no-vig consensus or hit rate. |
| Line and lean for every suggested name | Suggest is names. Daily picks keep `probability >= 0.65` | "No read" and no percent. The selected row can show a posted line. |
| Timezone | `commence_time` is ISO. No zone field | Local date and clock. No "ET". |
| Other side of a stored pick | `DailyPick` stores one direction. History may omit `p_over` or `p_under` | The other add button is hidden. The page does not save `1 - probability`. |
| WNBA projection | no WNBA projection route | "Projection is not available for WNBA." Panel is `SectionUnavailable`. |
| One payload of every player's line | no bulk props endpoint | Names from suggest. Lines from a pick or the selected player's no-vig mode. |

## Follow-ups

Picks, Bet Slip, and Method stay on their current pages until PR C. A bulk line for the player rail, a season parameter, venue on the game log, and a real signal verdict would each be a backend field before the page can show them.
