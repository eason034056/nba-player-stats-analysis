# NBA injury-report CDN fixtures

Tests load every CDN status, header map, and body from this directory. The test module does not type those values inline.

## Recorded

`existing.meta.json` is one real `200` for `Injury-Report_2024-11-14_10AM.pdf`. The headers are from that response. `body_sha256` and `body_length` are the official PDF. That file is not here. The repo is public, and official PDF bytes are not stored in it.

`replay_body` is `synthetic_body.bin`. Tests replay the recorded headers with those bytes. The bytes start with `%PDF-1.4` and the word `synthetic`. Their sha256 is not `body_sha256`.

`missing.meta.json` plus `missing_403.body.xml` is one real `403` for `Injury-Report_2024-11-14_10_00AM.pdf` (a minute-format name on an hour-format day). The body is the CDN's `AccessDenied` XML (`application/xml`, 263 bytes). Its sha256 is `body_sha256`. The XML includes a `RequestId` and a `HostId`, so a later request for the same URL has a different hash. An earlier capture of this URL hashed to `fc52b223153d5749e72499e1d0586eba230824d5bb3a757b8b54341212011e9d`. This file is the 2026-11-24 09:23:52 GMT response, hash `2962a18de1e93e26965ad116e06ebb8715350c5a14cd7372c3fe5a57055351f5`. Cookie and request-trace headers are not in the meta.

## Synthetic

No HTML block page and no `text/plain` error body were returned by the recorded requests, so those shapes cannot be recorded from the CDN.

| File | Meta | Why it is synthetic |
|---|---|---|
| `block_page.body.html` | `block_page.meta.json` (`200`, `text/html`) | Used when a `200` is HTML instead of a PDF |
| `block_page.body.html` | `html_403.meta.json` (`403`, `text/html`) | Used when a first-seen `403` is HTML instead of the XML missing file |
| `text_plain.body.bin` | `text_plain.meta.json` | Body and content type for a retryable `429` or `5xx`. The test passes the status |

Each of those metas has `"synthetic": true`.
