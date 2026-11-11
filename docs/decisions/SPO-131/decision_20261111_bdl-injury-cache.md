# Decision — NBA injuries come from a backend BALLDONTLIE cache

- **Ticket:** SPO-131
- **Date:** 2026-11-11
- **Status:** Accepted

## Context

Product agents scrape ESPN and CBS on every injury lookup. `get_official_injury_report`, the own-team report, and `auto_teammate_impact` each call `_fetch_injury_report_for_team`, and that function has no cache.

BALLDONTLIE `/v1/player_injuries` is the replacement for NBA. The recorded page is `{data, meta{next_cursor, per_page}}`. A row has `player` (including numeric `id` and `team_id`), `return_date`, `description`, and `status`. It has no team abbreviation and no timestamp. Statuses on the recorded page are Out, Questionable, Available, Day-To-Day, Probable, and Doubtful.

The BALLDONTLIE key is shared and allows 5 requests per minute. One user question can ask for the same report more than once (own team, opponent, teammate impact). Calling the API from the request path would spend that budget and 429 every other caller on the key.

## Decision

A backend refresh fetches every page, following `meta.next_cursor` until it is null or absent, and writes `{fetched_at, entries}` to Redis key `injuries:nba:latest` with a 6 hour TTL. `fetched_at` is the UTC time we stored the pages. BDL does not send one, and the endpoint has no history, so this clock is the only freshness we have. Each entry also carries `fetched_at`, `bdl_player_id`, and `raw_status` so a later Postgres history table can store this shape without a second migration of the payload.

Product agents never call BALLDONTLIE. When `BALLDONTLIE_API_KEY` is set they only read the cache. A missing snapshot, or one older than 6 hours, is signal `caution` with reason `injury data unavailable`. An empty list is not treated as a healthy team. When the key is unset, NBA keeps the ESPN/CBS scrape so a dev environment without the key behaves as it does today. WNBA is unchanged and stays on that scrape.

`Available` is dropped. It is not an injury. `Doubtful` is stored as `Questionable` because that is the unresolved status the scorer already understands (`Questionable` and `Day-To-Day`). Eason chose that mapping. `raw_status` keeps `Doubtful`. `Out`, `Questionable`, `Day-To-Day`, and `Probable` pass through.

The team code is not on the injury row. `normalize_bdl_injuries` takes a `team_id -> abbreviation` map. The recorded standings response (`data[].team.{id, abbreviation}`) contains all 30 clubs, and those abbreviations are the NBA codes in `nba_lineup_rag/src/config.py` (`NBA_TEAMS`) and `app.services.lineup_source_support` (`TEAM_ALIASES`). The map is read from that payload. It is not typed out by hand. SPO-130d will own the production map.

If any page fails, or the cache write fails, the previous snapshot stays. A failure must not replace a good list with an empty one. Rate limiting and 429 retries live in the client. After its retries the client raises `BdlRateLimitError` or `BdlApiError` (both `BdlError`) from `bdl_client.py`. That module arrives with SPO-130a. Until then the refresh catches any exception and leaves the cache alone.

The scheduler is not registered in this change. When the client exists, the job id is `nba_injuries_refresh`, the interval is `NBA_INJURIES_REFRESH_MINUTES` (default 15), and the job runs only when `BALLDONTLIE_API_KEY` is set. The setting is declared now. The client and the job are a later commit.

## Alternatives

1. *Call `/v1/player_injuries` inside the product agent.* Rejected. The shared key is 5 requests per minute, and one question already performs several injury reads. A user request must not be the thing that spends the quota.
2. *Keep scraping ESPN/CBS for NBA whenever the cache is empty.* Rejected when the key is set. A scrape that returns nothing looks like a healthy team. The report has to say the injury data is unavailable.
3. *Add a `Doubtful` branch to the scorer.* Rejected. The scorer's unresolved bucket is already `Questionable` / `Day-To-Day`. Mapping at the normalizer keeps that vocabulary, and `raw_status` preserves the source word.
4. *Hand-write the 30 team ids.* Rejected. The standings fixture already has `id` and `abbreviation`, and those abbreviations match the codes we use.

## Tradeoff

The cache can be up to 6 hours old, and a failed refresh keeps the previous body until that window passes. There is still no per-status timestamp, so we cannot say when a player moved from Questionable to Out. Readers see one `fetched_at` for the whole page. That is the honest clock until a history table exists. The 15 minute refresh, once it is wired, is what keeps the body well inside the 6 hour window. The window is the failure case, not the steady state.
