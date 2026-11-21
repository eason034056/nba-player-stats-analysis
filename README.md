# NBA + WNBA Player Props

This project is a web app for NBA and WNBA player props. **Both leagues are first-class** — each league has its own routes, CSV, and UI (see `docs/dev-doc.md` for the league plumbing; the agent paragraphs in that file are historical). The front-end lets a user pick a game, read vig-free prices, lineups, and historical game logs.

The LangGraph chat package (`scripts/agents/`), the lineup RAG package (`nba_lineup_rag/`), and the finetune and dataset trees were removed in SPO-142b. SPO-142a had already removed `POST /api/nba/agent/chat` and `POST /api/wnba/agent/chat`. The decision record is `docs/decisions/SPO-142/decision_20261121_remove-agent-trees.md`. `sample_outputs.md` is a saved demo from the removed CLI.

## What the app does

The browser talks to the Next.js app. That app proxies `/api/backend/...` to the FastAPI server. The server reads The Odds API, BALLDONTLIE, RotoWire, and RotoGrinders, and it scores daily picks from the cached odds, the injury snapshot, and the game-log CSVs. Redis holds the short-lived caches. PostgreSQL holds the odds snapshots and the backfill tables.

## Project Features

- Query NBA **and WNBA** games and player props
- Display vig-free probabilities and market consensus
- Read player historical game data from the NBA and WNBA CSVs
- Show live odds, lineups, and injury status
- The front-end Agent Widget is still in the Next.js app. The backend chat routes it used to call are gone.

## Tech Stack

### Backend

- `FastAPI`
- `Redis`
- `PostgreSQL`
- `HTTPX`
- `Pydantic`

### Frontend

- `Next.js 14`
- `TypeScript`
- `Tailwind CSS`
- `TanStack Query`

## 1. How to Start the Project

### Prerequisites

- `Docker` and `Docker Compose`
- `Node.js 18+`
- `Python 3.11+`
- `The Odds API` key: <https://the-odds-api.com/>

### Recommended: Start Backend with Docker, Frontend Locally

1. Copy the environment variables file

```bash
cp env.example .env
```

2. Edit the root `.env` file

At minimum, fill in the odds key:

```bash
ODDS_API_KEY=your_odds_api_key_here
```

Notes:

- `ODDS_API_KEY` is used to fetch live odds data
- NBA projections are not loaded. `has_projection` stays false until a model writes those fields.

3. Start the backend, Redis, and PostgreSQL

```bash
docker compose up --build -d
```

4. Check if backend started normally

```bash
docker compose logs -f backend
```

5. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

6. Open the project in your browser

- Frontend homepage: <http://localhost:3000>
- Backend API: <http://localhost:8000>
- Swagger docs: <http://localhost:8000/docs>

### Local Development (No Docker)

If you want to run everything locally for development, use the following method. This is more suitable for development and not the main recommended workflow for grading.

#### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.migrations upgrade
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Notes:

- `python -m app.migrations upgrade` reads `DATABASE_URL` and applies the SQL files. Run it before uvicorn. The Docker image runs the same command in its entrypoint.
- An existing local Postgres that already has the tables from `SCHEMA_SQL` needs that command once. `001_baseline.sql` applies as a no-op on that database, then `002` adds the history tables.
- If not using Docker, you should start `Redis` yourself
- If PostgreSQL is not running, the upgrade command fails. With `DATABASE_REQUIRED` left false, uvicorn still starts and persistence stays off.
- If PostgreSQL is reachable and `schema_migrations` is not at head, uvicorn does not start. `init()` logs one error naming the missing versions and `python -m app.migrations upgrade`, then raises. That includes a database whose tables came from `SCHEMA_SQL` and has no `schema_migrations` table yet.

#### Frontend

```bash
cd frontend
npm install
npm run dev
```

Local `npm run dev` does not need an API URL. The app calls `/api/backend/...` on the same origin, and the dev server proxies that to `http://localhost:8000`. To point the proxy at another origin, set `BACKEND_API_URL` in `frontend/.env.local` (leave it unset for the localhost default). See `docs/deployment/vercel.md` for the Vercel Production and Preview variables.

## 2. How to Obtain Required Data

Assignment 4 requires the README to explain "where to download the data." This project uses two types of data: static historical data and real-time external data.

### A. Historical Data CSV

The project uses one player game logs file **per league**:

- NBA target path: `data/nba_player_game_logs.csv`
- WNBA target path: `data/wnba_player_game_logs.csv`

Both CSVs ship with the repo (committed alongside `data/`). They originate from the same scraper project:

- Original source (NBA): <https://github.com/eason034056/nba-player-stats-scraper/blob/main/nba_player_game_logs.csv>
- Direct download (NBA): <https://raw.githubusercontent.com/eason034056/nba-player-stats-scraper/main/nba_player_game_logs.csv>

If either file is missing from your clone, re-download via the same scraper repo (or `git lfs` if your clone uses LFS). For the NBA CSV the canonical command is:

```bash
mkdir -p data
curl -L "https://raw.githubusercontent.com/eason034056/nba-player-stats-scraper/main/nba_player_game_logs.csv" -o data/nba_player_game_logs.csv
python scripts/hygiene_game_logs.py
```

The raw scraper file stamps a single `Season` value on every row and mixes Summer League, preseason, the regular season, and playoffs (RealGM's "All Games" view). `scripts/hygiene_game_logs.py` rewrites `Season` and adds `GameType` from the recorded ESPN schedule in `tests/fixtures/espn/`, and drops Summer League and preseason so they cannot feed props. `POST /api/trigger-csv-download` fetches the live ESPN schedule for the seasons in the file, then runs that same pass. Rows that still do not join a game are kept as `unclassified` (they do not feed props) and the download reports failure. Refresh the schedule fixture with `python scripts/explore_espn_schedule_api.py` when a new season starts.

The WNBA CSV is loaded by `backend/app/services/csv_player_history.py` via the same `_get_csv_path(league=...)` helper — searching `/app/data/wnba_player_game_logs.csv` (Docker) then `data/wnba_player_game_logs.csv` (local) — so as long as the file exists at one of those paths, the `/api/wnba/csv/*` endpoints work without further configuration. The same hygiene script covers `data/wnba_player_game_logs.csv`.

### B. Use API to Download CSV Automatically

After starting the backend, you can also call the API to have the system download the CSV to the `data/` directory:

```bash
curl -X POST http://localhost:8000/api/trigger-csv-download
```

To check the scheduler and CSV status:

```bash
curl http://localhost:8000/api/scheduler-status
```

### C. Real-Time External Data

You do not need to manually download the following data files; the system fetches them live when running:

- Real-time odds data: from `The Odds API`
- Starting lineups and injury status: from `RotoWire` and `RotoGrinders`

To fully use the project, make sure:

1. You have prepared API keys in `.env`
2. `data/nba_player_game_logs.csv` exists (or download it using the above API/command)

## 3. Interaction Methods

### Web Front-End

The frontend exposes two parallel league routes with equivalent prop-pick UI:

- `/` — NBA (default landing page)
- `/wnba` — WNBA (mirror routes: `/wnba/event/[eventId]`, `/wnba/player/[name]`, `/wnba/picks`, `/wnba/betslip`)

After going to <http://localhost:3000>, you can:

- Pick a league (NBA at `/`, WNBA at `/wnba`)
- View games and player props
- View odds, lineup, historical context, and daily picks

## 4. Testing and Utility Commands

### Backend Tests

```bash
cd backend
pytest
```

### Frontend Tests

```bash
cd frontend
npm test
```

## 5. Project Structure

```text
.
├── backend/                 # FastAPI backend
│   └── app/api/
│       ├── nba.py           # /api/* — NBA events, props/no-vig, player-history, csv/*
│       └── wnba.py          # /api/wnba/* — same surface for WNBA (events, props/no-vig, player-history, csv/*)
├── frontend/                # Next.js frontend (App Router)
│   └── app/
│       ├── (NBA routes)     # /, /event/[eventId], /picks, /betslip, /about
│       └── wnba/            # /wnba, /wnba/event/[eventId], /wnba/player/[name], /wnba/picks, /wnba/betslip
├── scripts/                 # Exploration scripts, CSV hygiene, and ops helpers
├── data/                    # nba_player_game_logs.csv, wnba_player_game_logs.csv, star_players.json
├── docker-compose.yml       # Backend, Redis, PostgreSQL launch configuration
├── env.example              # Environment variable example
└── README.md
```

