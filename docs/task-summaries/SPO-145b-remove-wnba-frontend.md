# SPO-145b — remove the WNBA frontend

## Summary

The Next.js app is NBA-only. `/wnba` and the old league pages are gone, the shell has no league switch, and the second bet slip is gone. Shared Today, event, picks, and history UI keep the NBA path they already rendered. Backend modules, `data/`, `scripts/`, CI, and `docs/progress.md` are unchanged by this ticket.

`origin/dev` moved to `3b5ee9c` while the branch was open (`#111` and `#112`). That tree was merged in with a normal merge. Product docs were resolved on top of it so the README, the Vercel notes, and `docs/dev-doc.md` do not describe a second league.

## Changes

| Area | What changed |
|---|---|
| Routes | Deleted `frontend/app/wnba/**` (home, layout, event, picks, bet slip, and `/wnba/player/[name]` plus its test). Those URLs are no longer pages. |
| Shell | `shell-nav.ts` and `AppShell.tsx` only know Today, Picks, Bet Slip, and Method. No switch, no disabled control, no commented path. |
| Slip | Deleted `WnbaBetSlipContext.tsx` and unhooked it from `providers.tsx`. `BetSlipProvider` deletes `wnba_betslip_picks` from `localStorage` on load, before it reads `betslip_picks`. Nothing parses the retired key. |
| API client | Removed `getWNBAEvents`, `calculateWNBANoVig`, `getWNBAPlayerSuggestions`, `getWnbaDailyPicks`, `triggerWnbaDailyAnalysis`, `getWNBATeamLineup`, and the WNBA CSV / history / double-double helpers from `frontend/lib/api.ts`. |
| Shared UI | `TodayBoard`, `EventDetail`, event chrome, `PlayerDDTile`, and `PlayerHistoryStats` no longer take a league prop or a `/wnba` path check. Event links are `/event/<id>`. Team abbreviations are the NBA table only. |
| Types | `SeasonLeague` is gone. `recentGamesOptions()` is the 82-game list. `LeagueSegment` is `"nba"`. |
| Tests and fixtures | Deleted `frontend/test/fixtures/**/wnba-*.json` and the `wnba` object in `spo-121b/qa-review.json`. WNBA cases were removed from component, page, and QA tests. NBA assertions that lived in the same files were kept. |
| Docs | README title, routes, and CSV wording are NBA-only. `docs/deployment/vercel.md` examples no longer use `/api/wnba/events`. About drops the second-league copy and keeps The Odds API credit. `docs/dev-doc.md` no longer says a second league is first-class. Historical research, decision, and older task-summary files stay. |

## Why

The product decision is one league. A switch that only disabled the second league would still ship the routes, the client, and a second `localStorage` key. Collapsing onto the NBA branch keeps the classes, the ET clock, the blend percent, and the 82-game season the NBA pages already used.

The retired key is `wnba_betslip_picks`. After the provider that parsed it is gone, a corrupt value cannot crash the shell, because nothing reads it. The load effect still deletes it so a later reader cannot pick it up by mistake.

## Tests

`cd frontend && npm test` (`TZ=America/Chicago vitest run`): **89 files, 669 tests, all passed.**

Mutation check, after that green run: `BetSlipProvider` skipped `localStorage.removeItem("wnba_betslip_picks")`. Three tests went red:

- `AppShell` “drops a retired slip key so it cannot be parsed” — expected `null`, received `"{not-json"`.
- Both reverse-slip tests that seed the same key and expect it to be gone.

`removeItem` was put back. Those two files were re-run (11 passed), then the full suite was re-run (669 passed).

`next dev` on port 3456: `/`, `/about`, `/picks`, and `/betslip` returned **200**. `/wnba`, `/wnba/picks`, `/wnba/betslip`, `/wnba/event/evt-lva-nyl`, and `/wnba/player/A%27ja%20Wilson` returned **404**. The HTML for `/` has no league switch and no second-league string.

## Follow-ups

- SPO-145a still owns `/api/wnba` and `backend/app/api/wnba.py`. The README tree still names that file because the module is on disk.
- `data/wnba_player_game_logs.csv` is still in the repo. The product README no longer tells a reader to download it.
- `#108` (SPO-144) was not in the two commits that landed on `origin/dev` during this work. This branch already contains `3b5ee9c`.

## Progress notes (for the docs PR)

- Frontend routes, shell, slip, client, fixtures, and current product docs are NBA-only.
- `docs/progress.md` was not edited.
- Backend, `data/`, `scripts/`, and CI were not edited.
- Suite: 669 passed / 89 files. Mutation of the retired-slip flush turned 3 tests red, then the flush was restored.
