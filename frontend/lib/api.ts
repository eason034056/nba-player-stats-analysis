/**
 * api.ts - API 客戶端
 * 
 * 封裝所有與後端 API 的通訊
 * 使用 fetch API 進行 HTTP 請求
 * 
 * 功能：
 * 1. 統一的錯誤處理
 * 2. 使用 Zod 驗證回應資料
 * 3. TypeScript 類型安全
 */

import {
  eventsResponseSchema,
  noVigResponseSchema,
  playerSuggestResponseSchema,
  csvPlayersResponseSchema,
  playerHistoryResponseSchema,
  dailyPicksResponseSchema,
  lineupRefreshResponseSchema,
  lineupsResponseSchema,
  playerProjectionSchema,
  projectionsResponseSchema,
  projectionRefreshResponseSchema,
  teamLineupSchema,
  type PlayerProjection,
  type EventsResponse,
  type NoVigRequest,
  type NoVigResponse,
  type PlayerSuggestResponse,
  type CSVPlayersResponse,
  type PlayerHistoryResponse,
  type PlayerHistoryRequest,
  type DailyPicksResponse,
  type DailyPicksRequest,
  type LineupRefreshResponse,
  type LineupsResponse,
  type ProjectionsResponse,
  type ProjectionRefreshResponse,
  type TeamLineup,
} from "./schemas";
import {
  agentChatResponseSchema,
  type AgentChatRequest,
  type AgentChatResponse,
} from "./agent-chat";

// API 基礎 URL
// 從環境變數讀取，預設為本地開發環境
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * API 錯誤類別
 * 
 * 用於封裝 API 呼叫時發生的錯誤
 * 包含狀態碼和訊息，方便錯誤處理
 */
export class ApiError extends Error {
  constructor(
    public status: number,        // HTTP 狀態碼
    public statusText: string,    // HTTP 狀態文字
    public detail?: string        // 詳細錯誤訊息
  ) {
    super(`API Error: ${status} ${statusText}`);
    this.name = "ApiError";
  }
}

/**
 * 通用的 fetch 包裝函數
 * 
 * 提供：
 * - 統一的錯誤處理
 * - JSON 解析
 * - TypeScript 類型支援
 * 
 * @param endpoint - API 端點（如 "/api/nba/events"）
 * @param options - fetch 選項
 * @returns Promise<T> - 解析後的 JSON 資料
 * 
 * @example
 * const data = await fetchApi<EventsResponse>("/api/nba/events?date=2026-01-14");
 */
async function fetchApi<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;
  
  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options?.headers,
      },
    });
    
    // 檢查回應狀態
    if (!response.ok) {
      // 嘗試解析錯誤訊息
      let detail: string | undefined;
      try {
        const errorData = await response.json();
        detail = errorData.detail || errorData.message;
      } catch {
        // 無法解析 JSON，使用預設訊息
      }
      
      throw new ApiError(response.status, response.statusText, detail);
    }
    
    // 解析 JSON
    const data = await response.json();
    return data as T;
    
  } catch (error) {
    // 重新拋出 ApiError
    if (error instanceof ApiError) {
      throw error;
    }
    
    // 網路錯誤或其他錯誤
    throw new ApiError(
      0,
      "Network Error",
      error instanceof Error ? error.message : "Unknown error"
    );
  }
}


// ==================== API 函數 ====================

/**
 * 取得 NBA 賽事列表
 * 
 * GET /api/nba/events
 * 
 * @param date - 日期（YYYY-MM-DD 格式），不提供則使用今天
 * @param regions - 地區代碼，預設 "us"
 * @returns Promise<EventsResponse> - 賽事列表
 * 
 * @example
 * const events = await getEvents("2026-01-14");
 * console.log(events.events.length);
 */
export async function getEvents(
  date?: string,
  regions: string = "us"
): Promise<EventsResponse> {
  // 建構查詢參數
  const params = new URLSearchParams({ regions });
  if (date) {
    params.set("date", date);
  }
  
  // 傳遞時區偏移量給後端
  // JavaScript 的 getTimezoneOffset() 返回「UTC - 本地時間」的分鐘數
  // 例如：UTC-6 返回 360，UTC+8 返回 -480
  // 我們需要轉換為「本地時間 - UTC」的分鐘數
  // 所以取負值：UTC-6 變成 -360，UTC+8 變成 480
  const tzOffset = -new Date().getTimezoneOffset();
  params.set("tz_offset", tzOffset.toString());
  
  // 發送請求
  const data = await fetchApi<EventsResponse>(`/api/nba/events?${params}`);
  
  // 使用 Zod 驗證回應格式
  // parse() 會在驗證失敗時拋出錯誤
  return eventsResponseSchema.parse(data);
}


/**
 * 計算去水機率
 * 
 * POST /api/nba/props/no-vig
 * 
 * 這是整個應用的核心功能！
 * 
 * @param request - 計算請求參數
 * @returns Promise<NoVigResponse> - 計算結果
 * 
 * @example
 * const result = await calculateNoVig({
 *   event_id: "abc123",
 *   player_name: "Stephen Curry",
 *   bookmakers: ["draftkings", "fanduel"]
 * });
 * console.log(result.consensus?.p_over_fair);
 */
export async function calculateNoVig(
  request: NoVigRequest
): Promise<NoVigResponse> {
  const data = await fetchApi<NoVigResponse>("/api/nba/props/no-vig", {
    method: "POST",
    body: JSON.stringify(request),
  });
  
  // 驗證回應
  return noVigResponseSchema.parse(data);
}


/**
 * 取得球員名稱建議
 * 
 * GET /api/nba/players/suggest
 * 
 * 用於前端 autocomplete 功能
 * 
 * @param eventId - 賽事 ID
 * @param query - 搜尋關鍵字（可選）
 * @param market - 市場類型，預設 "player_points"
 * @returns Promise<PlayerSuggestResponse> - 球員列表
 * 
 * @example
 * const suggestions = await getPlayerSuggestions("abc123", "cur");
 * // suggestions.players = ["Stephen Curry", "Seth Curry"]
 */
export async function getPlayerSuggestions(
  eventId: string,
  query?: string,
  market: string = "player_points"
): Promise<PlayerSuggestResponse> {
  // 建構查詢參數
  const params = new URLSearchParams({
    event_id: eventId,
    market,
  });
  
  if (query) {
    params.set("q", query);
  }
  
  const data = await fetchApi<PlayerSuggestResponse>(
    `/api/nba/players/suggest?${params}`
  );
  
  return playerSuggestResponseSchema.parse(data);
}


/**
 * 健康檢查
 * 
 * GET /api/health
 * 
 * 用於檢查後端服務是否正常
 * 
 * @returns Promise<boolean> - 服務是否正常
 */
export async function checkHealth(): Promise<boolean> {
  try {
    const data = await fetchApi<{ ok: boolean }>("/api/health");
    return data.ok === true;
  } catch {
    return false;
  }
}


// ==================== CSV 球員歷史數據 API ====================

/**
 * 取得 CSV 球員名單
 * 
 * GET /api/nba/csv/players
 * 
 * 從 data/nba_player_game_logs.csv 讀取所有球員名單
 * 用於前端球員選擇器的 autocomplete 功能
 * 
 * @param query - 搜尋關鍵字（可選）
 * @returns Promise<CSVPlayersResponse> - 球員列表
 * 
 * @example
 * const players = await getCSVPlayers("curry");
 * // players.players = ["Stephen Curry", "Seth Curry"]
 */
export async function getCSVPlayers(
  query?: string
): Promise<CSVPlayersResponse> {
  const params = new URLSearchParams();
  
  if (query) {
    params.set("q", query);
  }
  
  const queryString = params.toString();
  const url = queryString 
    ? `/api/nba/csv/players?${queryString}`
    : "/api/nba/csv/players";
  
  const data = await fetchApi<CSVPlayersResponse>(url);
  return csvPlayersResponseSchema.parse(data);
}


/**
 * 取得球員歷史數據統計
 * 
 * GET /api/nba/player-history
 * 
 * 計算球員在指定指標上的「經驗機率」（empirical probability）
 * 這是基於 CSV 歷史數據的統計，不是模型預測！
 * 
 * 機率定義（符合運彩 props 直覺）：
 * - Over: value > threshold（嚴格大於）
 * - Under: value < threshold（嚴格小於）
 * 
 * @param request - 查詢參數
 * @returns Promise<PlayerHistoryResponse> - 統計結果
 * 
 * @example
 * const stats = await getPlayerHistory({
 *   player: "Stephen Curry",
 *   metric: "points",
 *   threshold: 24.5,
 *   n: 20
 * });
 * console.log(`Over 機率: ${stats.p_over}`);
 */
export async function getPlayerHistory(
  request: PlayerHistoryRequest
): Promise<PlayerHistoryResponse> {
  // 建構查詢參數
  const params = new URLSearchParams({
    player: request.player,
    metric: request.metric,
    threshold: request.threshold.toString(),
  });
  
  // 可選參數
  if (request.n !== undefined) {
    params.set("n", request.n.toString());
  }
  if (request.bins !== undefined) {
    params.set("bins", request.bins.toString());
  }
  if (request.exclude_dnp !== undefined) {
    params.set("exclude_dnp", request.exclude_dnp.toString());
  }
  // 對手篩選
  if (request.opponent) {
    params.set("opponent", request.opponent);
  }
  // 先發狀態篩選
  if (request.is_starter !== undefined) {
    params.set("is_starter", request.is_starter.toString());
  }
  // 星級隊友篩選
  if (request.teammate_filter && request.teammate_filter.length > 0) {
    params.set("teammate_filter", request.teammate_filter.join(","));
  }
  if (request.teammate_played !== undefined) {
    params.set("teammate_played", request.teammate_played.toString());
  }
  
  const data = await fetchApi<PlayerHistoryResponse>(
    `/api/nba/player-history?${params}`
  );

  return playerHistoryResponseSchema.parse(data);
}


// ==================== WNBA CSV 球員歷史數據 API (SPO-32 Phase 1) ====================
// 💡 WNBA 端點為 NBA 的姊妹路由：相同 schema、相同回應格式。
// 之所以不參數化 getCSVPlayers/getPlayerHistory 加 league 參數，是因為
// Phase 2-6 還會引入 /api/wnba/events、/api/wnba/props 等更多端點，
// 而 NBA 端點已有 daily-picks/projections 等不在 WNBA 範疇的調用，
// 強行統一介面會 leak 出兩邊都沒實作的功能。並列函式比假裝對稱乾淨。

/**
 * Get WNBA player names from CSV.
 *
 * GET /api/wnba/csv/players
 */
export async function getWNBACSVPlayers(
  query?: string
): Promise<CSVPlayersResponse> {
  const params = new URLSearchParams();
  if (query) {
    params.set("q", query);
  }

  const queryString = params.toString();
  const url = queryString
    ? `/api/wnba/csv/players?${queryString}`
    : "/api/wnba/csv/players";

  const data = await fetchApi<CSVPlayersResponse>(url);
  return csvPlayersResponseSchema.parse(data);
}

/**
 * Get WNBA player historical stats.
 *
 * GET /api/wnba/player-history
 */
export async function getWNBAPlayerHistory(
  request: PlayerHistoryRequest
): Promise<PlayerHistoryResponse> {
  const params = new URLSearchParams({
    player: request.player,
    metric: request.metric,
    threshold: request.threshold.toString(),
  });

  if (request.n !== undefined) {
    params.set("n", request.n.toString());
  }
  if (request.bins !== undefined) {
    params.set("bins", request.bins.toString());
  }
  if (request.exclude_dnp !== undefined) {
    params.set("exclude_dnp", request.exclude_dnp.toString());
  }
  if (request.opponent) {
    params.set("opponent", request.opponent);
  }
  if (request.is_starter !== undefined) {
    params.set("is_starter", request.is_starter.toString());
  }
  if (request.teammate_filter && request.teammate_filter.length > 0) {
    params.set("teammate_filter", request.teammate_filter.join(","));
  }
  if (request.teammate_played !== undefined) {
    params.set("teammate_played", request.teammate_played.toString());
  }

  const data = await fetchApi<PlayerHistoryResponse>(
    `/api/wnba/player-history?${params}`
  );

  return playerHistoryResponseSchema.parse(data);
}


// ==================== 每日高機率球員 API ====================

/**
 * 取得每日高機率球員
 * 
 * GET /api/nba/daily-picks
 * 
 * 返回當日所有發生機率超過門檻（預設 65%）的球員投注選擇
 * 
 * 分析流程：
 * 1. 獲取當日所有 NBA 賽事
 * 2. 對每場賽事，獲取所有球員的 props（得分、籃板、助攻、PRA）
 * 3. 計算博彩公司 line 的眾數作為門檻
 * 4. 從歷史數據計算 over/under 機率
 * 5. 篩選機率超過門檻的結果
 * 
 * @param request - 查詢參數（可選）
 * @returns Promise<DailyPicksResponse> - 高機率球員列表
 * 
 * @example
 * const picks = await getDailyPicks();
 * console.log(`找到 ${picks.total_picks} 個高機率選擇`);
 * 
 * // 指定日期和參數
 * const picks = await getDailyPicks({
 *   date: "2026-01-24",
 *   min_probability: 0.70,
 *   refresh: true
 * });
 */
export async function getDailyPicks(
  request?: DailyPicksRequest
): Promise<DailyPicksResponse> {
  // 建構查詢參數
  const params = new URLSearchParams();
  
  if (request?.date) {
    params.set("date", request.date);
  }
  if (request?.refresh) {
    params.set("refresh", "true");
  }
  if (request?.min_probability !== undefined) {
    params.set("min_probability", request.min_probability.toString());
  }
  if (request?.min_games !== undefined) {
    params.set("min_games", request.min_games.toString());
  }
  
  // 傳遞時區偏移量
  // JavaScript 的 getTimezoneOffset() 返回「UTC - 本地時間」的分鐘數
  // 需要取負值轉換為「本地時間 - UTC」
  const tzOffset = -new Date().getTimezoneOffset();
  params.set("tz_offset", tzOffset.toString());
  
  const queryString = params.toString();
  const url = `/api/nba/daily-picks?${queryString}`;
  
  const data = await fetchApi<DailyPicksResponse>(url);
  return dailyPicksResponseSchema.parse(data);
}

/**
 * 手動觸發每日分析
 * 
 * POST /api/nba/daily-picks/trigger
 * 
 * 強制重新執行分析（忽略快取）
 * 
 * @param date - 分析日期（可選，預設今天）
 * @returns Promise<DailyPicksResponse> - 新的分析結果
 */
export async function triggerDailyAnalysis(
  date?: string
): Promise<DailyPicksResponse> {
  const params = new URLSearchParams();
  
  if (date) {
    params.set("date", date);
  }
  
  // 傳遞時區偏移量
  const tzOffset = -new Date().getTimezoneOffset();
  params.set("tz_offset", tzOffset.toString());
  
  const queryString = params.toString();
  const url = `/api/nba/daily-picks/trigger?${queryString}`;
  
  const data = await fetchApi<DailyPicksResponse>(url, {
    method: "POST",
  });
  
  return dailyPicksResponseSchema.parse(data);
}

/**
 * 與投注 agent 對話
 *
 * POST /api/nba/agent/chat
 */
export async function sendAgentChat(
  request: AgentChatRequest,
): Promise<AgentChatResponse> {
  const data = await fetchApi<AgentChatResponse>("/api/nba/agent/chat", {
    method: "POST",
    body: JSON.stringify(request),
  });

  return agentChatResponseSchema.parse(data);
}


// ==================== 免費先發預測共識 API ====================

export async function getLineups(
  date?: string,
): Promise<LineupsResponse> {
  const params = new URLSearchParams();
  if (date) {
    params.set("date", date);
  }

  const queryString = params.toString();
  const url = queryString ? `/api/nba/lineups?${queryString}` : "/api/nba/lineups";
  const data = await fetchApi<LineupsResponse>(url);
  return lineupsResponseSchema.parse(data);
}

export async function getTeamLineup(
  team: string,
  date?: string,
): Promise<TeamLineup> {
  const encodedTeam = encodeURIComponent(team);
  const params = new URLSearchParams();
  if (date) {
    params.set("date", date);
  }

  const queryString = params.toString();
  const url = queryString
    ? `/api/nba/lineups/${encodedTeam}?${queryString}`
    : `/api/nba/lineups/${encodedTeam}`;

  const data = await fetchApi<TeamLineup>(url);
  return teamLineupSchema.parse(data);
}

export async function refreshLineups(
  date?: string,
): Promise<LineupRefreshResponse> {
  const params = new URLSearchParams();
  if (date) {
    params.set("date", date);
  }

  const queryString = params.toString();
  const url = queryString
    ? `/api/nba/lineups/refresh?${queryString}`
    : "/api/nba/lineups/refresh";

  const data = await fetchApi<LineupRefreshResponse>(url, {
    method: "POST",
  });
  return lineupRefreshResponseSchema.parse(data);
}


// ==================== 球員投影資料 API ====================

/**
 * 取得球員投影資料
 * 
 * GET /api/nba/projections
 * 
 * 取得指定日期所有球員的 SportsDataIO 投影數據。
 * 使用混合取得策略：Redis 快取 → 背景刷新 → 同步呼叫 API。
 * 
 * 投影資料包含：
 * - 預計得分、籃板、助攻等核心數據
 * - 預計上場分鐘數
 * - 對手防守排名
 * - DFS 薪資和 Fantasy 分數
 * 
 * @param date - 查詢日期（YYYY-MM-DD），不提供則使用今天
 * @returns Promise<ProjectionsResponse> - 投影資料列表
 * 
 * @example
 * const projections = await getProjections("2026-02-08");
 * console.log(`取得 ${projections.player_count} 筆投影資料`);
 */
export async function getProjections(
  date?: string
): Promise<ProjectionsResponse> {
  const params = new URLSearchParams();
  
  if (date) {
    params.set("date", date);
  }
  
  const queryString = params.toString();
  const url = queryString
    ? `/api/nba/projections?${queryString}`
    : "/api/nba/projections";
  
  const data = await fetchApi<ProjectionsResponse>(url);
  return projectionsResponseSchema.parse(data);
}

/**
 * 手動刷新投影資料
 * 
 * POST /api/nba/projections/refresh
 * 
 * 強制重新呼叫 SportsDataIO API，更新 Redis 快取和 PostgreSQL。
 * 通常在以下情況使用：
 * - 需要最新的陣容確認資訊
 * - 排程器之外的手動更新
 * 
 * @param date - 刷新日期（YYYY-MM-DD），不提供則使用今天
 * @returns Promise<ProjectionRefreshResponse> - 刷新結果
 * 
 * @example
 * const result = await refreshProjections("2026-02-08");
 * console.log(result.message); // "成功刷新 250 筆投影資料"
 */
/**
 * 取得單一球員投影資料
 * 
 * GET /api/nba/projections/{player_name}
 * 
 * 取得指定球員在指定日期的投影資料。
 * 用於球員詳細頁面（Event Detail Page）顯示投影數據。
 * 
 * 後端使用 projection_service.get_player_projection() 取得：
 * 先查 Redis → 若過期觸發背景刷新 → 未命中則查 PostgreSQL 或同步呼叫 API。
 * 
 * @param playerName - 球員全名（如 "Stephen Curry"），會被 URL encode
 * @param date - 查詢日期（YYYY-MM-DD），不提供則使用 UTC 今天
 * @returns Promise<PlayerProjection> - 單一球員的投影資料
 * @throws ApiError 404 - 找不到該球員的投影資料
 * 
 * @example
 * const proj = await getPlayerProjection("Stephen Curry", "2026-02-08");
 * console.log(`預計得分: ${proj.points}, 預計分鐘: ${proj.minutes}`);
 */
export async function getPlayerProjection(
  playerName: string,
  date?: string
): Promise<PlayerProjection> {
  // encodeURIComponent: 將球員名稱編碼為 URL 安全格式
  // 例如 "Stephen Curry" → "Stephen%20Curry"
  const encodedName = encodeURIComponent(playerName);
  
  const params = new URLSearchParams();
  
  if (date) {
    params.set("date", date);
  }
  
  const queryString = params.toString();
  const url = queryString
    ? `/api/nba/projections/${encodedName}?${queryString}`
    : `/api/nba/projections/${encodedName}`;
  
  const data = await fetchApi<PlayerProjection>(url);
  // 使用 playerProjectionSchema 驗證回應格式
  return playerProjectionSchema.parse(data);
}


export async function refreshProjections(
  date?: string
): Promise<ProjectionRefreshResponse> {
  const params = new URLSearchParams();
  
  if (date) {
    params.set("date", date);
  }
  
  const queryString = params.toString();
  const url = queryString
    ? `/api/nba/projections/refresh?${queryString}`
    : "/api/nba/projections/refresh";
  
  const data = await fetchApi<ProjectionRefreshResponse>(url, {
    method: "POST",
  });
  
  return projectionRefreshResponseSchema.parse(data);
}
