# Decision — No-Vig redesign design system

- **Ticket:** SPO-110a (PR A of SPO-110)
- **Date:** 2026-11-10
- **Status:** Accepted

## Context

The November 2026 prototype (`docs/design/redesign-2026-11/`) restyles the product as No-Vig: a light canvas, a deep-purple brand, and a yellow accent. This PR lands the tokens, the type, the app shell, and the Today page. Picks, Bet Slip, and Method keep their current pages until a later PR.

Two older contrast bugs have to move with the tokens. `text-dark` was `#ebf1fb`, which is 1.13:1 on the white cards in `PlayerProjectionPanel`. `text-gray` was a blue-gray that is 2.26:1 on `bg-blue-50` in `PlayerDDTile` and the `ResultsTable` caption. Both fail WCAG AA body text (4.5:1).

## Tokens

| Role | Value | Use |
|---|---|---|
| Brand | `#3E0F8D` | Header button, hero, active fills |
| Brand deep | `#2F0A6E` | Hover on a brand fill |
| Brand soft | `#9564DD` | Borders and large type only |
| Brand tint | `#ECE6F7` | Active nav pill |
| Brand ink | `#2A0A60` | Text on the yellow accent |
| Accent | `#E4DA72` | Fills, and type that sits on brand |
| Canvas | `#EEEEEE` | Page background |
| Surface | `#FFFFFF` | Cards, header, tabs |
| Ink | `#1D1530` | Body text |
| Muted | `#625B70` | Secondary text |
| Line | `#DEDAE5` | Borders |

Radii follow the prototype: 10px for small controls, 14px for inputs and the mobile "see all" button, 20px for cards, 28px for the hero. The desktop header is 68px tall. These live in `frontend/tailwind.config.ts` and `frontend/app/globals.css`.

`#9564DD` on white is 4.08:1. That passes large text and fails body text, so `brand.soft` is not a body color.

## Fonts

`Instrument Sans` is the UI face. `JetBrains Mono` is the face for numbers: percents, ranks, the slate eyebrow, and the slip badge. Both load through `next/font/google` in `frontend/app/layout.tsx` as `--font-sans` and `--font-mono`. Tailwind `font-sans` and `font-mono` read those variables, so a page does not import a second copy.

## Contrast

The app canvas is light. `text-dark` is the ink `#1D1530` (about 17:1 on white, 15:1 on `#EEEEEE`). `text-gray` is `#625B70` (about 6.5:1 on white, 5.6:1 on the canvas, 5.9:1 on `bg-blue-50`). Older pages that put those utilities on white cards and blue captions stay readable without a per-page restyle.

`text-yellow` and `bg-yellow` no longer share a color. The fill stays `#E4DA72`. The utility `text-yellow` is `#5A5310` (about 7.8:1 on white and on the yellow fill). `#E4DA72` as text on white is about 1.6:1, so it cannot be a word color on a light page. On a dark surface, yellow words use `text-accent` (`#E4DA72`), which is about 12:1 on `#1D1530`. The about-page formulas sit on `bg-dark` and use `text-accent` for that reason.

The betting-agent panel is a dark island. It uses `text-on-dark` (`#F4EEFF`) and `text-on-dark-muted` (`#D9CEF0`). Those tokens exist so the light-theme ink is not painted onto the dark panel. `gray.light` stays `#D9CEF0` for the same reason: code-block labels on `bg-dark`.

Red text and red fills that carry white type use `#8E2C50`. Green words and white-on-green fills use Tailwind `green-800` (`#166534`, about 7.1:1). White on `blue-700` replaces white on `blue-500`. A green or blue at 500 as text on white is under 4.5:1.

## Component conventions

- `AppShell` is the only header and the only mobile tab bar. The brand link goes to that league's Today. The league switch is a sibling of that link, not a link inside a link.
- League is the URL. `isWnbaPath` is `pathname === "/wnba"` or a path under it. Today, Picks, and Bet Slip keep their section when the switch flips. Method is the shared `/about` page, so the switch leaves it for that league's Today. A route with no section (a player page) also goes to that league's Today.
- The slip badge reads `useBetSlip` on NBA paths and `useWnbaBetSlip` on WNBA paths. The two contexts stay mounted.
- "Ask the agent" and "Ask agent" call `openWidget()` from `AgentWidgetContext`. The existing widget stays mounted in `Providers`.
- `TodayBoard` takes `league: "nba" | "wnba"` and is the home route plus `/wnba`. It loads events and daily picks with TanStack Query. The two requests run together. Numbers on the cards come from `frontend/lib/today-board.ts`.
- A missing value is a sentence or a hidden node. It is not a zero and not a sample player. `formatPercent(null)` returns `—`.
- Tier labels (Strong play at 0.70, Playable at 0.65, Lean only at 0.56, otherwise Pass) are a display bucket on `probability`. They are not an API field. The daily-picks service only stores rows at or above 0.65 with at least 10 games, so Lean and Pass do not appear on Today with the current API.
- The hero says the card is a historical hit rate. It does not say the number blends market price, recent form, projection, and matchup. `DailyPick.probability` is the historical rate. There is no blended field.

## Rejected alternatives

1. Keep the dark canvas and a light `text-dark`. That keeps the agent widget as it was, and it makes the white projection cards unreadable. The QA finding is the white card.
2. Restyle every old page in this PR. Picks, Bet Slip, and Method are a later PR. Token changes that keep their existing class names readable are in scope. A new layout for those pages is not.
3. Request `min_probability=0.5` so Today can show the prototype's weaker leans. The analysis service drops a prop below 0.65 or under 10 games before the query filter runs. The lower query floor does not bring those rows back, and it would split the picks-page cache. Today uses the same default query as the picks page.
