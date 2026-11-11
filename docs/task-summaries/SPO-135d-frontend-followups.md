# SPO-135d — Injury tag allow-list and projection cleanup

- Ticket: SPO-135d
- Branch: `feature/SPO-135d-frontend-followups`
- Stacked on #71. This PR's base is `feature/SPO-135b-remove-projections-frontend` @ `038f859`. #71 targets `dev`.
- Frontend only. WNBA routes are unchanged.

## Summary

The picks board shows an injury tag only for `Out` and `Questionable`. A literal `Doubtful` is shown as `Questionable`. `Probable`, `Day-To-Day`, `Active`, null, and any other value show no injury tag. The `Lineup confirmed` tag is gone. `LineupStatusBadge` still covers the lineups route. An Out pick whose `combined_probability` is null still renders: the board, the event read, and the slip print `—` for the blend. They do not print `NaN` or `0%`. Today board and agent copy no longer say the probability is built from a projection.

## Changes

| Area | File | Change |
|---|---|---|
| Tags | `frontend/lib/picks-board.ts` | Injury tag allow-list. Removed the `Lineup confirmed` tag. `Lineup unconfirmed` stays. |
| Copy | `frontend/components/TodayBoard.tsx`, `frontend/components/AgentWidget.tsx`, `frontend/components/agent-widget/AgentWidgetTranscript.tsx` | Replaced the projection phrase with recent form, matchup and defense rank, and rest. |
| Comments | `frontend/lib/api.ts` | Dropped `projections` from the two WNBA-vs-NBA comments. |
| Indent | `frontend/components/EventDetail.tsx` | Indented the WNBA unavailable panel. Copy is unchanged. |
| Tests | `frontend/lib/picks-board.test.ts`, `frontend/components/picks/DailyPicksBoard.test.tsx`, `frontend/lib/out-pick-render.test.tsx` | Allow-list, no lineup-confirmed tag, Out plus a null blend. |
| QA | `frontend/components/picks/spo135-contract.qa.test.tsx`, `frontend/test/fixtures/picks/nba-daily-picks-spo135.json` | #71 QA patch, kept as its own commit. |

## Why

PR #72 stores NBA `injury_status` as `Out`, `Questionable`, `Probable`, or `Day-To-Day`. Doubtful is stored as `Questionable`. Anything else is null. `lineup_confirmed` stays null. An Out pick stays on the board with `combined_probability` null. Showing every non-empty status, or a `Lineup confirmed` tag, would disagree with that. The projection sentence was left over from before #69 removed that feed.

## Copy

Today board, before: `Each prop gets one probability, built from market prices, recent form, projection and matchup. Start with the strongest calls, or open any game.`

Today board, after: `Each prop gets one probability, built from market prices, recent form, matchup and defense rank, and rest. Start with the strongest calls, or open any game.`

Agent header, before: `Checks market, form, projection and matchup`

Agent header, after: `Checks market, form, matchup and defense rank, and rest`

Agent empty transcript, before: `I check any prop against market price, recent form, projection and matchup. What do you want to look at?`

Agent empty transcript, after: `I check any prop against market price, recent form, matchup and defense rank, and rest. What do you want to look at?`

## Tests

- `npx vitest run` from `frontend/`: 66 files, 520 tests, passed. The QA file is 12 of those.
- `npx tsc --noEmit`: passed.
- `npm run lint`: passed, 0 warnings.
- `npm run build`: passed. `/wnba`, `/wnba/event/[eventId]`, `/wnba/picks`, `/wnba/betslip`, and `/wnba/player/[name]` are in the route table.

## Screenshots

`next start` against a local mock with one Out pick (Jimmy Butler, `combined_probability` null) and one Questionable pick (Bam Adebayo, blend 0.74). No dev overlay and no React Query icon. The Out card shows `—`, the tag `Out`, and `Def #9`. The Questionable card shows `74%`, `Playable`, and the tag `Questionable`. Neither card shows `NaN`, `0%`, or `Lineup confirmed`.

Those two statuses already printed as tags before this change, and `lineup_confirmed` is null, so this mock does not change the board. No before/after pair.

## Follow-ups

- `Lineup unconfirmed` still appears when `lineup_confirmed` is false. The badge from the lineups route was left alone.
- A null blend prints `—`. The bar and the strong count still use `boardRate`, which falls back to the historical probability when the blend is missing. Jimmy Butler's card is a dash and still counts toward strong because his stored rate is 0.72.
- The picks-board footer still says projection, edge, and minutes appear only when the response includes them. That sentence is still true.
- WNBA copy, including the unavailable projection panel, is unchanged.
