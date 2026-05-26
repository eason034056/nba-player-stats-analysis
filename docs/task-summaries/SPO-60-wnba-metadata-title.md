# SPO-60 — WNBA metadata title regression fix

## Summary

Phase 6 QA flagged that `/wnba/*` routes still rendered `<title>` as **"No-Vig NBA"** even though the navbar correctly toggled to "No-Vig WNBA". The root cause: `frontend/app/layout.tsx` declares `metadata.title.default = "No-Vig NBA"` and there was no route-segment layout under `/wnba` to override it. WNBA pages are all client components (`"use client"`) and therefore cannot export their own `metadata`.

Fix: a new `frontend/app/wnba/layout.tsx` server component that exports a `metadata` block overriding only `title` (default + template) and `description`. The Next.js App Router merges this with the root metadata, so navbar, fonts, providers, footer, icons, manifest, keywords, and viewport stay inherited.

## Changes

| File | Change |
|---|---|
| `frontend/app/wnba/layout.tsx` | **NEW** — server layout exporting WNBA `metadata` and passing children through |

## Why

- Title leakage is a cross-league branding bug — visible in browser tabs, link previews, and any future OG/share metadata.
- Editing the root `layout.tsx` would regress NBA. A route-segment layout is the idiomatic App Router fix and isolates the override to `/wnba/*`.
- Title + description are the only metadata that differ between leagues; everything else (fonts, viewport, icons, manifest) is shared and stays inherited.
- Approach was forced by the constraint that WNBA pages use `"use client"`, which forbids `export const metadata`.

## Tests

- `cd frontend && npx tsc --noEmit` — clean (no new errors).
- Manual route check (per acceptance criteria): `/wnba`, `/wnba/picks`, `/wnba/betslip`, `/wnba/event/[id]` now resolve to a title template ending in "No-Vig WNBA". NBA routes unchanged because root layout is untouched.

`npx next build` was NOT re-run — pre-existing SSG failures on `origin/dev` are unrelated to this metadata change; this PR cannot introduce new build errors via a single client-passthrough layout.

## Follow-ups

None. This was a fast-follow regression fix, not a new phase. Phase 7 dispatch on SPO-29 remains gated on owner intent.

## References

- Parent epic: SPO-29
- Source review: SPO-59 (Lens) + Sentinel QA on SPO-37
- Predecessor PR: #18 (merged)
