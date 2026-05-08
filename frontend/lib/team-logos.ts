/**
 * team-logos.ts - NBA 球隊 Logo 映射表
 * 
 * 使用 ESPN CDN 提供的官方 NBA 球隊 logo
 * CDN 格式：https://a.espncdn.com/i/teamlogos/nba/500/{TEAM_ABBREVIATION}.png
 * 
 * 功能：
 * - 根據球隊全名返回 logo URL
 * - 支援所有 30 支 NBA 球隊
 * - 提供預設 logo 作為後備方案
 */

/**
 * 球隊名稱到縮寫的映射表
 * 
 * ESPN CDN 使用球隊縮寫作為檔名
 * 例如：Lakers -> LAL, Warriors -> GSW
 */
const TEAM_NAME_TO_ABBR: Record<string, string> = {
  // 東區大西洋組
  "Boston Celtics": "BOS",
  "Brooklyn Nets": "BKN",
  "New York Knicks": "NY",
  "Philadelphia 76ers": "PHI",
  "Toronto Raptors": "TOR",

  // 東區中央組
  "Chicago Bulls": "CHI",
  "Cleveland Cavaliers": "CLE",
  "Detroit Pistons": "DET",
  "Indiana Pacers": "IND",
  "Milwaukee Bucks": "MIL",

  // 東區東南組
  "Atlanta Hawks": "ATL",
  "Charlotte Hornets": "CHA",
  "Miami Heat": "MIA",
  "Orlando Magic": "ORL",
  "Washington Wizards": "WSH",

  // 西區西南組
  "Dallas Mavericks": "DAL",
  "Houston Rockets": "HOU",
  "Memphis Grizzlies": "MEM",
  "New Orleans Pelicans": "NO",
  "San Antonio Spurs": "SA",

  // 西區西北組
  "Denver Nuggets": "DEN",
  "Minnesota Timberwolves": "MIN",
  "Oklahoma City Thunder": "OKC",
  "Portland Trail Blazers": "POR",
  "Utah Jazz": "UTAH",

  // 西區太平洋組
  "Golden State Warriors": "GS",
  "LA Clippers": "LAC",
  "Los Angeles Clippers": "LAC",
  "Los Angeles Lakers": "LAL",
  "Phoenix Suns": "PHX",
  "Sacramento Kings": "SAC",
};

/**
 * 簡短球隊名稱到完整名稱的映射
 * 
 * CSV 數據中使用簡短名稱（如 "Kings"），需要轉換為完整名稱才能獲取 logo
 */
const SHORT_NAME_TO_FULL: Record<string, string> = {
  // 東區
  "Celtics": "Boston Celtics",
  "Nets": "Brooklyn Nets",
  "Knicks": "New York Knicks",
  "76ers": "Philadelphia 76ers",
  "Raptors": "Toronto Raptors",
  "Bulls": "Chicago Bulls",
  "Cavaliers": "Cleveland Cavaliers",
  "Pistons": "Detroit Pistons",
  "Pacers": "Indiana Pacers",
  "Bucks": "Milwaukee Bucks",
  "Hawks": "Atlanta Hawks",
  "Hornets": "Charlotte Hornets",
  "Heat": "Miami Heat",
  "Magic": "Orlando Magic",
  "Wizards": "Washington Wizards",
  // 西區
  "Mavericks": "Dallas Mavericks",
  "Rockets": "Houston Rockets",
  "Grizzlies": "Memphis Grizzlies",
  "Pelicans": "New Orleans Pelicans",
  "Spurs": "San Antonio Spurs",
  "Nuggets": "Denver Nuggets",
  "Timberwolves": "Minnesota Timberwolves",
  "Thunder": "Oklahoma City Thunder",
  "Trail Blazers": "Portland Trail Blazers",
  "Jazz": "Utah Jazz",
  "Warriors": "Golden State Warriors",
  "Clippers": "Los Angeles Clippers",
  "Lakers": "Los Angeles Lakers",
  "Suns": "Phoenix Suns",
  "Kings": "Sacramento Kings",
};

/**
 * SportsDataIO 球隊縮寫到完整名稱的映射表
 * 
 * SportsDataIO 投影 API 使用自己的縮寫格式（如 "GS", "MIL"），
 * 與 ESPN CDN 的縮寫格式大部分相同，但有少數差異。
 * 這張表用來將 SportsDataIO 縮寫轉換為完整球隊名稱，
 * 再從 TEAM_NAME_TO_ABBR 取得 ESPN CDN 的正確縮寫。
 * 
 * 用途場景：
 * - daily_analysis 優先從 SportsDataIO 投影 API 取得球員當前球隊
 * - 該 API 回傳縮寫格式（如 "GS"），前端需要轉換才能取得 logo
 */
const ABBR_TO_FULL: Record<string, string> = {
  // 東區大西洋組
  "BOS": "Boston Celtics",
  "BKN": "Brooklyn Nets",
  "NY": "New York Knicks",
  "NYK": "New York Knicks",       // SportsDataIO 可能使用 NYK
  "PHI": "Philadelphia 76ers",
  "TOR": "Toronto Raptors",

  // 東區中央組
  "CHI": "Chicago Bulls",
  "CLE": "Cleveland Cavaliers",
  "DET": "Detroit Pistons",
  "IND": "Indiana Pacers",
  "MIL": "Milwaukee Bucks",

  // 東區東南組
  "ATL": "Atlanta Hawks",
  "CHA": "Charlotte Hornets",
  "MIA": "Miami Heat",
  "ORL": "Orlando Magic",
  "WAS": "Washington Wizards",     // SportsDataIO 使用 WAS
  "WSH": "Washington Wizards",     // ESPN 使用 WSH

  // 西區西南組
  "DAL": "Dallas Mavericks",
  "HOU": "Houston Rockets",
  "MEM": "Memphis Grizzlies",
  "NO": "New Orleans Pelicans",
  "NOP": "New Orleans Pelicans",   // SportsDataIO 可能使用 NOP
  "SA": "San Antonio Spurs",
  "SAS": "San Antonio Spurs",     // SportsDataIO 可能使用 SAS

  // 西區西北組
  "DEN": "Denver Nuggets",
  "MIN": "Minnesota Timberwolves",
  "OKC": "Oklahoma City Thunder",
  "POR": "Portland Trail Blazers",
  "UTA": "Utah Jazz",             // SportsDataIO 使用 UTA
  "UTAH": "Utah Jazz",            // ESPN 使用 UTAH

  // 西區太平洋組
  "GS": "Golden State Warriors",
  "GSW": "Golden State Warriors",  // SportsDataIO 可能使用 GSW
  "LAC": "Los Angeles Clippers",
  "LAL": "Los Angeles Lakers",
  "PHX": "Phoenix Suns",          // ESPN 使用 PHX
  "PHO": "Phoenix Suns",          // SportsDataIO 使用 PHO
  "SAC": "Sacramento Kings",
};

/**
 * ESPN CDN 的 logo 基礎 URL
 * 
 * 500 = 高解析度版本（500x500 px）
 * 可選尺寸：
 * - 500: 高解析度（500x500）
 * - 220: 中解析度（220x220）
 * - 65: 低解析度（65x65）
 */
const ESPN_LOGO_CDN = "https://a.espncdn.com/i/teamlogos/nba/500";

/**
 * 預設 NBA logo（當無法找到特定球隊時使用）
 * 使用 ESPN 的 NBA 官方 logo
 */
const DEFAULT_NBA_LOGO = "https://a.espncdn.com/i/teamlogos/leagues/500/nba.png";

/**
 * 將簡短球隊名稱轉換為完整名稱
 * 
 * @param shortName - 簡短球隊名稱（如 "Kings", "Lakers"）
 * @returns 完整球隊名稱，如果找不到則返回原名稱
 */
export function getFullTeamName(shortName: string): string {
  if (!shortName) return shortName;
  // 先嘗試簡短名稱（如 "Lakers"）
  const fromShort = SHORT_NAME_TO_FULL[shortName];
  if (fromShort) return fromShort;
  // 再嘗試縮寫（如 "LAL"）— SportsDataIO 投影 API 格式
  const fromAbbr = ABBR_TO_FULL[shortName.toUpperCase()];
  if (fromAbbr) return fromAbbr;
  // 都找不到就回傳原值
  return shortName;
}

/**
 * 根據球隊名稱取得 logo URL
 * 
 * @param teamName - 球隊名稱（可以是完整名稱或簡短名稱）
 * @returns logo 的 CDN URL
 * 
 * @example
 * ```ts
 * getTeamLogo("Los Angeles Lakers")
 * // 返回: "https://a.espncdn.com/i/teamlogos/nba/500/LAL.png"
 * 
 * getTeamLogo("Lakers")
 * // 也返回: "https://a.espncdn.com/i/teamlogos/nba/500/LAL.png"
 * 
 * getTeamLogo("Unknown Team")
 * // 返回: DEFAULT_NBA_LOGO (預設 NBA logo)
 * ```
 */
export function getTeamLogo(teamName: string): string {
  if (!teamName) {
    return DEFAULT_NBA_LOGO;
  }

  // 1. 先嘗試直接查找（完整名稱，如 "Los Angeles Lakers"）
  let abbr = TEAM_NAME_TO_ABBR[teamName];

  // 2. 如果找不到，嘗試從簡短名稱轉換（如 "Lakers" → "Los Angeles Lakers"）
  if (!abbr) {
    const fullName = SHORT_NAME_TO_FULL[teamName];
    if (fullName) {
      abbr = TEAM_NAME_TO_ABBR[fullName];
    }
  }

  // 3. 如果還是找不到，嘗試從縮寫查找（如 "GS", "MIL", "LAL"）
  //    這是 SportsDataIO 投影 API 回傳的格式，
  //    daily_analysis 會優先使用投影 API 的球隊，確保季中交易後即時更新
  if (!abbr) {
    const upperName = teamName.toUpperCase();
    const fullNameFromAbbr = ABBR_TO_FULL[upperName];
    if (fullNameFromAbbr) {
      abbr = TEAM_NAME_TO_ABBR[fullNameFromAbbr];
    }
  }

  if (!abbr) {
    console.warn(`找不到球隊 "${teamName}" 的 logo，使用預設 NBA logo`);
    return DEFAULT_NBA_LOGO;
  }

  return `${ESPN_LOGO_CDN}/${abbr}.png`;
}

/**
 * 縮寫到簡短名稱的映射表（用於 UI 顯示）
 * 
 * 將 SportsDataIO 縮寫格式（如 "GS"）轉為簡短顯示名稱（如 "Warriors"），
 * 這是 filter button、betslip 文字等地方使用的格式。
 * 
 * 為什麼不用全名？因為 filter button 空間有限，
 * "Warriors" 比 "Golden State Warriors" 更適合 UI 顯示。
 */
const ABBR_TO_SHORT: Record<string, string> = {
  "BOS": "Celtics", "BKN": "Nets", "NY": "Knicks", "NYK": "Knicks",
  "PHI": "76ers", "TOR": "Raptors",
  "CHI": "Bulls", "CLE": "Cavaliers", "DET": "Pistons",
  "IND": "Pacers", "MIL": "Bucks",
  "ATL": "Hawks", "CHA": "Hornets", "MIA": "Heat",
  "ORL": "Magic", "WAS": "Wizards", "WSH": "Wizards",
  "DAL": "Mavericks", "HOU": "Rockets", "MEM": "Grizzlies",
  "NO": "Pelicans", "NOP": "Pelicans", "SA": "Spurs", "SAS": "Spurs",
  "DEN": "Nuggets", "MIN": "Timberwolves", "OKC": "Thunder",
  "POR": "Trail Blazers", "UTA": "Jazz", "UTAH": "Jazz",
  "GS": "Warriors", "GSW": "Warriors", "LAC": "Clippers",
  "LAL": "Lakers", "PHX": "Suns", "PHO": "Suns", "SAC": "Kings",
};

const CANONICAL_TEAM_CODES: Record<string, string> = {
  ATL: "ATL",
  ATLANTAHAWKS: "ATL",
  HAWKS: "ATL",
  BOS: "BOS",
  BOSTONCELTICS: "BOS",
  CELTICS: "BOS",
  BKN: "BKN",
  BROOKLYNNETS: "BKN",
  NETS: "BKN",
  CHA: "CHA",
  CHARLOTTEHORNETS: "CHA",
  HORNETS: "CHA",
  CHI: "CHI",
  CHICAGOBULLS: "CHI",
  BULLS: "CHI",
  CLE: "CLE",
  CLEVELANDCAVALIERS: "CLE",
  CAVALIERS: "CLE",
  DAL: "DAL",
  DALLASMAVERICKS: "DAL",
  MAVERICKS: "DAL",
  DEN: "DEN",
  DENVERNUGGETS: "DEN",
  NUGGETS: "DEN",
  DET: "DET",
  DETROITPISTONS: "DET",
  PISTONS: "DET",
  GS: "GSW",
  GSW: "GSW",
  GOLDENSTATEWARRIORS: "GSW",
  WARRIORS: "GSW",
  HOU: "HOU",
  HOUSTONROCKETS: "HOU",
  ROCKETS: "HOU",
  IND: "IND",
  INDIANAPACERS: "IND",
  PACERS: "IND",
  LAC: "LAC",
  LOSANGELESCLIPPERS: "LAC",
  CLIPPERS: "LAC",
  LAL: "LAL",
  LOSANGELESLAKERS: "LAL",
  LAKERS: "LAL",
  MEM: "MEM",
  MEMPHISGRIZZLIES: "MEM",
  GRIZZLIES: "MEM",
  MIA: "MIA",
  MIAMIHEAT: "MIA",
  HEAT: "MIA",
  MIL: "MIL",
  MILWAUKEEBUCKS: "MIL",
  BUCKS: "MIL",
  MIN: "MIN",
  MINNESOTATIMBERWOLVES: "MIN",
  TIMBERWOLVES: "MIN",
  NO: "NOP",
  NOP: "NOP",
  NEWORLEANSPELICANS: "NOP",
  PELICANS: "NOP",
  NY: "NYK",
  NYK: "NYK",
  NEWYORKKNICKS: "NYK",
  KNICKS: "NYK",
  OKC: "OKC",
  OKLAHOMACITYTHUNDER: "OKC",
  THUNDER: "OKC",
  ORL: "ORL",
  ORLANDOMAGIC: "ORL",
  MAGIC: "ORL",
  PHI: "PHI",
  PHILADELPHIA76ERS: "PHI",
  "76ERS": "PHI",
  PHO: "PHX",
  PHX: "PHX",
  PHOENIXSUNS: "PHX",
  SUNS: "PHX",
  POR: "POR",
  PORTLANDTRAILBLAZERS: "POR",
  TRAILBLAZERS: "POR",
  SAC: "SAC",
  SACRAMENTOKINGS: "SAC",
  KINGS: "SAC",
  SA: "SAS",
  SAS: "SAS",
  SANANTONIOSPURS: "SAS",
  SPURS: "SAS",
  TOR: "TOR",
  TORONTORAPTORS: "TOR",
  RAPTORS: "TOR",
  UTA: "UTA",
  UTAH: "UTA",
  UTAHJAZZ: "UTA",
  JAZZ: "UTA",
  WAS: "WAS",
  WSH: "WAS",
  WASHINGTONWIZARDS: "WAS",
  WIZARDS: "WAS",
};

/**
 * 將任何球隊格式轉為簡短顯示名稱
 * 
 * 支援三種輸入格式：
 * - 縮寫（"GS", "MIL"）→ "Warriors", "Bucks"（來自 SportsDataIO 投影 API）
 * - 簡短名稱（"Warriors", "Bucks"）→ 原樣返回
 * - 完整名稱（"Golden State Warriors"）→ "Warriors"
 * 
 * 用途：UI 上顯示球隊名稱（filter button、betslip 文字等）
 * 
 * @param teamName - 任何格式的球隊名稱
 * @returns 簡短球隊名稱，如 "Warriors"、"Lakers"
 * 
 * @example
 * ```ts
 * getShortTeamName("GS")        // "Warriors"
 * getShortTeamName("Warriors")  // "Warriors"（已經是簡短名稱）
 * getShortTeamName("Golden State Warriors") // "Warriors"
 * ```
 */
export function getShortTeamName(teamName: string): string {
  if (!teamName) return teamName;
  
  // 1. 如果已經是簡短名稱（在 SHORT_NAME_TO_FULL 中），直接返回
  if (SHORT_NAME_TO_FULL[teamName]) {
    return teamName;
  }
  
  // 2. 如果是縮寫（如 "GS"），轉為簡短名稱
  const fromAbbr = ABBR_TO_SHORT[teamName.toUpperCase()];
  if (fromAbbr) return fromAbbr;
  
  // 3. 如果是完整名稱（如 "Golden State Warriors"），提取簡短部分
  //    反查 SHORT_NAME_TO_FULL 映射表
  for (const [shortName, fullName] of Object.entries(SHORT_NAME_TO_FULL)) {
    if (fullName === teamName) {
      return shortName;
    }
  }
  
  // 找不到就返回原值
  return teamName;
}

export function getCanonicalTeamCode(teamName: string): string {
  if (!teamName) return "";

  const normalized = teamName.toUpperCase().replace(/[^A-Z0-9]/g, "");
  return CANONICAL_TEAM_CODES[normalized] ?? normalized;
}

/**
 * 取得所有支援的球隊名稱列表
 * 
 * @returns 所有 NBA 球隊的全名陣列
 */
export function getAllTeamNames(): string[] {
  return Object.keys(TEAM_NAME_TO_ABBR);
}

/**
 * 檢查球隊名稱是否有效
 * 
 * @param teamName - 球隊全名
 * @returns 是否為有效的 NBA 球隊名稱
 */
export function isValidTeamName(teamName: string): boolean {
  return teamName in TEAM_NAME_TO_ABBR;
}
