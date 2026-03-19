以下是一份「可直接丟給 Claude 生成完整專案」的開發文檔（PRD + Tech Spec）。內容以 **Python/FastAPI 後端 + Next.js 前端** 為主，並包含資料流、API 設計、資料結構、去水算法、快取策略、錯誤處理、部署與測試要求。

---

# 開發文檔：NBA 球員得分 Props「去水機率」網站

## 0. 一句話

做一個網站：使用者選擇 **NBA 比賽 + 球員**，系統自動呼叫 **Odds API** 抓該球員 **Points props（Over/Under）賠率與門檻 line**，計算 **未抽水（no-vig）公平機率** 與 **水錢（vig）**，並呈現在前端。

---

## 1) 需求與範圍

### 1.1 MVP 必做（Phase 1）

* 支援 **NBA 賽前**（pre-game）球員得分（Points）props
* 使用者流程：

  1. 選日期（預設今天）→ 顯示當天/近期 NBA 比賽清單
  2. 選一場比賽（event）
  3. 輸入球員名稱（或 autocomplete）
  4. 選 bookmaker（可選：全部 / 指定幾家）
  5. 點「計算」→ 回傳：

     * 每家 bookmaker 的：

       * line、Over/Under odds
       * vig
       * 去水後 over/under 機率
     * 市場共識（多家平均或加權）
* 後端需要：

  * 封裝外部 Odds API 呼叫
  * Redis 快取（避免頻繁打外部 API）
  * 計算模組（odds→機率→去水）

### 1.2 Phase 2（可選）

* 歷史 odds 快照（line movement）
* 提供 “closing line” 對比
* 加入「你的模型機率 vs 市場機率」做 value edge
* 使用者登入、收藏球員、通知（email/discord）

---

## 2) 產品 UI 規格（Next.js）

### 2.1 頁面

**(A) Home / Dashboard**

* 日期選擇器（預設今天）
* 比賽列表（cards 或 table）：

  * away_team @ home_team
  * start_time（本地時間）
  * “Select” 按鈕

**(B) Event Detail / Calculator**

* 顯示該場資訊（對戰、時間）
* 球員輸入：

  * MVP：文字輸入（player_name）
  * 加分：autocomplete（從當場 props outcomes 反推球員列表）
* Bookmakers 多選：

  * 預設：全部
  * 常用：draftkings、fanduel、betmgm、caesars 等（依 API 回來為準）
* 顯示結果：

  * 表格 columns：

    * bookmaker
    * line
    * over_odds / under_odds
    * implied_p_over / implied_p_under（可選顯示）
    * vig（%）
    * p_over_fair / p_under_fair（%）
  * “Consensus” 區塊：顯示平均或加權結果

**(C) About / Disclaimer**

* 註明資料來源與免責（資訊用途）

### 2.2 前端技術棧

* Next.js（App Router）+ TypeScript
* UI：Tailwind + shadcn/ui
* Data fetching：TanStack Query（React Query）
* Form：react-hook-form + zod
* 部署：Vercel

---

## 3) 系統架構（高層）

```
Browser (Next.js)
  -> Next.js Server Actions / API route (optional proxy)
  -> FastAPI Backend (recommended as main API)
       -> Redis cache
       -> External Odds API (The Odds API v4)
  <- JSON results (no-vig probabilities)
```

**建議做法**

* Next.js 只負責 UI 與呼叫後端（FastAPI）
* FastAPI 統一處理：

  * API key 安全
  * 快取
  * 外部 API error handling
  * 機率計算邏輯

---

## 4) 外部資料源與限制假設

### 4.1 Odds API（以 The Odds API v4 為例）

* 取得 NBA events（賽事清單）
* 取得單場 event 的 player props（Points）
* 注意：player props 通常需要「單場查」的 event odds endpoint（non-featured markets），因此要設計快取與節流。

> 實作上請把「外部 API 供應商」做成可替換 adapter（未來可換 Sportradar / SportsDataIO）。

---

## 5) 後端（FastAPI）API 設計

### 5.1 Base

* Base URL：`/api`
* 所有 response 皆為 JSON
* 時間格式：ISO 8601（UTC），前端顯示轉本地

### 5.2 Endpoints

#### (1) 健康檢查

`GET /api/health`

* Response:

```json
{ "ok": true, "service": "no-vig-nba", "time": "2026-01-14T18:00:00Z" }
```

#### (2) 取得 NBA 賽事列表（events）

`GET /api/nba/events?date=YYYY-MM-DD`

* 行為：

  * 從外部 API 拿該日期附近 upcoming games（或當日）
  * Redis 快取（建議 TTL 60–300 秒）
* Response:

```json
{
  "date": "2026-01-14",
  "events": [
    {
      "event_id": "evt_xxx",
      "sport_key": "basketball_nba",
      "home_team": "Los Angeles Lakers",
      "away_team": "Golden State Warriors",
      "commence_time": "2026-01-15T01:00:00Z"
    }
  ]
}
```

#### (3) 主功能：查球員 points props 並計算去水機率

`POST /api/nba/props/no-vig`

* Request:

```json
{
  "event_id": "evt_xxx",
  "player_name": "Stephen Curry",
  "market": "player_points",
  "regions": "us",
  "bookmakers": ["draftkings", "fanduel"],
  "odds_format": "american"
}
```

* 行為（核心資料流）：

  1. Redis 查快取：key = `props:{event_id}:{market}:{regions}:{bookmakers}:{odds_format}`
  2. miss → call 外部 API 取得該場 props（包含所有球員 outcomes）
  3. 在 outcomes 中找出符合 `player_name` 的條目（Over/Under）
  4. 依 bookmaker 分組，對每家：

     * 取 line + over_odds + under_odds
     * 計算 implied prob、vig、no-vig prob
  5. 計算 consensus（平均或加權）
  6. 存入 Redis（TTL 30–60 秒）

* Response:

```json
{
  "event_id": "evt_xxx",
  "player_name": "Stephen Curry",
  "market": "player_points",
  "results": [
    {
      "bookmaker": "draftkings",
      "line": 28.5,
      "over_odds": -115,
      "under_odds": -105,
      "p_over_imp": 0.5349,
      "p_under_imp": 0.5122,
      "vig": 0.0471,
      "p_over_fair": 0.5108,
      "p_under_fair": 0.4892,
      "fetched_at": "2026-01-14T18:20:11Z"
    }
  ],
  "consensus": {
    "method": "mean",
    "p_over_fair": 0.5091,
    "p_under_fair": 0.4909
  }
}
```

#### (4)（可選）球員建議 / autocomplete

`GET /api/nba/players/suggest?event_id=evt_xxx&q=cur`

* 行為：從該 event 的 props outcomes 解析出球員名單做前端 autocomplete
* Response:

```json
{ "players": ["Stephen Curry", "Seth Curry"] }
```

---

## 6) 核心數學與計算模組規格

### 6.1 American odds → implied probability

若 odds = -A：

* `p = A / (A + 100)`

若 odds = +B：

* `p = 100 / (B + 100)`

### 6.2 Vig（水錢）

* `vig = (p_over_imp + p_under_imp) - 1`

### 6.3 去水（no-vig / fair probability）

* `p_over_fair = p_over_imp / (p_over_imp + p_under_imp)`
* `p_under_fair = p_under_imp / (p_over_imp + p_under_imp)`

### 6.4 共識（consensus）

MVP：平均

* `p_over_fair_consensus = mean(p_over_fair across bookmakers)`
  Phase 2：vig 加權（vig 越低權重越高）
* `w_i = 1 / max(vig_i, eps)`
* `p = sum(w_i * p_i)/sum(w_i)`

### 6.5 邊界情況

* 缺少 over 或 under → 該 bookmaker result 標示 incomplete，不參與 consensus
* odds=0 或 null → 當作無效
* line 不一致（不同 book 可能 28.5 vs 29.5）：

  * MVP：依 bookmaker 分開顯示；consensus 只平均同一 line（或先以“最常見 line”為主）
  * Phase 2：做 line-normalization（進階）

---

## 7) 球員名稱匹配規格（很重要）

### 7.1 MVP 匹配策略

* 先做 normalize：

  * 去前後空白
  * 轉小寫
  * 移除特殊符號（`.`、`'`、`-` 可選）
* outcomes 的 `name` 也 normalize 後比對
* exact match 找不到 → fuzzy match（可用 rapidfuzz，門檻例如 90）
* 若 fuzzy match 多筆：

  * 優先選：同場 event 中出現次數較多 or team context（如果 outcomes 有 team）

### 7.2 前端降低錯配

* 建議做 `/players/suggest` 讓使用者從列表點選

---

## 8) 快取與節流

### 8.1 Redis keys

* Events：

  * `events:nba:{date}:{regions}` TTL 60–300 秒
* Props（單場）：

  * `props:nba:{event_id}:{market}:{regions}:{bookmakers}:{odds_format}` TTL 30–60 秒
* Players suggest：

  * `players:nba:{event_id}` TTL 300 秒

### 8.2 Rate limiting

* FastAPI 層限制：例如每 IP 每分鐘 60 次（可用 slowapi）
* 外部 API 呼叫加上 retry + backoff（最多 2–3 次）

---

## 9) 安全與設定

### 9.1 環境變數（後端）

* `ODDS_API_KEY=...`
* `ODDS_API_BASE_URL=https://api.the-odds-api.com`
* `REDIS_URL=redis://...`
* `CACHE_TTL_EVENTS=300`
* `CACHE_TTL_PROPS=60`
* `ALLOWED_ORIGINS=https://your-frontend.vercel.app`
* `LOG_LEVEL=info`

### 9.2 CORS

* 只允許 Next.js domain

### 9.3 不可把 API key 放前端

* Next.js 只能打你自己的 FastAPI

---

## 10) 專案結構（建議）

### 10.1 後端（FastAPI）

```
backend/
  app/
    main.py
    api/
      health.py
      nba.py
    services/
      odds_provider.py      # adapter interface
      odds_theoddsapi.py    # The Odds API implementation
      cache.py              # redis
      prob.py               # math
      normalize.py          # name normalization + matching
    models/
      schemas.py            # pydantic
    settings.py
  tests/
    test_prob.py
    test_matching.py
  Dockerfile
  pyproject.toml / requirements.txt
```

### 10.2 前端（Next.js）

```
frontend/
  app/
    page.tsx                # home: date + events list
    event/[eventId]/page.tsx # calculator + results
    api/ (optional)         # if you want Next proxy; not required
  components/
    EventList.tsx
    PlayerInput.tsx
    BookmakerSelect.tsx
    ResultsTable.tsx
  lib/
    api.ts                  # fetcher
    schemas.ts              # zod validators
  tailwind.config.ts
  next.config.js
```

---

## 11) Next.js ↔ FastAPI 介面契約

### 11.1 前端呼叫策略

* 用 React Query：

  * `useQuery(['events', date], fetchEvents)`
  * `useMutation(noVigRequest, postNoVig)`

### 11.2 UX 細節

* loading skeleton
* 若查不到球員：

  * 顯示「此球員在該場找不到 points props」＋ 建議用 suggest 列表
* 若某些 bookmaker 沒有該球員：

  * Results table 顯示 “N/A”，consensus 只用有效資料

---

## 12) 測試與驗收

### 12.1 單元測試（後端）

* `american_to_prob` 正負 odds 測試
* `devig` 計算正確性（over+under fair = 1）
* `vig` 計算正確性
* matching：

  * normalize 後 exact match
  * fuzzy match 門檻

### 12.2 端到端驗收（最小）

* 打 `/api/nba/events?date=...` 能拿到 events（或空但格式正確）
* 選一場 event，輸入球員，POST `/api/nba/props/no-vig` 回傳：

  * results 非空或合理的 not-found 訊息
  * `p_over_fair + p_under_fair == 1`（允許浮點誤差）
  * `vig >= 0`

---

## 13) 部署方案

### 13.1 本地開發（docker-compose）

* services：

  * backend (FastAPI)
  * redis
  * frontend (Next dev)（可選）

### 13.2 線上

* frontend：Vercel
* backend：Render/Fly.io/Railway（Docker）
* redis：Upstash/Render Redis

---

## 14) 免責聲明（前端必放）

* 本站為資訊與數據分析用途，不構成投注建議
* 資料可能延遲或缺漏，以外部供應商為準



