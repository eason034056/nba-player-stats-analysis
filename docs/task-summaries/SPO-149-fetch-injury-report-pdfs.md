# SPO-149 — Fetch official NBA injury-report PDFs

- **Ticket:** SPO-149
- **Branch:** `feature/SPO-149-fetch-injury-report-pdfs`
- **Base:** `dev` (`ce54ac1`)
- **Repo:** public, and it stays public

## Architect sketch

The slot mapper is pure. The network, the clock, and the disk sit at the edges. Callers match a tag. They do not catch an exception to learn that a file is missing.

- `SlotKey` — `instant` (Eastern publish time), `format_name` (`hour` or `minute`), `filename`, `url`. Built only by `report_slot`.
- `FetchResult` — `Stored` (`tag=stored`), `Missing` (`tag=missing`), `Blocked` (`tag=blocked`), `Failed` (`tag=error`).
- `RunReport` — `results`, `paused`, `requests_made`.
- `LocalInjuryReportStore` — read and write the gitignored cache. No S3 client.
- `RateLimiter` — `acquire` and `retry_gap`. The floor is `MIN_GAP_SECONDS` (1.0). The cap is 60 seconds.
- `Clock` / `SystemClock` / `FakeClock` — tests advance time only inside `sleep`.

`decision_time` is tip UTC minus 3 hours, the same offset as `game_as_of` in migration 005. A NULL tip is skipped. The SQL midnight fallback in `game_as_of` is not used here, because a missing tip is not a real 00:00 report.

## Summary

The fetcher downloads one official injury-report PDF per URL from `https://ak-static.cms.nba.com/referee/injury/`, waits at least one second between requests, and writes the file plus a JSON sidecar under `INJURY_PDF_DIR` (default `/workspace/nba-injury-pdf`). A 403 on a URL that was never stored is recorded as missing and is not retried in that run. A backfill does not request a URL that is already stored or already recorded missing. The live slot may check a recorded 403 again on the next 15-minute tick.

`backfill --season 2021-22` reads tip times from Postgres, keeps 2021-22 and later, drops NULL tips and postponed games, and fetches each distinct tip-minus-3-hour slot once. `current` fetches the slot for now. Both support `--dry-run` (print URLs, no network). The scheduler job `injury_pdf_fetch_current` runs at minute 0, 15, 30, and 45, and only when `INJURY_PDF_FETCH_ENABLED` is true and the Eastern date has a non-postponed NBA game. The flag defaults to false, so a merge does not start fetching.

There is no new HTTP route, page, or feed. No PDF bytes are committed. CI fails if `git ls-files` contains a `.pdf` path, any case. Upload to S3 stays in `scripts/sync_raw_to_s3.sh`. boto3 is not a dependency.

## Changes

| Area | Files | Change |
|---|---|---|
| Slot map | `backend/app/services/injury_report_slots.py` | Pure Eastern filename map, one cutover at 2025-12-22 09:00 ET, DST walk in UTC |
| Result types | `backend/app/services/injury_report_types.py` | `Stored`, `Missing`, `Blocked`, `Failed`, `RunReport` |
| Cache | `backend/app/services/injury_report_store.py` | PDF plus sidecar, atomic replace, 403 sidecar with no PDF |
| Fetch | `backend/app/services/injury_report_fetcher.py` | httpx 0.27.0, 1s floor, backoff, pause after 5 retryable failures |
| Games | `backend/app/services/injury_report_games.py` | Season tips and the game-day check |
| CLI | `backend/scripts/fetch_injury_reports.py` | `backfill` and `current`, `--dry-run` |
| Scheduler | `backend/app/services/scheduler.py` | 15-minute job, registered only when the flag is on |
| Settings | `backend/app/settings.py`, `env.example`, `docker-compose.yml` | Flag default false, cache dir, named volume |
| Sync | `scripts/sync_raw_to_s3.sh` | Optional fourth prefix, still no `--delete` |
| Infra | `infra/aws/locals.tf`, `outputs.tf`, `README.md`, `docs/deployment/aws.md` | Prefix `nba-injury-pdf/`. Get, Put, List. No delete |
| Guard | `.github/workflows/ci.yml`, `.gitignore` | CI rejects a tracked PDF. Ignore `nba-injury-pdf/` only |
| Tests | `backend/tests/test_spo149_injury_report_pdfs.py`, `test_spo132_rds_s3.py` | Behavior tests and the three-prefix sync case |
| Fixtures | `backend/tests/fixtures/nba_injury_cdn/` | Recorded headers, the real 403 XML body, synthetic replay bytes, README |

## Why

- **One cutover.** Hour files through the morning of 2025-12-22: `HHAM` / `HHPM` is the HH:30 report, so 4:00 PM ET uses `03PM`. Minute files from 2025-12-22 09:00 ET: the file stamped at exactly T is a few seconds late, so 4:00 PM ET uses `03_45PM`. A decision at the cutover instant still uses the 08:30 hour file.
- **The spring-forward gap is a real minute walk.** Subtracting a minute from an Eastern datetime inside the missing 2:00–3:00 hour produces a wall clock of 2:30 whose UTC instant is later, not earlier. `_latest_mark` walks UTC and converts each instant to Eastern. 2024-03-10 03:00 EDT selects `01AM` (1:30 EST). 03:30 EDT selects `03AM`.
- **403 is missing, until it is not.** The CDN returns 403 with `application/xml` when the object is absent. That is recorded and the failure streak is reset, so a run of not-yet-posted slots does not pause the live job. A 403 on a URL that already had a stored PDF pauses and leaves the PDF in place. A 200 that is not a PDF (HTML or XML) pauses immediately.
- **Retries never speed up.** `retry_gap` is `min(60, 1.0 * 2^(n-1))` and is never below 1 second. Five consecutive 429s, 5xxs, or timeouts pause the run. Later URLs in that run are not requested.
- **No delete on the injury prefix.** The sync script does not pass `--delete`. A partial local cache must not remove remote PDFs. The runtime IAM policy has `s3:GetObject`, `s3:PutObject`, and `s3:ListBucket` on the prefix. It has no `s3:DeleteObject`.
- **The repo stays public.** The terms limit for that is: no PDF and no PDF contents in the repo, and no public route. The cache directory is gitignored. `*.pdf` is not globally gitignored, so a staged `x.pdf` is visible to the guard.

## Tests / Verification

Throwaway PostgreSQL 16 on `127.0.0.1:5441`, database `test`. Not port 5434. Docker was not used: `docker` was absent, and after `docker.io` installed, the service start was denied (`policy-rc.d`, no systemd). The suite used a local cluster on the port and database the brief named.

- **This ticket:** `pytest tests/test_spo149_injury_report_pdfs.py` — 47 passed, including the Postgres tip test.
- **Sync script:** the three existing prefixes still sync when `INJURY_PDF_DIR` is missing, with no `--delete`. When the directory exists, the fourth prefix is added and `--delete` is still absent.
- **Full backend suite:** `pytest -q` — **1926 passed, 11 skipped, 4 xfailed, 0 failed** (118.66s). `test_spo132b_optional_vpc.py::TestVpcIdConsole` passed here (3 tests). Those were the only failures the brief allowed, and they did not fail.
- **Full backend suite after the QA fixes:** `pytest -q` on the same throwaway Postgres — **1935 passed, 11 skipped, 4 xfailed, 0 failed** (115.63s). `tests/test_spo149_injury_report_pdfs.py` is 59 passed. `git ls-files | grep -i '\.pdf$'` printed nothing.
- **Terraform:** `terraform fmt -check` and `terraform validate` in `infra/aws` with Terraform 1.9.8. `terraform init -backend=false` only. No plan, no apply, no AWS credentials.
- **CLI:** `python -m backend.scripts.fetch_injury_reports current --dry-run` printed one URL and did not open a connection to the CDN:

```
https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-24_03_45AM.pdf
```

That was 2026-11-24 03:47 ET, so the minute-format slot is 03:45. `git ls-files | grep -i '\.pdf$'` printed nothing.

### Two CDN requests

Both used `User-Agent: sportslab-injury-pdf/1.0`, about one second apart. The bodies were hashed and discarded. Cookies and request-trace headers were not written into the fixtures.

| URL | Status | What was kept |
|---|---|---|
| `Injury-Report_2024-11-14_10AM.pdf` | 200 `application/pdf`, 64977 bytes, `Last-Modified: Thu, 14 Nov 2024 15:30:04 GMT` | sha256 `47b5bb60d173b97f299a24ec2f6e8eba9571200e0c5edc4fa22c02b1af2157ea` |
| `Injury-Report_2024-11-14_10_00AM.pdf` | 403 `application/xml`, 263 bytes, no `Last-Modified` | sha256 `fc52b223153d5749e72499e1d0586eba230824d5bb3a757b8b54341212011e9d` |

The 10AM file is the 10:30 ET report (a few seconds after :30). The minute-format name on an hour-format day is a first-time 403, so it is missing, not a block. The CDN did not block the client.

### Mutation checks

Each change was restored. The four tests passed again after the restore, and the full suite ran on the restored code.

1. **Remove the 1 second gap.** `MIN_GAP_SECONDS = 0.0`. `test_minimum_gap_over_eleven_files` failed at the literal `assert all(gap >= 1.0 for gap in gaps)`.
2. **Remove the cache skip.** The `reuse_stored` branch was forced off. `test_second_run_over_cached_urls_makes_no_http_calls` failed because the second run requested the missing URL.
3. **Retry a 403.** The missing-file branch was forced off and 403 was treated as retryable. `test_missing_slot_is_one_403_and_is_not_retried` failed: the same URL was requested 5 times instead of once.
4. **Tracked PDF.** `printf 'not a pdf\n' > x.pdf` and `git add x.pdf`, not committed. `test_git_tracks_no_pdf` failed with `assert ['x.pdf'] == []`. The CI step printed `x.pdf` and `tracked PDF files are not allowed` and exited 1. `git reset HEAD x.pdf` and `rm x.pdf`. `git ls-files` then showed no PDF.

## Blast radius

| Surface | Result |
|---|---|
| Scheduler, flag off | `injury_pdf_fetch_current` is not registered. Existing scheduler tests still pass. The handler returns before HTTP if the flag is off. |
| Scheduler, flag on | Cron minute `0,15,30,45`, `replace_existing`, `max_instances=1`, `coalesce`. No fetch when the pool is down or the Eastern date has no non-postponed NBA game. |
| `test_spo132` sync | Three prefixes and no `--delete` when the injury directory is missing. Four prefixes and no `--delete` when it exists. |
| Compose and `env.example` | `INJURY_PDF_FETCH_ENABLED` defaults to false. |
| Terraform | Prefix added to `local.s3_prefixes`. IAM policy is the same document, updated in place. One new empty prefix marker in `s3.tf` (`for_each` on that set). No `s3:DeleteObject`. Lifecycle still expires only current objects under `pg-dumps/`. Objects over 128KB can move to infrequent access; the sample PDF was 64977 bytes. |
| `.gitignore` | `nba-injury-pdf/` only. A global `*.pdf` ignore would hide the `x.pdf` mutation from `git ls-files`. |
| Sync excludes | `*.partial` is excluded on every prefix. The three-prefix sync still runs three times and still has no `--delete`. The injury prefix is still the fourth, still with no `--delete`. |
| CLI exit codes | A season before 2021-22 is still 2. A Postgres failure on backfill is still 1. A bad `Last-Modified` no longer raises, so it is not exit 2. `current --dry-run` is 0 and does not connect. |
| Public routes | None added. |

## Terms limits

- One request per second inside the fetcher. Retries wait 1, 2, 4, 8 seconds, then pause. Never faster.
- Cache by URL. A stored PDF is not fetched again. A recorded 403 is not fetched again during backfill. The current slot may recheck one 403 on the next tick, not in a loop.
- No mass HEAD of every slot. Backfill requests only the tip-minus-3-hour slot, deduped.
- No official PDF in git, in CI artifacts, or on a public route. Tests use `b"%PDF-1.4 synthetic"`.
- The local cache directory is gitignored.
- A block (HTML or non-PDF body, 403 on a URL that used to exist, or five retryable failures) pauses the run.
- The repo is public and stays public. The guard is `backend/tests/test_spo149_injury_report_pdfs.py::TestRepoGuard::test_git_tracks_no_pdf` and the `Refuse tracked PDF files` step in `.github/workflows/ci.yml`.

## Eason's terraform step

Run `terraform plan` in `infra/aws` and confirm **0 to destroy**. The intended change is an in-place IAM policy update plus one new empty `aws_s3_object` for `nba-injury-pdf/`. It must not replace the bucket, RDS, or the VPC. Do not apply a plan that destroys any of those.

If NBA blocks access or ends the agreement: set `INJURY_PDF_FETCH_ENABLED=false` and stop the CLI. An admin deletes the stored PDFs. The runtime IAM user cannot delete them, on purpose.

## QA follow-up on #128

Review `6036580948` at `09c1853`. One later commit. No amend.

### Red runs, before the fixes

| Test | Result |
|---|---|
| `test_test_module_does_not_build_cdn_payloads_inline` | Failed. The module still contained `headers={`. |
| `test_malformed_last_modified_is_stored_and_the_next_url_is_fetched` | Failed. `ValueError: Invalid date value or format "not-a-date"` from `parsedate_to_datetime`. |
| `test_first_seen_html_403_pauses` | Failed. `paused` was false. The HTML 403 was recorded as missing. |
| `test_dry_run_documents_when_postgres_opens` | Failed. The docstring still said `does not open a socket`. |
| `test_current_dry_run_does_not_open_postgres` | Passed before the edit. `current --dry-run` already skipped Postgres. |
| `test_backfill_dry_run_opens_postgres_and_not_the_cdn` | Passed before the edit. The backfill dry-run already opened Postgres and did not call the CDN. The missing piece was the docstring. |
| `test_sync_prefixes_and_no_delete` and `test_injury_pdf_prefix_syncs_without_delete` | Failed. The aws log had no `*.partial`. |

### 403 body re-record

One GET, after a one-second pause, `User-Agent: sportslab-injury-pdf/1.0`, to `Injury-Report_2024-11-14_10_00AM.pdf`. Status `403`, `Content-Type: application/xml`, 263 bytes. sha256 `2962a18de1e93e26965ad116e06ebb8715350c5a14cd7372c3fe5a57055351f5`. That does **not** match the earlier meta hash `fc52b223153d5749e72499e1d0586eba230824d5bb3a757b8b54341212011e9d`. The XML embeds a `RequestId` and a `HostId`, so a second response for the same URL is not the same bytes. The saved file is this response. `missing.meta.json` now uses this hash, and the fixture test checks the file against that hash. No second request.

`synthetic_body.bin` is the replay body for the recorded `200` headers. It is not the official PDF. `block_page` and `text_plain` are marked `"synthetic": true` because the two recorded responses were a PDF and an XML 403. See `backend/tests/fixtures/nba_injury_cdn/README.md`.

### What the fixes do

- `_parse_last_modified` returns None on `ValueError` or `TypeError`. The raw header is stored, `last_modified_utc` is null, and the next URL is fetched. `main` no longer sees that `ValueError`, so it does not return 2 for a bad date.
- A first-seen 403 whose content type or body is HTML pauses and writes nothing. The recorded XML 403 is still missing, one request, no pause.
- `backfill --dry-run` still opens Postgres, because the tip times are the URLs. The docstring and the `--help` text say that. `current --dry-run` opens neither Postgres nor the CDN.
- `scripts/sync_raw_to_s3.sh` excludes `*.partial` on every prefix, including the original three.

### Mutation checks after the fix

- Restored the bare `parsedate_to_datetime` call. `test_malformed_last_modified_is_stored_and_the_next_url_is_fetched` failed again with `ValueError: Invalid date value or format "not-a-date"`. Restored the `try`. The test passed.
- Recorded a first-seen 403 without the HTML check. `test_first_seen_html_403_pauses` failed: `paused` was false. Restored `not _is_html`. The test passed.

## Follow-ups

- [ ] Parse the PDFs (out of scope here).
- [ ] Migration 006, player-id matching, and monitoring (SPO-150 to SPO-152).
- [ ] No backfill before 2021-22, and no dense scan of every 15-minute slot.
- [ ] Eason runs `terraform plan` in `infra/aws` and confirms 0 to destroy before any apply.

## Progress notes (for the docs PR)

- SPO-149: fetch official NBA injury-report PDFs into a private cache and a private S3 prefix. One request per second, an XML 403 recorded as missing, an HTML 403 pauses, game-day refresh every 15 minutes and off by default. No public route. CI rejects a tracked PDF. The runtime IAM user cannot delete the prefix. A bad Last-Modified date is stored as null and the run continues.

---

**Ticket**: SPO-149
**Branch**: `feature/SPO-149-fetch-injury-report-pdfs`
**Task summary**: `docs/task-summaries/SPO-149-fetch-injury-report-pdfs.md`

> Owner: review, then squash-merge into `dev`. Only the owner merges. Run `terraform plan` in `infra/aws` and confirm 0 to destroy before apply.
