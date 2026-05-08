# Decision — Phase 0: research-first dispatch + backend-compute for combos / DD

**Date:** 2026-05-02
**Author:** CTO ([SPO-11](/SPO/issues/SPO-11))
**Epic:** event-page-stat-expansion (parent [SPO-10](/SPO/issues/SPO-10))
**Status:** proposed (awaiting owner confirmation via `request_confirmation` on [SPO-11 plan](/SPO/issues/SPO-11#document-plan))

---

## Context

Eason 要求在 `/event/[eventId]` 加 9 個球員 prop stat type。實作前要先處理三個非顯而易見的選擇：

1. 先研究 The Odds API 還是直接寫 code？
2. Combo (R+A、P+R、P+A) 與 DD 算在 backend 還是 frontend？
3. 若 The Odds API 不支援某些 market (FGA、3PA、DD)，UI 怎麼處理？

每個選擇都影響後面 Scout / Forge / Sentinel / Lens 的拆工方式。

---

## Decision

### 1. Research-first：Phase 0 先派 Scout 用 curl 驗證所有 9 個 market key

**選**: Scout 必須在 Forge 動 backend code 之前，產出一份 `docs/research/event-page-stat-expansion/research_odds_api_markets.md`，每個 stat 都附 curl + response evidence。

**理由**:
- `CLAUDE.md § External API Wrappers` 明文規定 (rule #1 + #3): API 假設**必須**有 curl 證據；先 hardcode 市場 key 然後等線上炸是 Sports Lab 最常見的 LLM 失誤模式。
- 9 個 stat 中，最少有 3 個 (FGA、3PA、DD) 我合理懷疑 The Odds API 根本沒對外開放 — 直接 hardcode 進 `SUPPORTED_MARKETS` 會讓 `daily_analysis` 整支 broken。
- Scout 1 個 heartbeat 的成本，遠低於 Forge 寫完發現 422 之後 rebase + revert 的成本。

### 2. Combo (R+A、P+R、P+A) 與 DD 都在 backend 算

**選**: 沿用 `projection_provider.normalize_projection()` 已經存在的 `pra = pts + reb + ast` pattern (`backend/app/services/projection_provider.py:365-371`)，加 4 個 derived field (`r_a`, `p_r`, `p_a`, `dd`)。`csv_player_history.get_player_stats()` 也加 9 個 metric。

**理由**:
- **資料一致性**: backend `OddsGateway` 已有 single-flight + cache (`fresh_ttl_seconds`, `stale_ttl_seconds`)；前端 fan-out 多支 fetch 容易 race + 重複燒 quota。
- **既有 pattern**: PRA 的 derive 已在 backend，新加 4 個 derived 是 same idiom 沒增加複雜度。
- **vig-free probability** (Domain Lens): combo 若由 frontend 把兩條獨立 over 線的 american odds 直接相乘，會把 vig 雙計 → 機率錯 ~6-8%。Backend 算的話可以先 vig-free 再 sum，正確得多。
- **Product agent state**: `projection: dict[str, float | None]` 形狀不變，不需要改 LangGraph state schema。

### 3. 不支援的 market → UI graceful degrade

**選**: 若 Scout 證明某 market `[not-available]` (預期 FGA、3PA、DD)，前端仍提供 selector 選項，但 odds 區塊改顯示「無 bookmaker 線，僅供參考歷史機率 + projection」。

**理由**:
- Eason 列在需求裡的 9 個 stat **全部**都要在 selector 出現 (issue body 的明文要求)。
- 拿掉選項違反需求；硬加 fake odds 違反 anti-hallucination policy。
- "歷史 P(stat ≥ threshold) + SportsData projection" 對使用者**仍然有價值** — 至少能回答「這球員平均 9 次三分球嘗試，今天投影 10 次」這類問題。
- Selector 採分組 (Single / Combo / Derived) 後，無 odds 的 stat 用 visual marker 標示 (e.g. tooltip 寫「無 bookmaker 線」)，使用者體驗不會被誤導。

### 4. DD 第一期只算歷史 P(DD=1)，ML projection 留第二期

**選**: DD 是 binary (0/1)，不是連續值。第一期 backend 對 DD 只做 `P(DD = 1)` 從 CSV 算。Projection 顯示「DD projection N/A (將於下期實作)」。

**理由**:
- DD projection 需要從 5 個分量 (PTS / REB / AST / STL / BLK) 各自算 P(≥10) 然後算 P(at least 2 ≥ 10)，這是聯合機率問題，不是 simple sum。
- 寫對需要建一個 multi-variate 模型 (假設 5 個 stat 互相 correlated)，估計花 1-2 個 heartbeat — 會把 Phase 1 拖長。
- 第一期先讓 UI 通、historical probability 上線，用 4 週看 Eason 真的會不會去看 DD projection 再決定要不要做完整模型。先 ship learn iterate。

---

## Alternatives considered

### Alternative A — 直接 hardcode 9 個 market key (skip research)

被否決：違反 `CLAUDE.md` rule #1 + #3。LLM 對 The Odds API market 命名一致性極差 — 真有人在 `player_threes` vs `player_three_pointers_made` vs `player_3pt_made` 之間賭一把然後線上爆掉。

### Alternative B — Combo 在 frontend 算 (兩支 fetch + sum)

被否決：(1) vig 雙計問題 (機率錯 6-8%)；(2) 前端 fan-out 兩支 odds fetch 在 game window 重複燒 quota；(3) 與 PRA 的 backend-compute pattern 不一致，新進 contributor 會迷惑。

### Alternative C — 不支援的 market 直接從 selector 拿掉

被否決：Eason 在 issue body 列明 9 個都要顯示。把選項偷偷拿掉是 silent failure，比 graceful degrade 顯示「無 bookmaker 線」差。

### Alternative D — DD 第一期就做 ML projection (full multivariate model)

被否決：這是 1-2 個 heartbeat 的投入但預期 Eason 在第一期看不到使用價值差異 (UI 主要使用情境是 odds + 歷史機率，projection 只是 nice-to-have)。延後到第二期讓我們收到使用 telemetry 再決定要不要做。

---

## Impact

- **Phase 1 (Scout) 唯一輸出物**：研究文件 + decision log update (CTO 補上 `[direct-supported] / [derive-needed] / [not-available]` 表)
- **Phase 2 (Forge backend)** 預估 2-3 heartbeat — 範圍是 6 個 single source of truth (`SUPPORTED_MARKETS`、`SNAPSHOT_MARKETS`、`odds_history` allow-list、`schemas.py` enum、`csv_player_history` metric 清單、`normalize_projection` derived) + tests
- **Phase 3 (Forge frontend)** 預估 2 heartbeat — `MarketSelect` 重設計成分組、`PlayerHistoryStats` mapping、zod schema、可能的 query key 重排
- **Phase 4 (Sentinel)** 預估 1-2 heartbeat — 至少 1 個 `@pytest.mark.integration` (per `CLAUDE.md` rule #2)
- **Phase 5 (Lens)** 預估 1 heartbeat — 確認 explore script + integration test 都在 diff 裡 (per rule #4)

**總體**: 7-9 heartbeat 從 confirmation accept 到 SPO-10 done。

---

## Links

- Plan: [SPO-11 plan](/SPO/issues/SPO-11#document-plan)
- Parent epic: [SPO-10](/SPO/issues/SPO-10)
- Anti-hallucination policy: `CLAUDE.md § External API Wrappers` (rules #1-#4)
- Existing PRA derive pattern: `backend/app/services/projection_provider.py:365-371`
- Existing market enum: `backend/app/services/daily_analysis.py:41-46`
- Existing frontend selector: `frontend/components/MarketSelect.tsx:18-46`

---

## Addendum 1 — Scout brief 必須量測 The Odds API quota cost per market (2026-05-02, CEO routing comment)

CEO 在 [SPO-11 routing comment](/SPO/issues/SPO-11) (2026-05-02T20:13Z) 提醒：plan §7 風險表標 quota 是「高機率/高衝擊」但沒指定 Scout 該怎麼量。CEO 要求把這條變成 Scout 的硬性研究輸出。

**MUST-DO (binding for Subtask 1)**: 當 CTO 開 Scout 研究 ticket 時，ticket description **必須**包含以下測量項目：

> 對 `basketball_nba` 任一 live event_id，分別執行以下兩種 curl，並從 response header 紀錄 `x-requests-used`、`x-requests-remaining`：
>
> 1. **Single-market call**: `?markets=player_threes`
> 2. **Multi-market call**: `?markets=player_points,player_rebounds,player_assists,player_threes,player_steals` (5 markets in one URL)
>
> 比較兩次的 `x-requests-used` 差值，回答：
> - 一次 multi-market call 計 1 unit 還是 N units (N = markets 數量)？
> - 若是 N units，加 9 markets 等於月配額燒 ~225%-300% (assuming current 4-market baseline)，必須回 plan v2 重新 scope。
> - 若是 1 unit，原 plan v1 範圍可全部上線。

### 對 Phase 1 範圍的條件邏輯

Scout 量測結果直接決定下一步：
- **per-call billing (1 unit / call)** → plan v1 不變，9 個新 market 全部進 Phase 1
- **per-market billing (N units / call)** → CTO 出 plan v2，建議 Phase 1 限縮到 6 個 high-confidence markets (3PM、STL、FTM、R+A、P+R、P+A)，把 FGA / 3PA / DD 留給 Phase 2 (因為這 3 個本來信心就最低)
- **per-market billing 但 grouped pricing** (e.g. "first market 1 unit, additional markets 0.2 unit each") → CTO 用 Scout 數字現算 Phase 1 cap，可能介於 6-9 之間

### 為什麼要綁進 decision log 而不是只寫 comment

Paperclip API 在 SPO-11 移交 CEO 後阻止 CTO 在該 issue 直接留 comment ("Agent cannot mutate another agent's issue", `securityPrinciples: Least Privilege`)。decision log 是 repo 內的 markdown，沒有 ACL — 把這條要求 codify 在這裡，未來開 Scout ticket 時 CTO 從 decision log 讀出來貼進 ticket description，要求不會被遺失。
