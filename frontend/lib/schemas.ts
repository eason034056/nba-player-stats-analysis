/**
 * schemas.ts - Zod 驗證模式
 * 
 * Zod 是一個 TypeScript-first 的資料驗證套件
 * 用於：
 * 1. 驗證 API 回應資料格式
 * 2. 驗證表單輸入
 * 3. 自動推導 TypeScript 類型
 * 
 * z.object(): 定義物件結構
 * z.string(): 字串類型
 * z.number(): 數字類型
 * z.array(): 陣列類型
 * z.optional(): 可選欄位
 * z.infer<typeof schema>: 從 schema 推導 TypeScript 類型
 */

import { z } from "zod";

// ==================== 健康檢查 ====================

/**
 * 健康檢查回應 Schema
 * 
 * 對應後端 HealthResponse
 */
export const healthResponseSchema = z.object({
  ok: z.boolean(),           // 服務是否正常
  service: z.string(),       // 服務名稱
  time: z.string(),          // 伺服器時間（ISO 8601 字串）
});

// 從 schema 推導的 TypeScript 類型
export type HealthResponse = z.infer<typeof healthResponseSchema>;


// ==================== NBA 賽事 ====================

/**
 * 單場 NBA 賽事 Schema
 * 
 * 每場比賽的基本資訊
 */
/**
 * Per-team lineup confirmation. `confirmed` or `projected`.
 * Null when that club has no lineup for the date. WNBA leaves the object null.
 */
export const eventLineupStatusSchema = z.object({
  home: z.enum(["confirmed", "projected"]).nullable().optional(),
  away: z.enum(["confirmed", "projected"]).nullable().optional(),
});

export type EventLineupStatus = z.infer<typeof eventLineupStatusSchema>;

/**
 * Best stored daily pick for one event, joined by the events route.
 * `market` is an Odds API key (`player_points`), not the CSV metric (`points`).
 * A broken object becomes null so one bad row does not drop the slate.
 */
export const topReadSchema = z.object({
  player: z.string().min(1),
  market: z.string().min(1),
  side: z.enum(["over", "under"]),
  line: z.number().finite(),
  probability: z.number().finite().min(0).max(1),
});

export type TopRead = z.infer<typeof topReadSchema>;

export const nbaEventSchema = z.object({
  event_id: z.string(),      // 賽事唯一 ID，用於後續查詢
  sport_key: z.string(),     // 運動類型，NBA 為 "basketball_nba"
  home_team: z.string(),     // 主場球隊名稱
  away_team: z.string(),     // 客場球隊名稱
  commence_time: z.string(), // 比賽開始時間（UTC ISO 8601）
  // Same tip in America/New_York, with the offset. Absent on older payloads and on WNBA.
  commence_time_et: z.string().nullable().optional(),
  // Label for commence_time_et. "ET" on NBA events.
  display_tz: z.string().nullable().optional(),
  lineup_status: eventLineupStatusSchema.nullable().optional().catch(null),
  top_read: topReadSchema.nullable().optional().catch(null),
});

export type NBAEvent = z.infer<typeof nbaEventSchema>;

/**
 * 賽事列表回應 Schema
 * 
 * GET /api/nba/events 的回應格式
 */
export const eventsResponseSchema = z.object({
  date: z.string(),                            // 查詢日期
  events: z.array(nbaEventSchema),             // 賽事陣列
});

export type EventsResponse = z.infer<typeof eventsResponseSchema>;


// ==================== Props 計算 ====================

/**
 * 去水機率計算請求 Schema
 * 
 * POST /api/nba/props/no-vig 的請求格式
 */
export const noVigRequestSchema = z.object({
  event_id: z.string().min(1, "賽事 ID 為必填"),
  player_name: z.string().min(1, "球員名稱為必填"),
  market: z.string().default("player_points"),
  regions: z.string().default("us"),
  bookmakers: z.array(z.string()).optional().nullable(),
  odds_format: z.string().default("american"),
});

export type NoVigRequest = z.infer<typeof noVigRequestSchema>;

/**
 * 單一博彩公司結果 Schema
 * 
 * 每家博彩公司的賠率和計算結果
 */
export const marketKindSchema = z.enum(["binary", "over_under"]);

export const bookmakerResultSchema = z.object({
  bookmaker: z.string(),     // 博彩公司名稱（如 "draftkings"）
  line: z.number(),          // 門檻值（如 28.5）。DD 的 0.5 是佔位，見 line_is_synthetic。
  // 價格與隱含機率在單邊報價上可以是 null。SPO-104 之前單邊 DD 會把
  // Yes 價抄進 under_odds；之後 under_odds / p_under_imp 改為 null。
  // 兩邊都要能通過，畫面才不會在後端合併前後壞掉。
  over_odds: z.number().nullable().optional(),
  under_odds: z.number().nullable().optional(),
  p_over_imp: z.number().nullable().optional(),
  p_under_imp: z.number().nullable().optional(),
  vig: z.number(),           // 水錢（vig）
  p_over_fair: z.number(),   // Over 去水機率（單邊時仍是模型補數的另一側）
  p_under_fair: z.number(),  // Under 去水機率。單邊 DD 仍有值，但是 4.5% prior 的補數。
  fetched_at: z.string().nullable().optional(),
  // SPO-26 二元市場（player_double_double）的顯式 Yes/No 欄位。
  // Over/Under 市場維持缺席或 null。DD tile 只讀這些名字，
  // 不把 over_odds / p_over_fair 當成 Yes 的替身。
  yes_price: z.number().nullable().optional(),
  no_price: z.number().nullable().optional(),
  p_yes_imp: z.number().nullable().optional(),
  p_no_imp: z.number().nullable().optional(),
  yes_fair_prob: z.number().nullable().optional(),
  no_fair_prob: z.number().nullable().optional(),
  // SPO-104（PR #37）。這些欄位在每一列上，不在回應外層。
  // 仍是 optional + nullable，合併前的 dev payload 才過得了。
  // 缺席時前端改用 market === player_double_double，或 null 的 No 價。
  line_is_synthetic: z.boolean().nullable().optional(),
  market_kind: marketKindSchema.nullable().optional(),
  uses_prior: z.boolean().nullable().optional(),
});

export type BookmakerResult = z.infer<typeof bookmakerResultSchema>;

/**
 * 市場共識 Schema
 * 
 * 多家博彩公司的平均機率
 */
export const consensusSchema = z.object({
  method: z.string(),        // 計算方法（"mean" 或 "weighted"）
  p_over_fair: z.number(),   // 共識 Over 機率
  p_under_fair: z.number(),  // 共識 Under 機率
  // 二元市場共識。Over/Under 回應裡這兩個欄位是 null 或缺席。
  p_yes_fair: z.number().nullable().optional(),
  p_no_fair: z.number().nullable().optional(),
  // 跟 p_yes_fair 放在同一個共識物件。任一家書用了 prior 即為 true。
  // 沒有共識時整個物件缺席或是 null，這兩個鍵不會出現在外層。
  consensus_uses_prior: z.boolean().nullable().optional(),
  consensus_prior_book_count: z.number().int().nullable().optional(),
});

export type Consensus = z.infer<typeof consensusSchema>;

/**
 * 去水機率計算回應 Schema
 * 
 * POST /api/nba/props/no-vig 的回應格式
 */
export const noVigResponseSchema = z.object({
  event_id: z.string(),
  player_name: z.string(),
  market: z.string(),
  results: z.array(bookmakerResultSchema),
  consensus: consensusSchema.nullable().optional(),
  message: z.string().nullable().optional(),
  // 快照年齡必須留在 parse 結果裡。Zod 預設會丟掉 schema 沒列出的鍵，
  // 所以這四個鍵要寫在這裡，畫面才讀得到賠率有多舊。
  // NBA 與 WNBA 的 /props/no-vig 共用這個 schema。
  fetched_at: z.string().nullable().optional(),
  data_age_seconds: z.number().int().nullable().optional(),
  cache_state: z.string().nullable().optional(),
  source: z.string().nullable().optional(),
});

export type NoVigResponse = z.infer<typeof noVigResponseSchema>;


// ==================== 球員建議 ====================

/**
 * 球員建議回應 Schema
 * 
 * GET /api/nba/players/suggest 的回應格式
 */
export const playerSuggestResponseSchema = z.object({
  players: z.array(z.string()),  // 球員名稱列表
});

export type PlayerSuggestResponse = z.infer<typeof playerSuggestResponseSchema>;


// ==================== 表單驗證 ====================

/**
 * 計算表單 Schema
 * 
 * 用於驗證使用者輸入的表單資料
 */
export const calculatorFormSchema = z.object({
  player_name: z
    .string()
    .min(2, "球員名稱至少需要 2 個字元")
    .max(100, "球員名稱過長"),
  bookmakers: z
    .array(z.string())
    .optional()
    .default([]),
});

export type CalculatorFormData = z.infer<typeof calculatorFormSchema>;


// ==================== 博彩公司列表 ====================

/**
 * 支援的博彩公司（US Region）
 * 
 * 這些是 The Odds API 在美國地區支援的博彩公司
 * key: API 使用的識別碼（必須與 The Odds API 的 bookmaker key 一致）
 * name: 顯示名稱
 * 
 * 資料來源：The Odds API v4
 * 文檔：https://the-odds-api.com/liveapi/guides/v4/
 */
export const BOOKMAKERS = [
  // === 主流平台（市佔率高） ===
  { key: "draftkings", name: "DraftKings" },
  { key: "fanduel", name: "FanDuel" },
  { key: "betmgm", name: "BetMGM" },
  { key: "caesars", name: "Caesars" },
  { key: "espnbet", name: "ESPN Bet" },
  
  // === 知名線上博彩 ===
  { key: "bet365", name: "Bet365" },
  { key: "pointsbetus", name: "PointsBet" },
  { key: "betrivers", name: "BetRivers" },
  { key: "unibet_us", name: "Unibet" },
  { key: "williamhill_us", name: "William Hill" },
  
  // === 賭場/區域型 ===
  { key: "hardrockbet", name: "Hard Rock Bet" },
  { key: "borgata", name: "Borgata" },
  { key: "bally_bet", name: "Bally Bet" },
  { key: "sisportsbook", name: "SI Sportsbook" },
  { key: "wynnbet", name: "WynnBet" },
  
  // === 其他美國運彩平台 ===
  { key: "betfred", name: "Betfred" },
  { key: "betway", name: "Betway" },
  { key: "circasports", name: "Circa Sports" },
  { key: "fliff", name: "Fliff" },
  { key: "livescorebet_us", name: "LiveScore Bet" },
  { key: "lowvig", name: "LowVig.ag" },
  { key: "mybookieag", name: "MyBookie" },
  { key: "bovada", name: "Bovada" },
  { key: "betonlineag", name: "BetOnline.ag" },
  { key: "superbook", name: "SuperBook" },
  { key: "twinspires", name: "TwinSpires" },
  { key: "betparx", name: "BetPARX" },
  { key: "foxbet", name: "FOX Bet" },
  { key: "sugarhouse", name: "SugarHouse" },
  { key: "windcreek", name: "Wind Creek" },
] as const;

// 博彩公司 key 的類型
export type BookmakerKey = (typeof BOOKMAKERS)[number]["key"];


// ==================== CSV 球員歷史數據 ====================

/**
 * CSV 球員列表回應 Schema
 * 
 * GET /api/nba/csv/players 的回應格式
 * 從 CSV 檔案讀取的所有球員名單
 */
export const csvPlayersResponseSchema = z.object({
  players: z.array(z.string()),   // 球員名稱列表
  total: z.number(),              // 球員總數
});

export type CSVPlayersResponse = z.infer<typeof csvPlayersResponseSchema>;

/**
 * 直方圖單一區間 Schema
 * 
 * 用於視覺化球員歷史數據分佈
 * - binStart: 區間起始值
 * - binEnd: 區間結束值
 * - count: 該區間內的資料點數量
 */
export const histogramBinSchema = z.object({
  binStart: z.number(),   // 區間起始
  binEnd: z.number(),     // 區間結束
  count: z.number(),      // 數量
});

export type HistogramBin = z.infer<typeof histogramBinSchema>;

/**
 * 單場比賽記錄 Schema
 * 
 * 用於時間序列圖表，顯示每場比賽的詳細資料
 */
export const gameLogSchema = z.object({
  date: z.string(),         // 比賽日期（MM/DD 格式）
  date_full: z.string(),    // 完整日期（YYYY-MM-DD 格式）
  opponent: z.string(),     // 對手球隊
  value: z.number(),        // 該指標的數值
  is_over: z.boolean(),     // 是否超過閾值
  team: z.string().optional().default(""),  // 球員所屬球隊
  minutes: z.number().optional().default(0),  // 上場時間（分鐘）
  is_starter: z.boolean().optional().default(false),  // 是否先發
  game_type: z.string().optional(),  // regular_season / playoffs / play_in
  season: z.string().optional(),  // 賽季標籤，例如 2025-2026
});

export type GameLog = z.infer<typeof gameLogSchema>;

/**
 * 球員歷史數據統計回應 Schema
 * 
 * GET /api/nba/player-history 的回應格式
 * 計算球員在指定指標上的歷史經驗機率
 */
export const playerHistoryResponseSchema = z.object({
  player: z.string(),                              // 球員名稱
  metric: z.string(),                              // 統計指標（points/assists/rebounds/pra）
  threshold: z.number(),                           // 用戶設定的閾值
  n_games: z.number(),                             // 樣本場次數
  p_over: z.number().nullable().optional(),        // Over 機率（value > threshold）
  p_under: z.number().nullable().optional(),       // Under 機率（value < threshold）
  equal_count: z.number().optional().default(0),   // 等於閾值的場次數
  mean: z.number().nullable().optional(),          // 平均值
  std: z.number().nullable().optional(),           // 標準差
  season_mean: z.number().nullable().optional().catch(null),
  histogram: z.array(histogramBinSchema),          // 直方圖資料（保留兼容性）
  game_logs: z.array(gameLogSchema).optional().default([]),  // 每場比賽詳細資料
  opponents: z.array(z.string()).optional().default([]),      // 對手列表
  teammates: z.array(z.string()).optional().default([]),      // 隊友列表（星級隊友選擇器）
  opponent_filter: z.string().nullable().optional(),          // 當前篩選的對手
  teammate_filter: z.array(z.string()).nullable().optional(), // 當前篩選的星級隊友
  teammate_played: z.boolean().nullable().optional(),         // 星級隊友出賽篩選
  message: z.string().nullable().optional(),       // 額外訊息
});

export type PlayerHistoryResponse = z.infer<typeof playerHistoryResponseSchema>;

/**
 * Double-Double 歷史命中率
 *
 * GET /api/nba/player-dd-history 與 GET /api/wnba/player-dd-history
 * 對應後端 PlayerDDHistoryResponse（backend/app/models/schemas.py）。
 *
 * DD 是二元結果，沒有 threshold、沒有 p_over / p_under。
 * prob_dd 在樣本為空（n_games == 0）時是 null，呼叫端不得自己補 0。
 */
export const playerDDHistoryResponseSchema = z.object({
  player: z.string(),
  season: z.string().nullable().optional(),
  n_games: z.number(),
  dd_games: z.number(),
  prob_dd: z.number().nullable().optional(),
  message: z.string().nullable().optional(),
});

export type PlayerDDHistoryResponse = z.infer<typeof playerDDHistoryResponseSchema>;

/**
 * GET /player-dd-history 的查詢參數。
 * season 省略表示後端使用全部賽季。不要傳 threshold。
 */
export interface PlayerDDHistoryRequest {
  player: string;
  season?: string;
}

/**
 * 球員歷史數據查詢請求參數
 * 
 * 用於 GET /api/nba/player-history 的查詢參數
 */
export interface PlayerHistoryRequest {
  player: string;              // 球員名稱
  metric: string;              // 統計指標
  threshold: number;           // 閾值
  n?: number;                  // 最近 N 場（0 表示全部）
  bins?: number;               // 直方圖分箱數
  exclude_dnp?: boolean;       // 是否排除 DNP
  opponent?: string;           // 對手篩選（可選）
  is_starter?: boolean;        // 先發狀態篩選（True=僅先發、False=僅替補、undefined=全部）
  teammate_filter?: string[];  // 星級隊友名稱列表（可多選）
  teammate_played?: boolean;   // true=隊友皆有上場, false=隊友皆未上場
  home_team?: string;          // 本場主隊。和 away_team 一起用時，隊友只留本場球隊
  away_team?: string;          // 本場客隊
  as_of?: string;              // 開賽時間，用來選這天的紀錄球隊
}

/**
 * 歷史數據統計指標選項
 *
 * 用於前端下拉選單。SPO-20 把 4 個 metrics 擴充成 12 個，對應 SPO-16
 * 後端在 `csv_player_history.CONTINUOUS_METRIC_EXTRACTORS` 加入的新欄位。
 *
 * - 11 個 continuous metrics（points/rebounds/assists/pra/threes_made/
 *   steals/ftm/fgm/ra/pr/pa）走 Over/Under 流程
 * - 1 個 binary metric（dd）走 DD-only Yes/No 流程，前端必須以
 *   `marketKey === "player_double_double"` 分支處理（無 O/U threshold）
 *
 * ⚠ FGM 為「投籃命中」工作假設（working hypothesis），如後端 integration
 * test 顯示 The Odds API 實際回傳 FGA-attempted，需後端調整、前端不變。
 */
export const HISTORY_METRICS = [
  { key: "points", name: "Points (PTS)", description: "Points scored" },
  { key: "rebounds", name: "Rebounds (REB)", description: "Total rebounds" },
  { key: "assists", name: "Assists (AST)", description: "Assists" },
  { key: "pra", name: "PRA", description: "Points + Rebounds + Assists" },
  { key: "ra", name: "R+A", description: "Rebounds + Assists" },
  { key: "pr", name: "P+R", description: "Points + Rebounds" },
  { key: "pa", name: "P+A", description: "Points + Assists" },
  { key: "threes_made", name: "3-Pointers (3PM)", description: "Three-pointers made" },
  { key: "steals", name: "Steals (STL)", description: "Steals" },
  { key: "ftm", name: "Free Throws (FTM)", description: "Free throws made" },
  { key: "fgm", name: "Field Goals (FGM)", description: "Field goals made (working hypothesis: FGM)" },
  { key: "dd", name: "Double Double (DD)", description: "Player records double-double (≥2 of {PTS, REB, AST, STL, BLK} ≥ 10)" },
] as const;

export type HistoryMetricKey = (typeof HISTORY_METRICS)[number]["key"];

/**
 * 最近 N 場選項
 * 
 * 用於前端選擇要分析的場次範圍
 */
export type SeasonLeague = "nba" | "wnba";

/** Regular-season length. NBA plays 82, WNBA plays 44. */
export const REGULAR_SEASON_GAMES: Record<SeasonLeague, number> = {
  nba: 82,
  wnba: 44,
};

export function recentGamesOptions(league: SeasonLeague) {
  const games = REGULAR_SEASON_GAMES[league];
  return [
    { value: 0, label: "All Games" },
    { value: 10, label: "Last 10 Games" },
    { value: 20, label: "Last 20 Games" },
    { value: 30, label: "Last 30 Games" },
    { value: games, label: `Full Season (${games} games)` },
  ] as const;
}

/** NBA list. Callers that know the league should use `recentGamesOptions`. */
export const RECENT_GAMES_OPTIONS = recentGamesOptions("nba");


// ==================== 每日高機率球員 ====================

/**
 * 單一高機率球員選擇 Schema
 * 
 * 當某球員在某 metric 上的歷史機率 > 65% 時，會被加入精選名單
 * 
 * 欄位說明：
 * - player_name: 球員名稱
 * - event_id: 賽事 ID
 * - home_team / away_team: 主客場球隊
 * - commence_time: 比賽開始時間
 * - metric: 統計指標（points/assists/rebounds/pra）
 * - threshold: 眾數門檻（每家博彩公司一條主盤的眾數）
 * - direction: "over" 或 "under"
 * - probability: 歷史機率（>= 0.65）
 * - n_games: 樣本場次數
 * - bookmakers_count: 有開出這名球員這個盤口的博彩公司家數（同一家的 Over/Under 與替代盤只算一次）
 * - all_lines: 每家博彩公司的主盤，一家一條
 */
/** One signal on a stored NBA pick. `value` is display text for the pick's side. */
export const pickSignalSchema = z.object({
  key: z.string(),
  label: z.string(),
  value: z.string().nullable().optional(),
  verdict: z.enum(["supports", "neutral", "against"]).nullable().optional().catch(null),
});

export type PickSignal = z.infer<typeof pickSignalSchema>;

export const dailyPickSchema = z.object({
  player_name: z.string(),
  player_team: z.string().optional().default(""),  // 球員所屬球隊（簡短名稱）
  player_team_code: z.string().optional().default(""),
  event_id: z.string(),
  home_team: z.string(),
  away_team: z.string(),
  commence_time: z.string(),
  metric: z.string(),
  threshold: z.number(),
  direction: z.string(),
  probability: z.number(),
  n_games: z.number(),
  bookmakers_count: z.number(),
  all_lines: z.array(z.number()).optional().default([]),
  
  // Nullable. The board omits a tag when the value is null.
  has_projection: z.boolean().optional().default(false),
  projected_value: z.number().nullable().optional(),
  projected_minutes: z.number().nullable().optional(),
  edge: z.number().nullable().optional(),
  opponent_rank: z.number().nullable().optional(),         // 對手整體防守排名。方向見 backend/app/models/schemas.py 第 514–516 行：1 = 最弱
  opponent_position_rank: z.number().nullable().optional(),// 對手對該位置防守排名。同一契約：1 = 最弱
  injury_status: z.string().nullable().optional(),         // 傷病狀態（Free Trial 為 null）
  // BDL's original word. Missing on older caches. Null when injury_status is null.
  injury_status_raw: z.string().nullable().optional(),
  lineup_confirmed: z.boolean().nullable().optional(),     // 先發是否已確認
  position: z.string().nullable().optional().catch(null),
  // Display keeps Strong play, Playable, and Lean. Pass stays on the payload
  // and is blank on the card. Any other string becomes null so the pick loads.
  tier: z
    .preprocess((value) => {
      if (value == null) return null;
      if (value === "Strong play" || value === "Playable" || value === "Lean" || value === "Pass") return value;
      return null;
    }, z.string().nullable())
    .optional(),
  p_over: z.number().min(0).max(1).nullable().optional().catch(null),
  p_under: z.number().min(0).max(1).nullable().optional().catch(null),
  season_mean: z.number().nullable().optional().catch(null),
  signals: z.array(pickSignalSchema).nullable().optional().catch(null),
  combined_probability: z.number().min(0).max(1).nullable().optional().catch(null),
});

export type DailyPick = z.infer<typeof dailyPickSchema>;

/**
 * 分析統計資訊 Schema
 * 
 * 提供整體分析的摘要統計
 */
export const analysisStatsSchema = z.object({
  total_events: z.number(),              // 分析的賽事總數
  total_players: z.number(),             // 分析的球員總數
  total_props: z.number(),               // 分析的 prop 總數
  high_prob_count: z.number(),           // 高機率選擇數量
  analysis_duration_seconds: z.number(), // 分析耗時（秒）
});

export type AnalysisStats = z.infer<typeof analysisStatsSchema>;

/**
 * 每日高機率球員回應 Schema
 * 
 * GET /api/nba/daily-picks 的回應格式
 * 返回當日所有發生機率超過門檻的球員投注選擇
 */
export const dailyPicksResponseSchema = z.object({
  date: z.string(),                                    // 分析日期
  analyzed_at: z.string(),                             // 分析執行時間
  total_picks: z.number(),                             // 符合條件的選擇總數
  picks: z.array(dailyPickSchema),                     // 高機率球員列表
  stats: analysisStatsSchema.nullable().optional(),    // 分析統計
  message: z.string().nullable().optional(),           // 額外訊息
});

export type DailyPicksResponse = z.infer<typeof dailyPicksResponseSchema>;

/**
 * 每日精選查詢參數
 */
export interface DailyPicksRequest {
  date?: string;           // 查詢日期（YYYY-MM-DD）
  refresh?: boolean;       // 是否強制重新分析
  min_probability?: number; // 最低機率門檻
  min_games?: number;      // 最少樣本場次
}


// ==================== 免費先發預測共識 ====================

export const lineupSourceSnapshotSchema = z.object({
  team: z.string(),
  opponent: z.string().optional().default(""),
  home_or_away: z.string().optional().default(""),
  status: z.string(),
  starters: z.array(z.string()).optional().default([]),
  bench_candidates: z.array(z.string()).optional().default([]),
});

export const teamLineupSchema = z.object({
  date: z.string(),
  team: z.string(),
  opponent: z.string().optional().default(""),
  home_or_away: z.string().optional().default(""),
  status: z.enum(["projected", "partial", "unavailable"]),
  starters: z.array(z.string()).optional().default([]),
  bench_candidates: z.array(z.string()).optional().default([]),
  sources: z.array(z.string()).optional().default([]),
  source_disagreement: z.boolean().optional().default(false),
  confidence: z.enum(["high", "medium", "low"]),
  updated_at: z.string().nullable().optional(),
  source_snapshots: z.record(z.string(), lineupSourceSnapshotSchema).optional().default({}),
});

export type TeamLineup = z.infer<typeof teamLineupSchema>;

export const lineupsResponseSchema = z.object({
  date: z.string(),
  team_count: z.number(),
  fetched_at: z.string().nullable().optional(),
  cache_state: z.string(),
  lineups: z.array(teamLineupSchema),
});

export type LineupsResponse = z.infer<typeof lineupsResponseSchema>;

export const lineupRefreshResponseSchema = z.object({
  date: z.string(),
  team_count: z.number(),
  message: z.string(),
});

export type LineupRefreshResponse = z.infer<typeof lineupRefreshResponseSchema>;

/**
 * 指標顯示名稱對應
 * 
 * 將 API 返回的 metric key 轉換為用戶友好的顯示名稱
 */
export const METRIC_DISPLAY_NAMES: Record<string, string> = {
  points: "Points",
  rebounds: "Rebounds",
  assists: "Assists",
  pra: "PRA",
  ra: "R+A",
  pr: "P+R",
  pa: "P+A",
  threes_made: "3PM",
  steals: "Steals",
  ftm: "FTM",
  fgm: "FGM",
  dd: "DD",
};

/**
 * Direction display name mapping
 */
export const DIRECTION_DISPLAY_NAMES: Record<string, string> = {
  over: "Over",
  under: "Under",
};


const unitProbability = z.number().min(0).max(1);

export const propReadSchema = z.object({
  player: z.string(),
  market: z.string(),
  line: z.number(),
  side: z.enum(["over", "under"]).nullable().optional().catch(null),
  combined_probability: unitProbability.nullable().optional().catch(null),
  tier: z.enum(["Strong play", "Playable", "Lean"]).nullable().optional().catch(null),
  signals: z.array(pickSignalSchema).nullable().optional().catch(null),
});

export type PropRead = z.infer<typeof propReadSchema>;

export const eventReadsResponseSchema = z.object({
  event_id: z.string(),
  market: z.string().nullable().optional(),
  snapshot_at: z.string().nullable().optional(),
  source: z.literal("snapshot"),
  reads: z.array(propReadSchema),
});

export type EventReadsResponse = z.infer<typeof eventReadsResponseSchema>;

export const bulkPropBookSchema = z.object({
  bookmaker: z.string(),
  line: z.number(),
  over_odds: z.number().nullable().optional(),
  under_odds: z.number().nullable().optional(),
  yes_odds: z.number().nullable().optional(),
  no_odds: z.number().nullable().optional(),
});

export const bulkPropPlayerSchema = z.object({
  player: z.string(),
  position: z.string().nullable().optional().catch(null),
  team_code: z.string().nullable().optional().catch(null),
  line: z.number(),
  bookmakers_count: z.number(),
  books: z.array(bulkPropBookSchema).optional().default([]),
});

export type BulkPropPlayer = z.infer<typeof bulkPropPlayerSchema>;

export const bulkPropsResponseSchema = z.object({
  event_id: z.string(),
  snapshot_at: z.string().nullable().optional(),
  data_age_seconds: z.number().int().nullable().optional(),
  source: z.literal("snapshot"),
  markets: z.array(
    z.object({
      market: z.string(),
      players: z.array(bulkPropPlayerSchema),
    }),
  ),
});

export type BulkPropsResponse = z.infer<typeof bulkPropsResponseSchema>;
