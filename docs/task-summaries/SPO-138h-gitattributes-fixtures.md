# SPO-138h — Mark recorded API fixtures as generated for GitHub

- **Ticket:** SPO-138h
- **Branch:** `feature/SPO-138h-gitattributes-fixtures`
- **Base:** `dev`
- **Depends on:** nothing.

## Summary

This PR adds `.gitattributes` with three `linguist-generated=true` rules for the recorded external API responses. GitHub then collapses those files in pull request diffs and leaves them out of the repository's language bar. A reviewer opening a PR sees the code first, and a recording is one "Load diff" click away.

SPO-138a (#94) shows why this matters. It adds 1,292 lines of code and tests, plus 32 recordings that are 2 MB of pretty-printed JSON (96 KB gzipped). The diff lists every one of those recordings.

## Changes

| Area | Files | Change |
|---|---|---|
| Repo | `.gitattributes` | New. `linguist-generated=true` for `backend/tests/fixtures/bdl/*.json`, `backend/tests/fixtures/odds_api_*.json`, `tests/fixtures/espn/**/*.json` |

## Why

- **Only recordings are marked.** The rules list the directories that `backend/tests/fixtures/README.md` and the explore scripts document as unchanged API responses. Hand-written fixtures stay visible in review:
  - `frontend/test/fixtures` (for example, `nba-no-vig-synthetic.json`);
  - `backend/tests/fixtures/player-double-double-one-sided.json`, which was copied from a frontend fixture;
  - every `.py` and `.md` file beside the recordings.
- **Nothing but GitHub's display changes.** File contents, `git diff`, `git log`, and CI behave as before. The PR header's line count still includes these files.
- **Collapsed is not hidden.** A recording that changes is still in the diff. Its integrity is checked by tests (for example, the capture registry in `test_bdl_client.py` checks each capture's keys, its request path, and that it has no auth header) and by the fabrication scan in each task summary.
- **Line endings are left for another PR.** `* text=auto` would change what Git stores, so it does not belong in this display-only change. Today the index holds 728 LF files, no CRLF, and one file with mixed endings (`docs/research/wnba-rollout/rotowire_wnba_sample.html`, a recording that should be marked `-text`).

## Tests / Verification

- **`git check-attr linguist-generated`** on every JSON under `backend/tests/fixtures/` and `tests/fixtures/`: 38 `true`. The one `unspecified` file is `player-double-double-one-sided.json`, as intended. `odds_api.py`, `record_fixtures.py`, `README.md`, and `frontend/test/fixtures/event/nba-no-vig-synthetic.json` are `unspecified`. SPO-138a's new recordings match `backend/tests/fixtures/bdl/*.json`.
- **No content change:** after `git add --renormalize .`, the only staged file is `.gitattributes`.
- **CI:** all 6 checks passed (Backend Tests 1744 passed). The run merged this branch onto `dev` at `fc3f5ed`, which already has #94's `langsmith==0.14.17` pin. Without that pin, Backend Tests and the walk-forward guard stop at pytest start-up, because langsmith 0.15.1 (released 2026-11-20) fails to import under pydantic 2.8.0.
- **Frontend:** not touched.

## Follow-ups

- [ ] After merge, check the "Files changed" tab of the next PR that touches recordings (SPO-138c onward): the recordings should be collapsed and labeled as generated.
- [ ] Line endings in a separate PR: `* text=auto`, `*.sh text eol=lf`, and `-text` for the mixed-ending RotoWire sample.

## Progress notes (for the docs PR)

- SPO-138h: recorded API fixtures are marked `linguist-generated` in `.gitattributes`, so GitHub collapses them in PR diffs.

---

**Ticket**: SPO-138h
**Branch**: `feature/SPO-138h-gitattributes-fixtures`
**Task summary**: `docs/task-summaries/SPO-138h-gitattributes-fixtures.md`

> Owner: review, then squash-merge into `dev`. Only the owner merges.
