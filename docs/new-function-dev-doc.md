以下是一份可直接交給 Claude 生成/改專案用的「開發文檔」（Tech Spec）。你已經指定資料位置為 **專案根目錄 `data/nba_player_game_logs.csv`**，我就以此為唯一資料來源來寫（不需要外部 API）。

---

# 開發文檔：球員歷史數據門檻機率 + Bar Chart 視覺化（CSV 版本）

## 1. 目標

在現有網站新增一個功能：使用者選擇 NBA 球員後，系統從 `data/nba_player_game_logs.csv` 讀取該球員歷史比賽數據，讓使用者設定閾值（threshold），計算並顯示：

* Over 機率：`P(metric > threshold)`
* Under 機率：`P(metric < threshold)`
* Bar chart：顯示該球員歷史數據分佈（直方圖 / histogram），並可視覺標記 threshold 位置

> 本功能計算的是「歷史經驗機率（empirical probability）」，不是模型預測。

---

## 2. 技術棧

### 前端

* Next.js（App Router）+ TypeScript
* UI：Tailwind + shadcn/ui（可選）
* 圖表：Recharts（BarChart + ReferenceLine）
* 資料抓取：TanStack Query（React Query）或原生 fetch（MVP 允許原生）

### 後端

* Next.js API Route（App Router）
* Node.js 讀取 CSV（`fs`）+ CSV parser（`csv-parse/sync`）

---

## 3. 資料來源與檔案位置

* CSV 檔案：`<project_root>/data/nba_player_game_logs.csv`
* **只允許 server-side 讀取**（不可在 client bundle 直接讀 CSV）

---

## 4. CSV 欄位需求（最低需求）

CSV 必須包含以下欄位（名稱可不同，但需在程式中對應）：

* `player_name` 或 `player_id`（至少其一）
* `game_date`（用於排序最近 N 場，可選但建議）
* `points`（PTS）
* `assists`（AST）
* `rebounds`（REB）
* （可選）`minutes`（用於排除 DNP / 0 分鐘）

> **PRA**（Points+Assists+Rebounds）由後端計算：`points + assists + rebounds`

---

## 5. 功能需求（User Stories）

### 5.1 使用者操作

1. 選擇球員（dropdown 或 autocomplete）
2. 選擇 metric：

* `points`
* `assists`
* `rebounds`
* `pra`（points+assists+rebounds）

3. 輸入 threshold（可支援小數：例如 24.5、39.5）
4. 立即顯示：

* `樣本場次 n_games`
* `Over 機率（%）`
* `Under 機率（%）`
* `Bar chart（histogram）`

### 5.2 參數（可選）

* 最近 N 場：`n=10/20/82/all`
* bins：直方圖分箱數（預設 15，範圍 5–50）

---

## 6. 產品規則（一定要固定）

### 6.1 Over / Under 定義

MVP 建議採用 props 直覺（特別適合 24.5 這種線）：

* `Over = (value > threshold)`
* `Under = (value < threshold)`

> 注意：若 threshold 是整數（例如 10），會存在 `value == threshold` 的場次不被計入 Over/Under。
> 可選方案：

* 方案 A（預設）：保持 `>` / `<`，並在 UI 顯示「等於不計入」
* 方案 B：改成 `>=` / `<=`（但會跟博彩 Over/Under 定義略不同）

**本文件採用方案 A（`>` / `<`）**。

### 6.2 樣本納入規則

* 若該場 `points/assists/rebounds` 缺失或非數字 → 排除
* 若有 `minutes` 欄位且 `minutes == 0` → 建議排除（可透過 query 參數 `exclude_dnp=true` 控制）
* 依 `game_date` 排序後取最後 N 場

---

## 7. 系統架構與資料流

**Client（Next.js page/component）**
→ 呼叫 **Next API Route** `/api/player-history?...`
→ Server 讀 CSV、過濾球員、計算 values
→ 回傳：

* `p_over`, `p_under`
* `histogram bins`
* `mean/std`
  → Client 用 Recharts 畫 bar chart + threshold line

---

## 8. API 設計（Next.js API Route）

### 8.1 Endpoint

`GET /api/player-history`

### 8.2 Query Params

* `player`（必填）：球員識別（先用 player_name）
* `metric`（選填，預設 `points`）：`points | assists | rebounds | pra`
* `threshold`（必填）：數值（float）
* `n`（選填，預設 `0`）：最近 N 場；`0` 表示全量
* `bins`（選填，預設 `15`）：直方圖分箱數，5–50
* `exclude_dnp`（選填，預設 `true`）：若 minutes 欄位存在且為 0，是否排除

### 8.3 Response（JSON）

```json
{
  "player": "Stephen Curry",
  "metric": "points",
  "threshold": 24.5,
  "n_games": 68,
  "p_over": 0.47,
  "p_under": 0.53,
  "mean": 25.1,
  "std": 5.7,
  "histogram": [
    {"binStart": 0, "binEnd": 5, "count": 1},
    {"binStart": 5, "binEnd": 10, "count": 6}
  ]
}
```

### 8.4 錯誤回應

* 400：缺參數 / threshold 非數字
* 200：player 找不到或無有效資料 → `n_games=0`，`histogram=[]`，`p_over/p_under=null`

---

## 9. 後端實作規格（App Router）

### 9.1 檔案路徑

* `app/api/player-history/route.ts`

### 9.2 依賴

* `csv-parse`（sync 版）

安裝：

```bash
npm i csv-parse
```

### 9.3 CSV 讀取與快取策略（必做）

避免每次 request 都 parse CSV：

* module-level cache（檔案內容載入一次，存在記憶體）
* 若要支援熱更新，可加 `CSV_MTIME` 檢查（非 MVP 必做）

**最低要求：**

* 第一次 request 才讀檔 parse
* 後續 request 使用記憶體中的 array

---

## 10. 前端 UI 規格（Next.js）

### 10.1 介面元件

* PlayerSelect（dropdown/autocomplete）
* MetricSelect（points/assists/rebounds/pra）
* ThresholdInput（number input）
* RecentNGamesSelect（all/10/20/82）
* StatsSummary（n_games、p_over、p_under、mean/std）
* HistogramChart（bar chart）

### 10.2 圖表（Recharts）規格

* X 軸：分箱區間（或 binStart number axis）
* Y 軸：count
* 顯示 ReferenceLine x = threshold（垂直線）
* Tooltip 顯示：區間 + count

依賴：

```bash
npm i recharts
```

---

## 11. Histogram 建模規格

### 11.1 分箱策略

* `bins` 預設 15
* `min = min(values)`, `max = max(values)`
* `binWidth = (max - min)/bins`（若 max==min，range 用極小值避免 0）
* value 落在最後邊界時強制放入最後一箱

### 11.2 輸出格式

每一箱：

* `binStart`（float）
* `binEnd`（float）
* `count`（int）

---

## 12. 測試與驗收（Acceptance Criteria）

### 12.1 後端單元測試（可選但建議）

* `american_to_prob` 不需要（此功能不含 odds）
* 測 `histogram`：

  * bins 數量正確
  * count 總和 = n_games
* 測 `p_over/p_under`：

  * 值域 0–1
  * `p_over + p_under <= 1`（因為等於 threshold 不算）

### 12.2 前端驗收

* 選球員後能顯示 n_games 與 Over/Under %
* 更改 threshold 即更新結果
* 圖表正常顯示且 tooltip 正確
* threshold line 出現在正確位置（使用 number X axis 版本）

---

## 13. 非功能性需求（NFR）

* API 回應時間：本地資料 + 快取後，<200ms（一般情況）
* 不可把 CSV 暴露給前端下載（安全/資料保護）
* 結果顯示要註明：

  * “based on historical games in CSV”
  * “not a prediction / no guarantee”

---

## 14. Claude 生成專案的指令（你可直接貼）

請 Claude 依照以下要求修改/新增功能：

1. 在 Next.js 專案新增 API route：`app/api/player-history/route.ts`

   * 從 `data/nba_player_game_logs.csv` 讀取並快取資料
   * 支援 query params：player, metric, threshold, n, bins, exclude_dnp
   * 回傳 JSON：p_over, p_under, mean, std, histogram

2. 新增前端頁面或元件：

   * PlayerSelect（先用硬編或從 CSV 抽出 unique players 也可）
   * MetricSelect / ThresholdInput / RecentNSelect
   * 呼叫 `/api/player-history` 取得結果並顯示
   * 用 Recharts BarChart 畫 histogram，並用 ReferenceLine 標示 threshold

3. 請提供：

   * 安裝依賴指令（csv-parse, recharts）
   * `.env.example`（如不需要也可省）
   * README：如何放置 CSV（已固定 `data/nba_player_game_logs.csv`）與如何啟動

---

## 15.（可選）延伸：球員清單 API

若你希望球員選擇器自動從 CSV 取清單，可增加：

* `GET /api/players`：回傳 unique player list（可加 q filter）
* 快取同樣用 module-level cache
