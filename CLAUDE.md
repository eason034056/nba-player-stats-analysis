# Sports Lab — Project Context

NBA player props betting advisor. Multi-agent in-process LangGraph system + FastAPI backend + Next.js frontend that recommends or rejects player prop bets given live odds, lineups, and historical data.

Tech stack: Python 3.11+ / FastAPI / LangGraph / Pydantic v2 / Redis / PostgreSQL / pytest / Next.js 14 / TypeScript / Tailwind CSS / TanStack Query / Docker Compose.

Project path: `/Users/wuyusen/Documents/bet/`
Ticket prefix: `SPO` (Sports Lab — paperclip auto-assigned)
Paperclip company ID: `5bf7dcb7-39df-4efd-bc96-e6397e18fd9d`

## Two layers of "agents" — DO NOT confuse them

This codebase contains agents at two completely different layers. Every contributor must know which one a comment refers to:

1. **Product agents (in-process LangGraph nodes)** — live in `scripts/agents/` and `backend/`. They are LLM-orchestrated nodes that answer end-user betting queries. Names: `planner`, `historical_agent`, `projection_agent`, `market_agent`, `critic`, `synthesizer`. They run inside one Python process per user request.

2. **Paperclip dev agents** — defined in Paperclip (`~/.paperclip/.../companies/<sports-lab-id>/agents/<...>/instructions/AGENTS.md`). They are autonomous LLM agents that **build and maintain this codebase**. Names: `CTO`, `Scout`, `Forge`, `Lens`, `Sentinel`, `Sage`. They run on Paperclip wake-ups, not inside user requests.

When CLAUDE.md / ticket comments / decision logs say "agent" without qualification:
- inside `scripts/agents/`, `backend/`, or any product code path → **product agent** (LangGraph node)
- in `docs/task-summaries/`, `docs/decisions/`, `docs/progress.md`, AGENTS.md → **paperclip dev agent**

## Sub-Projects

- `backend/` — FastAPI server, REST API, scheduler, DB models, odds gateway, integration tests
- `frontend/` — Next.js 14 App Router, TanStack Query data layer, Tailwind UI, Agent Widget
- `scripts/agents/` — LangGraph multi-agent system + CLI entry (`cli.py`, `graph.py`)
- `nba_lineup_rag/` — RAG pipeline for lineup / injury context (RotoWire + RotoGrinders ingestion)
- `data/` — `nba_player_game_logs.csv` and other static historical data (download path documented in README)
- `notebooks/` — exploratory analysis, backtest notebooks
- `docker-compose.yml` — backend + Redis + Postgres dev stack

Key existing docs: `README.md`, `docs/dev-doc.md`, `docs/multi-agent-dev.md`, `docs/new-function-dev-doc.md`, `docs/player-stats-projection-api.md`, `backtest_report.md`, `sample_outputs.md`.

## Coding Conventions

### LangGraph Patterns (product agents)

- Graph nodes: functions taking `state: dict`, returning `dict` with partial state updates → see `scripts/agents/<node>.py`
- State schema: TypedDict (or Pydantic BaseModel for validated state) in `scripts/agents/state.py`. Use `total=False` for optional fields, `Annotated[list, operator.add]` for append-only lists
- Graph construction: `StateGraph` with explicit `END` for terminal nodes
- Fan-out / scoring / critic / synthesizer pattern as documented in `README.md` system architecture diagram

### FastAPI Patterns

- Routes under `backend/app/api/<domain>.py`. One router per domain (nba, odds, agents, scheduler).
- Use FastAPI `Depends` for cross-cutting concerns: DB session, current user, settings.
- Async-first for any handler that does I/O (HTTPX outbound, DB query, Redis). No blocking calls in async handlers.
- Request / response shapes: Pydantic v2 models in `backend/app/schemas/<domain>.py`. Never return raw dicts from a route.
- Lifespan events (`@asynccontextmanager async def lifespan(app)`) own startup / shutdown of pools, schedulers, cache warm-ups.

### Next.js / TypeScript Patterns (frontend)

- App Router (`app/`) only — do not add `pages/` files.
- Data fetching: TanStack Query (`useQuery` / `useMutation`) — no raw `fetch` in components except for prefetch in route loaders.
- API client lives in `frontend/lib/api/` with typed responses generated from backend schemas (or hand-written until codegen is set up).
- Public env vars must be prefixed `NEXT_PUBLIC_`. Server-only env vars stay unprefixed and are never imported in client components.
- Components: small, single-responsibility, prefer composition over conditional rendering.

### Tool Functions (product agents)

- Place in `scripts/agents/tools/` or `backend/app/services/`. Each tool is one focused function.
- Return format: `{"status": "success" | "error", "data": {...}, "sources": [...]}`. The product agent's reasoning depends on this shape.
- Wrap external API calls in `try / except` with structured logging. Docstrings must be LLM-readable (the product critic reads them at runtime).

### External API Wrappers (strict — LLMs hallucinate API shapes)

> ⚠ This is the **authoritative anti-hallucination policy** for Sports Lab. Every paperclip dev agent's `AGENTS.md` references this section in its Safety block — do not duplicate the rules elsewhere; cite them.

This codebase calls multiple live external APIs: **The Odds API**, **SportsData.io**, **RotoWire** (lineup), **RotoGrinders** (lineup / DFS), **OpenAI** (LLM). Each has rate limits, paid quotas, and a documented track record of silent schema drift. These rules exist because dev agents — Scout, Forge, Sentinel, Lens, and Claude itself — consistently assume API response shapes from training data without ever calling the real endpoint, and a sports-betting product where the odds parser silently breaks is a product that loses money.

1. **Exploration script first (Forge).** Before implementing `backend/app/services/<provider>_gateway.py` or any new external API client, create `scripts/explore_<provider>_api.py` that calls 2–3 real endpoints and pretty-prints raw responses. Commit this script alongside the client — it is the ground-truth reference for API shape and the first place to check when the API changes (e.g., when The Odds API renames a market key).

2. **Integration test required (Sentinel).** Ship at least one `@pytest.mark.integration` test that hits the live endpoint. Gate CI execution behind `RUN_INTEGRATION=1` env var (default skip; developer must run locally before PR). A pure-mock test suite for an API wrapper is NOT acceptable — the mock only proves the code runs against assumptions, not reality.

3. **Research must cite curl output (Scout).** When research recommends an external API or a new endpoint within an existing provider, the research doc must include (a) the `curl` command used and (b) the first ~500 bytes of actual response, pasted under the Sources section. Claims with no curl evidence are "unverified" and not grounds for implementation.

4. **Review demands proof of run (Lens).** Reviewing API-wrapper code requires checking that item 1 or 2 is present in the diff. "The code logic looks right" is insufficient — LLMs write plausible-looking code that calls endpoints that don't exist (or use stale market keys, or assume vig-free probability fields the API doesn't return).

### Python Standards

- Type hints required everywhere (Python 3.10+ style: `str | None`, `list[X]`)
- Docstrings: Google style. Logging: `logging.getLogger(__name__)`
- Pydantic v2 for all validated I/O (schemas, settings, agent state where applicable)
- Error handling: multi-level (tool → node → graph → API handler), graceful degradation — never let a single bad odds row crash the request

### Settings (`backend/app/settings.py`)

`Settings(BaseSettings)` MUST use the modern `model_config = SettingsConfigDict(...)` form (NOT legacy `class Config:`) and MUST set `extra="ignore"`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    odds_api_key: str
    openai_api_key: str
    sportsdata_api_key: str | None = None
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "postgresql+asyncpg://..."
    ...
```

Each Settings must explicitly declare every key it accesses via `settings.X`; `getattr(settings, "x", default)` is the only acceptable form for optional/conditional keys.

### PostgreSQL & Redis

- Migrations: alembic-managed under `backend/migrations/` (or whatever the existing scheme is — never hand-edit a deployed schema).
- Redis cache keys: namespace by domain + version, e.g. `odds:v1:<event-id>:<market>`. TTL must be explicitly chosen per key class — no implicit 0 (forever).
- Live odds cache TTL: ≤ 30 s during game windows; 5 min outside. The Sports Lab betting decision is sensitive to line freshness (see Domain lenses).
- Never serialize Pydantic v2 models with `.json()` for cache (deprecated) — use `model_dump_json()`.

### Git Workflow

- Branches: `main` (production), `dev` (integration), `feature/<ticket-id>-<desc>`
- Branch from: `git fetch origin && git checkout --no-track -b feature/SPO-<NN>-<desc> origin/dev`
- PR target: `dev`. Merge: squash. Commits: conventional (`feat:` / `fix:` / `refactor:` / `test:` / `docs:`)
- PR body: `## What` / `## Why` / `## How` / `## Testing` / `## Trade-offs`
- `dev` branch was created on 2026-05-01 from `main` and is empty of new commits — first feature merge will populate it.

### Docs Organization

- **Epic-scoped categories** go under `docs/<category>/<epic-name>/` — never loose at the category root.
  - Example: `docs/research/odds-api-v5-migration/research_market_keys.md`
- **Epic naming**: `<domain>-<phase>` in kebab-case (e.g., `odds-api-v5-migration`, `lineup-rag-revamp`, `kelly-sizing-rework`).
- **Categories (fixed list)**:
  - **Active (write here)**:
    - `decisions/<epic>/` — CTO's decision logs
    - `research/<epic>/` — Scout's research reports
    - `task-summaries/` — flat dir, file per ticket: `<TICKET>-<kebab-slug>.md` (e.g., `SPO-12-odds-cache-ttl.md`). NO epic subdir — ticket key is the index. Used by Forge / Lens / Sentinel / Sage / Scout for end-of-task summaries.
    - `progress.md` — single file at `docs/` root, maintained by CTO every wake-up.
  - **Pre-existing project docs (keep as historical reference, do not migrate)**:
    - `dev-doc.md`, `multi-agent-dev.md`, `new-function-dev-doc.md`, `player-stats-projection-api.md`, `team-logos-implementation.md` — written before the paperclip dev-agent setup; treat as background reading, do not append.
- **Cross-epic docs** stay at `docs/` root.

## Domain Lenses (sports-betting specific)

These lenses guide Scout / Forge / Lens / Sentinel judgment on sports-betting-specific code:

- **Vig-free probability**: bookmaker odds embed margin (vig). Any "probability" computed from raw odds without removing vig is wrong by 4–8%.
- **Closing-line value (CLV)**: long-term EV correlates with beating the closing line, not with single-bet outcomes. Backtests must report CLV, not just win rate.
- **Kelly criterion / fractional Kelly**: bankroll sizing must use fractional Kelly (≤ 0.25× full Kelly) — full Kelly assumes a perfectly calibrated edge, which we do not have.
- **Backtest integrity**: no future leak (do not use post-game data for pre-game decisions). Out-of-sample evaluation required for any model claim.
- **Lineup / injury validity**: a player marked questionable / OUT post-line-publish invalidates the prop entirely. Lineup data must be timestamped.
- **API rate-limit / cost-per-call**: The Odds API quota is monthly and finite. Cache + dedupe before calling. Budget per query > 1 cent is a `[Major]` cost regression.
- **Bookmaker line freshness**: the same market can move 5+ points between books in 30 s. Cache TTL ≤ 30 s during game windows. Stale-line bets are not accurate EV.
- **Bet legitimacy**: DNP, blowout (garbage time), stat-padding all distort props. Tools that compute "expected stat" must mark these explicitly.

## Agent Routing Table (paperclip dev agents)

These are the **dev** agents — they build this codebase. Do not confuse with product LangGraph nodes.

| Agent | UUID | Role |
|-------|------|------|
| CEO (delegating exec)            | `27970cac-91a1-4188-96ba-46a46fcba62e`              | Owner-facing triage; routes to CTO/specialists |
| CTO (Tech leadership)            | `b81d5848-bb55-487e-9a58-e584dfe3c93b`              | Phase planning, delegation, `docs/progress.md` |
| Scout (Researcher)               | `1a495f58-b689-46b7-9e79-9d563b31175d`    | Research, live API sample collection |
| Forge (Engineer)                 | `d5d67ab1-e5b6-4792-ab6e-563e174f81fd`    | Implementation on local feature branches |
| Lens (Reviewer)                  | `a1022b1c-16cb-4284-b0b1-94636b8f3744`     | Code review of local diffs (no PR) |
| Sentinel (QA)                    | `2df4c7c3-9ed0-4405-a813-b822e153ef62` | Pytest authoring, fixture grounding scan |
| Sage (Mentor)                    | `6faee58a-d432-4fdc-8ec9-7a4dbbe777b2`     | One mentor doc per closed parent epic |

> UUIDs are filled in after Phase B paperclip hire. The placeholder strings above must all be replaced before any agent is dispatched.

## Handoff: Creating Subtasks

All handoffs use the Paperclip API. Every subtask MUST set `assigneeAgentId` to wake the next agent:

```
POST /api/companies/{companyId}/issues
{ "title": "...", "parentId": "...", "goalId": "...", "assigneeAgentId": "<UUID>", "status": "todo", "description": "..." }
```

## Owner profile (for Sage)

Owner: Eason. Bilingual (Chinese / English), prefers Traditional Chinese for explanations unless task says otherwise. Northwestern MLDS student. First-principles learner — wants WHY and trade-offs, not step-by-step narration of what was coded.
