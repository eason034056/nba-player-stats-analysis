# SPO-142c — Test the agent chat flag guards

- Ticket: SPO-142c
- Branch: `feature/SPO-142c-agent-flag-tests`
- Base: `dev` at `341a73b`
- Tests only. No production files changed. `frontend/app/wnba` and `docs/progress.md` are untouched.

## Summary

The flag-off coverage stays, and the seven enabled-path cases that were skipped while `AGENT_CHAT_UI_ENABLED` is `false` now run in CI. Each of those cases lives in its own file that mocks `@/lib/agent-chat-ui` to `{ AGENT_CHAT_UI_ENABLED: true }`, the same pattern as `AgentWidget.test.tsx`. A saved session with `isOpen: true` still leaves the widget unmounted. `submitAction` and `runRequest` are each shown, through the public hook, to return without calling `sendAgentChat` when the flag is off.

## Changes

| Area | File | Change |
|---|---|---|
| Mount | `frontend/app/providers.flag.qa.test.tsx` | Applied unedited. With a stale `agent_widget_state` of `isOpen: true`, Providers renders the page and no betting-agent dialog, and `sendAgentChat` is not called. |
| Shell | `frontend/components/AppShell.flag-on.test.tsx` | Ask stays on every NBA and WNBA route and both Ask controls open the widget. |
| Shell off | `frontend/components/AppShell.test.tsx` | The hidden-default case is a normal `it`. The three enabled cases moved out. |
| Event | `frontend/components/event/event-ui.flag-on.test.tsx` | “Ask the agent” and the mobile “Ask” call `onAsk`. |
| Event off | `frontend/components/event/event-ui.test.tsx` | The hidden-default cases are normal `it`s. The two enabled cases moved out. |
| Picks | `frontend/app/picks/page.flag-on.test.tsx` | “Review board” sends `review_board` with Stephen Curry in `visible_picks`. |
| Picks off | `frontend/app/picks/page.test.tsx` | “Review board” stays hidden as a normal `it`. |
| Slip | `frontend/app/betslip/page.flag-on.test.tsx` | “Review with agent” sends `review_slip` with Stephen Curry on the slip. |
| Slip off | `frontend/app/betslip/page.test.tsx` | “Review with agent” stays hidden as a normal `it`. |
| Context | `frontend/contexts/AgentWidgetContext.guards.test.tsx` | A harness calls `submitAction` and `retryLastRequest` from `useAgentWidget`. With the flag off, `submitAction` does not call `sendAgentChat` and leaves `threadId` empty. `retryLastRequest` is the public path into `runRequest`: one request is stored while the mock flag is on, then the flag is turned off and retry does not call `sendAgentChat`. |
| Context off | `frontend/contexts/AgentWidgetContext.flag.test.tsx` | The open-and-send refusal is a normal `it` against the real `false` constant. |

## Why

`vi.mock` is file-scoped, so one file cannot see the real `false` constant and a mocked `true` at the same time. Splitting the enabled cases keeps both states in the suite. `it.skipIf(!AGENT_CHAT_UI_ENABLED)` never ran those cases in CI because the constant is `false`.

`submitAction` returns before it writes `threadId` or calls `runRequest`. A click that only checks `sendAgentChat` cannot tell which guard stopped the request. An empty stored `threadId` shows `submitAction` returned first. `runRequest` is not on the hook. `retryLastRequest` calls it once a previous request exists, which is why the second test turns the mock flag on, sends once, then turns it off before retry.

## Tests

`npm test` from `frontend/` (`TZ=America/Chicago vitest run`): 91 files, 695 passed, 0 skipped.

`npx tsc --noEmit` and eslint on the touched test files passed.

The Providers case still uses `it.skipIf(AGENT_CHAT_UI_ENABLED)`. The constant is `false`, so that case ran. It is the only `skipIf` left in the frontend tests.

## Follow-ups

- `TodayBoard.test.tsx` and `EventDetail.fixtures.test.tsx` still branch on the real constant inside a larger test. The hidden-default assertions run. The enabled assertions in those two `if` blocks do not, because the constant is `false`. They were not among the seven `skipIf` cases.
- Set `AGENT_CHAT_UI_ENABLED` to `true` to restore the widget and the Ask / Review controls.
