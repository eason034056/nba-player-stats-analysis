/**
 * utils.ts - 工具函數
 * 
 * 包含各種輔助函數，用於：
 * - CSS 類別合併
 * - 日期格式化
 * - 數字格式化
 */

import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { format, parseISO } from "date-fns";
import { zhTW } from "date-fns/locale";

/**
 * 合併 CSS 類別
 * 
 * 使用 clsx 處理條件類別，再用 twMerge 合併 Tailwind 類別
 * 這樣可以避免 Tailwind 類別衝突
 * 
 * @param inputs - CSS 類別（可以是字串、物件、陣列）
 * @returns 合併後的類別字串
 * 
 * @example
 * cn("text-red-500", "text-blue-500")
 * // 結果: "text-blue-500"（後者覆蓋前者）
 * 
 * cn("px-4", isActive && "bg-blue-500")
 * // 條件類別
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}


/**
 * 格式化日期為顯示格式
 * 
 * 將 ISO 8601 日期字串轉換為易讀格式
 * 
 * @param dateString - ISO 8601 格式的日期字串
 * @param formatStr - 格式字串，預設 "MM/dd HH:mm"
 * @returns 格式化後的日期字串
 * 
 * @example
 * formatDate("2026-01-15T01:00:00Z")
 * // 結果: "01/15 09:00"（轉換為本地時間）
 */
export function formatDate(
  dateString: string,
  formatStr: string = "MM/dd HH:mm"
): string {
  try {
    const date = parseISO(dateString);
    return format(date, formatStr, { locale: zhTW });
  } catch {
    return dateString;
  }
}


/**
 * 格式化日期為完整格式
 * 
 * @param dateString - ISO 8601 格式的日期字串
 * @returns 完整的日期時間字串
 */
export function formatFullDate(dateString: string): string {
  try {
    const date = parseISO(dateString);
    return format(date, "yyyy年MM月dd日 HH:mm", { locale: zhTW });
  } catch {
    return dateString;
  }
}


/**
 * 格式化日期為友好格式（含星期）
 * 
 * @param dateString - YYYY-MM-DD 格式的日期字串
 * @returns 友好的日期字串，如 "1月15日（週三）"
 */
export function formatFriendlyDate(dateString: string): string {
  try {
    const date = new Date(dateString);
    return format(date, "M月d日（EEEE）", { locale: zhTW });
  } catch {
    return dateString;
  }
}


/**
 * 判斷日期是否為今天
 * 
 * @param dateString - YYYY-MM-DD 格式的日期字串
 * @returns 是否為今天
 */
export function isToday(dateString: string): boolean {
  return dateString === getTodayString();
}


/**
 * 判斷日期是否為明天
 * 
 * @param dateString - YYYY-MM-DD 格式的日期字串
 * @returns 是否為明天
 */
export function isTomorrow(dateString: string): boolean {
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  return dateString === format(tomorrow, "yyyy-MM-dd");
}


/**
 * 取得日期的顯示標題
 * 
 * 如果是今天顯示「今天」，明天顯示「明天」，否則顯示完整日期
 * 
 * @param dateString - YYYY-MM-DD 格式的日期字串
 * @returns 顯示標題
 */
export function getDateDisplayTitle(dateString: string): string {
  if (isToday(dateString)) {
    return "今天";
  }
  if (isTomorrow(dateString)) {
    return "明天";
  }
  return formatFriendlyDate(dateString);
}


/**
 * 格式化比賽時間（只顯示時間）
 * 
 * @param dateString - ISO 8601 格式的日期字串
 * @returns 時間字串，如 "19:30"
 */
export function formatGameTime(dateString: string): string {
  try {
    const date = parseISO(dateString);
    return format(date, "HH:mm", { locale: zhTW });
  } catch {
    return dateString;
  }
}


/**
 * 格式化機率為百分比
 * 
 * @param probability - 機率（0-1 之間的小數）
 * @param decimals - 小數位數，預設 1
 * @returns 百分比字串
 * 
 * @example
 * formatProbability(0.5238)
 * // 結果: "52.4%"
 */
export function formatProbability(
  probability: number,
  decimals: number = 1
): string {
  return `${(probability * 100).toFixed(decimals)}%`;
}


/**
 * 格式化美式賠率
 * 
 * 美式賠率：正數加 + 號，負數保持原樣
 * 
 * @param odds - 美式賠率
 * @returns 格式化的賠率字串
 * 
 * @example
 * formatAmericanOdds(-110) // "-110"
 * formatAmericanOdds(150)  // "+150"
 */
export function formatAmericanOdds(odds: number): string {
  if (odds > 0) {
    return `+${odds}`;
  }
  return odds.toString();
}


/**
 * 格式化水錢為百分比
 * 
 * 水錢通常以百分比顯示，讓使用者容易理解
 * 
 * @param vig - 水錢（小數）
 * @returns 百分比字串
 * 
 * @example
 * formatVig(0.0476)
 * // 結果: "4.8%"
 */
export function formatVig(vig: number): string {
  return `${(vig * 100).toFixed(1)}%`;
}


/**
 * 取得今天的日期字串
 * 
 * @returns YYYY-MM-DD 格式的今天日期
 */
export function getTodayString(): string {
  return format(new Date(), "yyyy-MM-dd");
}

export function getLocalDateString(dateString: string): string | undefined {
  try {
    const date = parseISO(dateString);
    return format(date, "yyyy-MM-dd");
  } catch {
    return undefined;
  }
}


/**
 * 判斷機率是否有優勢
 * 
 * 如果去水機率 > 隱含機率，表示這個賠率可能有價值
 * 
 * @param fairProb - 去水機率
 * @param impliedProb - 隱含機率
 * @returns 是否有優勢
 */
export function hasEdge(fairProb: number, impliedProb: number): boolean {
  return fairProb > impliedProb;
}


/**
 * 取得博彩公司的顯示名稱
 * 
 * 將 API 的 key 轉換為易讀的名稱
 * 
 * @param key - 博彩公司 key（如 "draftkings"）
 * @returns 顯示名稱（如 "DraftKings"）
 */
export function getBookmakerDisplayName(key: string): string {
  const nameMap: Record<string, string> = {
    // 主流平台
    draftkings: "DraftKings",
    fanduel: "FanDuel",
    betmgm: "BetMGM",
    caesars: "Caesars",
    espnbet: "ESPN Bet",
    
    // 知名線上博彩
    bet365: "Bet365",
    pointsbetus: "PointsBet",
    betrivers: "BetRivers",
    unibet_us: "Unibet",
    williamhill_us: "William Hill",
    
    // 賭場/區域型
    hardrockbet: "Hard Rock Bet",
    borgata: "Borgata",
    bally_bet: "Bally Bet",
    sisportsbook: "SI Sportsbook",
    wynnbet: "WynnBet",
    
    // 其他美國運彩平台
    betfred: "Betfred",
    betway: "Betway",
    circasports: "Circa Sports",
    fliff: "Fliff",
    livescorebet_us: "LiveScore Bet",
    lowvig: "LowVig.ag",
    mybookieag: "MyBookie",
    bovada: "Bovada",
    betonlineag: "BetOnline.ag",
    superbook: "SuperBook",
    twinspires: "TwinSpires",
    betparx: "BetPARX",
    foxbet: "FOX Bet",
    sugarhouse: "SugarHouse",
    windcreek: "Wind Creek",
  };
  
  return nameMap[key] || key;
}


/**
 * 取得市場類型的顯示名稱
 * 
 * 將 API 的 market key 轉換為易讀的中文名稱
 * 
 * @param key - 市場 key（如 "player_points"）
 * @returns 顯示名稱（如 "得分"）
 * 
 * @example
 * getMarketDisplayName("player_points")
 * // 結果: "得分"
 * 
 * getMarketDisplayName("player_assists")
 * // 結果: "助攻"
 */
export function getMarketDisplayName(key: string): string {
  const nameMap: Record<string, string> = {
    player_points: "得分",
    player_assists: "助攻",
    player_rebounds: "籃板",
    player_points_rebounds_assists: "得分+籃板+助攻 (PRA)",
    player_threes: "三分球",
    player_steals: "抄截",
    player_blocks: "阻攻",
    player_turnovers: "失誤",
  };
  
  return nameMap[key] || key;
}
