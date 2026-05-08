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
export const nbaEventSchema = z.object({
  event_id: z.string(),      // 賽事唯一 ID，用於後續查詢
  sport_key: z.string(),     // 運動類型，NBA 為 "basketball_nba"
  home_team: z.string(),     // 主場球隊名稱
  away_team: z.string(),     // 客場球隊名稱
  commence_time: z.string(), // 比賽開始時間（ISO 8601 格式）
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
export const bookmakerResultSchema = z.object({
  bookmaker: z.string(),     // 博彩公司名稱（如 "draftkings"）
  line: z.number(),          // 門檻值（如 28.5）
  over_odds: z.number(),     // Over 原始賠率（美式）
  under_odds: z.number(),    // Under 原始賠率（美式）
  p_over_imp: z.number(),    // Over 隱含機率（含水）
  p_under_imp: z.number(),   // Under 隱含機率（含水）
  vig: z.number(),           // 水錢（vig）
  p_over_fair: z.number(),   // Over 去水機率
  p_under_fair: z.number(),  // Under 去水機率
  fetched_at: z.string(),    // 資料取得時間
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
export const RECENT_GAMES_OPTIONS = [
  { value: 0, label: "All Games" },
  { value: 10, label: "Last 10 Games" },
  { value: 20, label: "Last 20 Games" },
  { value: 30, label: "Last 30 Games" },
  { value: 82, label: "Full Season (82 games)" },
] as const;


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
 * - threshold: 眾數門檻（所有博彩公司 line 的眾數）
 * - direction: "over" 或 "under"
 * - probability: 歷史機率（>= 0.65）
 * - n_games: 樣本場次數
 * - bookmakers_count: 提供此 line 的博彩公司數量
 * - all_lines: 所有博彩公司的 line 列表
 */
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
  
  // === 投影資料欄位（來自 SportsDataIO Projection API）===
  has_projection: z.boolean().optional().default(false),   // 是否有投影資料
  projected_value: z.number().nullable().optional(),       // 投影值（如 projected points = 29.3）
  projected_minutes: z.number().nullable().optional(),     // 預計上場分鐘數
  edge: z.number().nullable().optional(),                  // 投影值與盤口差距（正數 = 有利方向）
  opponent_rank: z.number().nullable().optional(),         // 對手整體防守排名（1-30）
  opponent_position_rank: z.number().nullable().optional(),// 對手對該位置防守排名
  injury_status: z.string().nullable().optional(),         // 傷病狀態（Free Trial 為 null）
  lineup_confirmed: z.boolean().nullable().optional(),     // 先發是否已確認
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


// ==================== 球員投影資料 ====================

/**
 * 單一球員投影資料 Schema
 * 
 * 對應後端 PlayerProjection 模型
 * 資料來源：SportsDataIO Projected Player Game Stats API
 */
export const playerProjectionSchema = z.object({
  player_id: z.number().nullable().optional(),
  player_name: z.string(),
  team: z.string().nullable().optional(),
  position: z.string().nullable().optional(),
  opponent: z.string().nullable().optional(),
  home_or_away: z.string().nullable().optional(),
  
  // 核心投影數據
  minutes: z.number().nullable().optional(),
  points: z.number().nullable().optional(),
  rebounds: z.number().nullable().optional(),
  assists: z.number().nullable().optional(),
  steals: z.number().nullable().optional(),
  blocked_shots: z.number().nullable().optional(),
  turnovers: z.number().nullable().optional(),
  pra: z.number().nullable().optional(),
  // SPO-16 derived combo fields emitted by `projection_provider.normalize_projection()`.
  // ⚠ 沒有 `dd` — DD 為 binary 機率，無法從邊際投影推導（decision §4 step 4）
  r_a: z.number().nullable().optional(),
  p_r: z.number().nullable().optional(),
  p_a: z.number().nullable().optional(),
  
  // 投籃數據
  field_goals_made: z.number().nullable().optional(),
  field_goals_attempted: z.number().nullable().optional(),
  three_pointers_made: z.number().nullable().optional(),
  three_pointers_attempted: z.number().nullable().optional(),
  free_throws_made: z.number().nullable().optional(),
  free_throws_attempted: z.number().nullable().optional(),
  
  // 先發/傷病（Free Trial 為 null）
  started: z.number().nullable().optional(),
  lineup_confirmed: z.boolean().nullable().optional(),
  injury_status: z.string().nullable().optional(),
  injury_body_part: z.string().nullable().optional(),
  
  // 對位難度
  opponent_rank: z.number().nullable().optional(),
  opponent_position_rank: z.number().nullable().optional(),
  
  // DFS 相關
  draftkings_salary: z.number().nullable().optional(),
  fanduel_salary: z.number().nullable().optional(),
  fantasy_points_dk: z.number().nullable().optional(),
  fantasy_points_fd: z.number().nullable().optional(),
  
  // 進階指標
  usage_rate_percentage: z.number().nullable().optional(),
  player_efficiency_rating: z.number().nullable().optional(),
});

export type PlayerProjection = z.infer<typeof playerProjectionSchema>;

/**
 * 投影資料列表回應 Schema
 * 
 * GET /api/nba/projections 的回應格式
 */
export const projectionsResponseSchema = z.object({
  date: z.string(),
  player_count: z.number(),
  fetched_at: z.string().nullable().optional(),
  projections: z.array(playerProjectionSchema),
});

export type ProjectionsResponse = z.infer<typeof projectionsResponseSchema>;

/**
 * 投影資料刷新回應 Schema
 */
export const projectionRefreshResponseSchema = z.object({
  date: z.string(),
  player_count: z.number(),
  message: z.string(),
});

export type ProjectionRefreshResponse = z.infer<typeof projectionRefreshResponseSchema>;
