# SPO-136. Self-host fonts with next/font/local

- Ticket: SPO-136
- Branch: `feature/SPO-136-self-host-fonts` (from `origin/dev` @ `8b8bbdc`)
- Base: `dev`

## Summary

`next build` no longer downloads fonts. Instrument Sans and JetBrains Mono are files under `frontend/app/fonts/`, loaded with `next/font/local`. The CSS variables stay `--font-sans` and `--font-mono`. `frontend/tailwind.config.ts` is unchanged.

## Changes

| File | Change |
|---|---|
| `frontend/app/layout.tsx` | Replaces `next/font/google` with `next/font/local`. Same weights, `display: "swap"`, and an Arial size-adjust fallback. |
| `frontend/app/fonts/InstrumentSans[wdth,wght].woff2` | Instrument Sans variable webfont. |
| `frontend/app/fonts/JetBrainsMono[wght].woff2` | JetBrains Mono variable webfont. |
| `frontend/app/fonts/InstrumentSans-OFL.txt` | SIL Open Font License 1.1 for Instrument Sans. |
| `frontend/app/fonts/JetBrainsMono-OFL.txt` | SIL Open Font License 1.1 for JetBrains Mono. |
| `docs/task-summaries/assets/SPO-136/` | Today and Picks screenshots at 1440 and 390, before and after. |

`docs/progress.md` is not changed.

## Font sources

Instrument Sans is the unmodified webfont from the font's repository.

- URL: `https://github.com/Instrument/instrument-sans/blob/7fa22308a3d0c94ee2b3cd537a1196b65db34a3e/fonts/webfonts/InstrumentSans[wdth,wght].woff2`
- Commit: `7fa22308a3d0c94ee2b3cd537a1196b65db34a3e` (2023-06-14, "feat: updated example gif")
- Name-table version: `Version 1.000;gftools[0.9.28]`
- Axes: `wdth` 75 to 100, default 100. `wght` 400 to 700, default 400.
- Size: 88,784 bytes
- SHA-256: `aa72922aafcc0dc18f36ec1d805b0212057dabe8b9d5b8b57f67035aea1b826d`

The layout pins `font-stretch: 100%` so the width axis stays at 100. That is the width Google Fonts was serving. ASCII outlines at weights 400, 500, 600, and 700 match the latin woff2 that `next/font/google` downloaded (family version string `Version 1.000;gftools[0.9.28]`). The file is the full webfont, 343 cmap entries, not a latin-only subset. The repository does not publish a separate latin-only woff2.

JetBrains Mono is the variable TTF from the google/fonts repo, packed as woff2. Outlines were compared to the source TTF at weights 400, 500, 600, 700, and 800 for code points 32 through 126. The comparison found no differences.

- Source URL: `https://github.com/google/fonts/blob/main/ofl/jetbrainsmono/JetBrainsMono[wght].ttf`
- Last commit that touched that path: `2e05c1cf00a6e4f40a4b931600a90881c26e15cd` (2020-11-18, "JetBrains Mono: Version 2.211 added")
- Name-table version: `Version 2.211`
- Axis: `wght` 100 to 800, default 400
- Packed file size: 71,660 bytes
- SHA-256: `b5eca976eda57d2f0ce9c90bb40bbf488bd9c76d5b676a6a1baec9732efadaba`

This is the same version string as the latin file `next/font/google` was downloading from `fonts.gstatic.com` (`jetbrainsmono/v24`, name-table `Version 2.211`). The JetBrains GitHub release v2.304 (2023-01-14) is a later cut. ASCII outlines in that release differ from the 2.211 file the site was already rendering, so this change uses 2.211.

The google/fonts tree ships the variable TTF, not a latin-only woff2. The packed file keeps every glyph in that TTF (1,179 glyphs).

`layout.tsx` registers the same weights the Google call used. Instrument Sans is 400, 500, 600, and 700. JetBrains Mono is 500, 600, and 700. Each weight is its own `@font-face` on the one variable file, which is how the Google CSS used the variable file. A CSS weight of 400 on a mono element still matches the 500 face.

## License

Both files are SIL Open Font License 1.1. The copyright lines do not name a Reserved Font Name. The license allows bundling and redistribution with software when the license text stays with the fonts.

- Instrument Sans license URL: `https://github.com/Instrument/instrument-sans/blob/7fa22308a3d0c94ee2b3cd537a1196b65db34a3e/OFL.txt`
- Committed copy: `frontend/app/fonts/InstrumentSans-OFL.txt`, 4,403 bytes, SHA-256 `9e27a72ed30eb49a08678f6a5d6ed98ec7ba5368f541637ee0683ec9134ef966`
- JetBrains Mono license URL: `https://github.com/google/fonts/blob/main/ofl/jetbrainsmono/OFL.txt`
- Committed copy: `frontend/app/fonts/JetBrainsMono-OFL.txt`, 4,399 bytes, SHA-256 `b2fe5e8987594e9ffd1d2ca52a2f5d73eb8335243893c5d6254b5ad69269591d`

The license text includes "bundled, embedded, redistributed and/or sold with any software".

## Why

CI run `43119355890` on `feature/SPO-135f-out-followups` failed in Frontend Lint & Type Check during `npx next build`. The stack is `next/font/google` loader.js:112, `TypeError: Cannot read properties of null (reading '1')`, on the `JetBrains_Mono` call in `frontend/app/layout.tsx`.

That line is:

```js
const ext = /\.(woff|woff2|eot|ttf|otf)$/.exec(googleFontFileUrl)[1];
```

`exec` returns null when the Google font URL does not end in `.woff`, `.woff2`, `.eot`, `.ttf`, or `.otf`. The build then throws. In this environment the current Google CSS still ends in `.woff2`, and a `next build` with the old `layout.tsx` succeeded. GitHub Actions received a URL the regex does not accept. Local files remove that download.

`display` stays `"swap"`, which is the default both loaders already used. `adjustFontFallback: "Arial"` matches `next/font/google` for these two families. Next's metric table uses Arial unless the family category is serif, and JetBrains Mono is monospace, so the Google fallback face was already Arial.

## Tests / Verification

Offline build. `/etc/hosts` contained `127.0.0.1 fonts.googleapis.com fonts.gstatic.com`. Both curls failed before the build:

```
curl: (7) Failed to connect to fonts.googleapis.com port 443 after 0 ms: Couldn't connect to server
curl: (7) Failed to connect to fonts.gstatic.com port 443 after 0 ms: Couldn't connect to server
```

Command, from `frontend/`:

```
NEXT_TELEMETRY_DISABLED=1 npx next build
```

Result: exit 0. Compiled successfully. Generated 10 static pages, including `/wnba`, `/wnba/betslip`, `/wnba/picks`, and `/wnba/player/[name]`. The emitted CSS has no `fonts.googleapis.com` and no `fonts.gstatic.com`. A second build with the same hosts entries also compiled and generated the same 10 routes.

`grep -rn 'next/font/google' frontend/ --exclude-dir=node_modules --exclude-dir=.next` prints nothing. The same grep without those excludes matches files inside `frontend/node_modules/next`, which is the Next.js package and is not part of this change.

Computed style on `next start`, with those hosts still blocked, after `document.fonts.ready`.

- `body` font-family: `__sans_d4a84c, __sans_Fallback_d4a84c, "Instrument Sans", system-ui, sans-serif`
- A `.font-mono` element (`NV` in the header) font-family: `__mono_e3df3a, __mono_Fallback_e3df3a, "JetBrains Mono", ui-monospace, monospace`
- Loaded faces included `__sans_d4a84c` at 400, 600, and 700, and `__mono_e3df3a` at 700.

Screenshots, animations disabled, no overlay. Today at 1440 and at 390 is pixel-identical to the Google-font build (0 differing pixels). Picks at 1440 differs by 2 pixels. Picks at 390 differs by 4 pixels. Each difference is a one-channel shift of at most 7 on an icon edge, not a text change.

- `docs/task-summaries/assets/SPO-136/before-today-1440.png`
- `docs/task-summaries/assets/SPO-136/before-today-390.png`
- `docs/task-summaries/assets/SPO-136/before-picks-1440.png`
- `docs/task-summaries/assets/SPO-136/before-picks-390.png`
- `docs/task-summaries/assets/SPO-136/after-today-1440.png`
- `docs/task-summaries/assets/SPO-136/after-today-390.png`
- `docs/task-summaries/assets/SPO-136/after-picks-1440.png`
- `docs/task-summaries/assets/SPO-136/after-picks-390.png`

From `frontend/`:

- `npx vitest run`. 66 files, 517 tests, passed.
- `npx tsc --noEmit`. Exit 0.
- `npm run lint`. No ESLint warnings or errors.

## Follow-ups

None.
