# SPO-110c — Picks, Bet Slip, Method, and the agent panel

## Summary

NBA only; WNBA paused, routes unchanged.

Daily Picks (`/picks`), Bet Slip (`/betslip`), Method (`/about`), and the Ask agent panel use the November 2026 layout. The league switch still reaches the existing WNBA routes. Those pages were not restyled.

Numbers come from `getDailyPicks`, `getLineups`, and the probabilities already stored on the slip. A field the API does not return stays blank or is called out as planned. The prototype's sample board is not used. The agent opens only from Ask the agent, Ask agent, Ask on a pick, Review board, or Review with agent. There is no floating launcher.

## Changes

| File | Change |
|---|---|
| `frontend/app/picks/page.tsx` | NBA board data: date, team filter, session storage, re-analyze, lineups, slip, reverse add, ask, review board. |
| `frontend/components/picks/DailyPicksBoard.tsx` | NBA picks layout. Confidence and market chips filter the fetched list. |
| `frontend/lib/picks-board.ts` | Row model. Tags quote stored fields only. |
| `frontend/app/betslip/page.tsx` | Renders the NBA slip screen. |
| `frontend/components/betslip/BetSlipScreen.tsx` | NBA slip, lineup badges, share card, review with agent. |
| `frontend/lib/bet-slip-board.ts` | Mean and product of the stored rates. Detail links keep the local date. |
| `frontend/app/about/page.tsx` | Method copy for the vig formula, the stored fields, and the display tier. |
| `frontend/components/AgentWidget.tsx` | Light drawer on desktop, full screen on a narrow viewport. Workspace stays the dark console. |
| `frontend/components/agent-widget/AgentWidgetTranscript.tsx` | Light transcript, bubbles, and empty greeting. |
| `frontend/components/agent-widget/AgentWidgetComposer.tsx` | Light composer. Send is white on brand. |
| `frontend/app/globals.css` | Light-surface remap so verdict utilities stay readable. |
| `frontend/lib/player-dd.ts` | `formatPercent` prints `—` for NaN and infinities. |
| `frontend/test/fixtures/picks/` | NBA daily picks, empty board, and a Miami lineup. |
| `docs/progress.md` | SPO-110c row. |

`app/wnba/picks` and `app/wnba/betslip` are unchanged. `useBetSlip` and `useWnbaBetSlip` stay separate.

## Why

這次只改 NBA 的四個畫面。WNBA 的 picks 和 bet slip 維持原本的頁面，聯賽開關和路由都留著，所以共享的 agent panel 與 `formatPercent` 不能把 WNBA 弄壞。

版面上的百分比是 `DailyPick.probability`（歷史命中率），不是五個訊號混成的機率。API 沒有 `signals[]` 或 `combined_probability`，Method 把 blend 和 Supports / Neutral / Against 標成 planned。Tier 是顯示用分桶（Strong ≥ 0.70、Playable ≥ 0.65、Lean ≥ 0.56，其餘 Pass），不是 API 欄位。每日精選服務只留 ≥ 0.65 且至少 10 場，所以 Lean 和 Pass 不會出現在這張板。

`text-yellow-600` 原本在 NBA picks 的對戰難度標籤上，對比不夠。新的板子不再畫 Easy / Avg / Hard。有 `opponent_position_rank` 或 `opponent_rank` 才顯示 `Def #`，數字用 `text-muted`。過期徽章用 `text-yellow`（`#5A5310`）。

Bet slip 的 all hit 是已存機率的乘積，avg 是平均，頁面寫明這不是聯合模型。非有限數字顯示 `—`。分享卡是畫面上那張紫色卡，頁尾是 `novig · for research only`。

Picks 的反向加入仍沿用既有行為，把 `1 - probability` 存進 slip。Game page 沒有這個做法，這裡不把它拿掉。

Agent 預設面板改成淺色抽屜（桌面 `data-layout="drawer"`，窄螢幕 `data-layout="full"`）。Workspace 維持深色，分析面板的 on-dark 字色才讀得清楚。

## Tests / Verification

- `npx vitest run` — 39 files, 242 tests, passed (`TZ=America/Chicago`).
- `npx tsc --noEmit` — passed.
- `npm run lint` — passed, 0 warnings.
- Backend pytest: not run. This change is frontend only.
- Integration test: SKIPPED (env unset).
- Fabrication scan (Mock without fixture): PASS. New board tests parse `frontend/test/fixtures/picks/`.

| Behavior | Test |
|---|---|
| Tags quote projection and rank, and omit a missing rank | `quotes stored projection and rank fields and skips missing ones` |
| NaN hit rate renders `—` | `renders a non-finite hit rate as a dash` |
| Fixture order and Playable tier | `ranks the fixture by historical hit rate` |
| `formatPercent(NaN)` and infinities are `—` | `renders an em dash for NaN and other non-finite values` |
| Slip mean and product | `uses the mean and the product of the stored rates` |
| Non-finite slip summary | `renders a dash when a stored rate is not finite` |
| Board data, no prototype names, no `text-yellow-600` | `shows fixture players and only the fields the payload includes` |
| Confidence and market chips | `hides players that miss the confidence or market chip` |
| Empty board | `shows the empty message from the response` |
| Loading | `shows a loading state without player names` |
| Error and retry | `shows an error and retries` |
| Method describes the vig and marks the blend planned | `describes the vig math and marks a blend as planned` |
| Add to slip and lineup aligned | `shows a visible add-to-slip action for each pick card` |
| Ask sends the selected pick | `opens the widget from a pick card and sends the selected pick context` |
| Team filter prune | `prunes invalid v2 team filters after hydration` |
| Stale board | `shows a stale board badge when analysis is older than fifteen minutes` |
| Detail link date | `includes the selected date in pick detail links` |
| Empty slip | `renders the empty state when no picks are saved` |
| Share actions | `renders saved picks and share actions` |
| Review slip | `reviews the current slip through the agent widget` |
| Slip detail local date | `includes a local date query in detail links` |
| Agent drawer, no floating launcher | `starts collapsed, opens from Ask the agent, and closes on Escape in panel mode` |
| Mobile agent is full screen | `shows analysis as a bottom sheet on mobile workspace` |

Screenshots in `docs/task-summaries/SPO-110c-screenshots/` are the running NBA app against a local fixture API. Players are Bam Adebayo, Joel Embiid, and Tyrese Haliburton. No WNBA screenshots.

## Data gaps

Empty states stay empty. The backend tickets below own the missing fields. This page does not invent them.

| Gap | Ticket | What these screens do |
|---|---|---|
| `top_read`, tier as a stored field, the Lean tier, and both sides of a pick | SPO-111 | The tier badge is `readTier` on `DailyPick.probability`. Lean and Pass do not appear, because the service only returns rows at or above 65%. Reverse add on Daily Picks still stores `1 - probability`, which is the existing picks behavior. There is no second stored side. |
| `signals[]` verdicts and `combined_probability` | SPO-112 | Hidden. Method marks one blended probability, and Supports / Neutral / Against, as planned. |
| Timezone, position, lineup status, `home_or_away`, season hit rate, opponent rank, teammate games missed | SPO-113 | The clock is local and has no zone label. A null rank is omitted. The lineup badge comes from the lineups route, not from `lineup_confirmed`. Position, season hit rate, home or away, and games missed stay off these screens. |
| Bulk props | SPO-114 | Daily Picks renders the rows the daily route returns. No extra lines are filled in. |

## Follow-ups

WNBA picks and bet slip stay on their current pages until a later pass. SPO-111 through SPO-114 are the backend fields these empty states are waiting on.
