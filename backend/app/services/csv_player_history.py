"""
csv_player_history.py - CSV 球員歷史數據服務

從 data/nba_player_game_logs.csv 讀取球員歷史比賽數據
並計算經驗機率（empirical probability）

功能：
1. 讀取並快取 CSV 資料
2. 取得所有球員名單
3. 計算指定球員的歷史數據分佈和機率

CSV 欄位對應：
- Player -> player_name
- PTS -> points
- AST -> assists  
- REB -> rebounds (ORB + DRB)
- Date -> game_date
- MIN -> minutes
"""

import csv
import os
from typing import List, Optional, Dict, Any, Set, Tuple
from datetime import datetime
import statistics

# CSV 檔案路徑
# 優先使用環境變數，否則使用預設路徑
# 在 Docker 環境中，data 目錄會被掛載到 /app/data
# 在本地開發中，路徑相對於專案根目錄
def _get_csv_path() -> str:
    """
    取得 CSV 檔案路徑
    
    優先順序：
    1. 環境變數 CSV_DATA_PATH
    2. /app/data/nba_player_game_logs.csv（Docker 環境）
    3. 相對於專案根目錄的 data/nba_player_game_logs.csv
    
    Returns:
        str: CSV 檔案的絕對路徑
    """
    # 1. 優先使用環境變數
    env_path = os.environ.get("CSV_DATA_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    
    # 2. Docker 環境路徑（/app/data/）
    docker_path = "/app/data/nba_player_game_logs.csv"
    if os.path.exists(docker_path):
        return docker_path
    
    # 3. 本地開發路徑（相對於專案根目錄）
    local_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "data",
        "nba_player_game_logs.csv"
    )
    return local_path


CSV_PATH = _get_csv_path()


class CSVPlayerHistoryService:
    """
    CSV 球員歷史數據服務
    
    使用模組級快取（module-level cache）避免每次請求都重新讀取 CSV
    這是一個單例模式（Singleton Pattern）的實現
    
    Attributes:
        _cache: 快取的 CSV 資料（球員名稱為 key）
        _all_players: 所有球員名單（排序後）
        _loaded: 是否已載入資料
    """
    
    def __init__(self):
        self._cache: Dict[str, List[Dict[str, Any]]] = {}  # player_name -> game_logs
        self._all_players: List[str] = []  # 所有球員名單
        self._lineup_cache: Dict[Tuple[str, str], Set[str]] = {}  # (team, date_str) -> {player_names}
        self._loaded: bool = False  # 是否已載入
    
    def reload(self) -> None:
        """
        強制重新載入 CSV 資料
        
        清除所有快取並重新讀取 CSV 檔案
        用於：
        - CSV 檔案更新後重新載入
        - 開發時修改程式碼後刷新資料
        """
        print("🔄 正在重新載入 CSV 資料...")
        self._cache = {}
        self._all_players = []
        self._lineup_cache = {}
        self._loaded = False
        self.load_csv()
        print(f"✅ 重新載入完成，共 {len(self._all_players)} 位球員")
    
    def _parse_minutes(self, min_str: str) -> float:
        """
        解析分鐘欄位（格式：MM:SS 或數字）
        
        Args:
            min_str: 分鐘字串，例如 "32:15" 或 "32.5"
        
        Returns:
            float: 總分鐘數
        
        Example:
            "32:15" -> 32.25 (32分鐘 + 15秒 = 32.25分鐘)
            "32" -> 32.0
            "" -> 0.0
        """
        if not min_str or min_str.strip() == "":
            return 0.0
        
        min_str = min_str.strip()
        
        # 處理 MM:SS 格式
        if ":" in min_str:
            parts = min_str.split(":")
            try:
                minutes = int(parts[0])
                seconds = int(parts[1]) if len(parts) > 1 else 0
                return minutes + seconds / 60
            except ValueError:
                return 0.0
        
        # 處理純數字格式
        try:
            return float(min_str)
        except ValueError:
            return 0.0
    
    def _parse_float(self, value: str) -> Optional[float]:
        """
        安全地將字串轉換為浮點數
        
        Args:
            value: 要轉換的字串
        
        Returns:
            Optional[float]: 轉換後的數值，如果無法轉換則返回 None
        """
        if not value or value.strip() == "":
            return None
        try:
            return float(value.strip())
        except ValueError:
            return None
    
    def load_csv(self) -> None:
        """
        載入 CSV 檔案到記憶體
        
        只在第一次呼叫時執行，後續呼叫會直接返回（因為 _loaded 為 True）
        
        流程：
        1. 檢查檔案是否存在
        2. 讀取 CSV 檔案
        3. 解析每一行資料
        4. 按球員名稱分組存入快取
        5. 建立球員名單
        
        Raises:
            FileNotFoundError: 當 CSV 檔案不存在時
        """
        if self._loaded:
            return
        
        if not os.path.exists(CSV_PATH):
            raise FileNotFoundError(f"CSV 檔案不存在: {CSV_PATH}")
        
        # 讀取 CSV
        # 使用 utf-8-sig 編碼自動處理 BOM (Byte Order Mark)
        # 常見於從 Excel 匯出的 UTF-8 CSV 檔案
        with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                # 解析球員名稱
                player_name = row.get("Player", "").strip()
                if not player_name:
                    continue
                
                # 解析數值欄位
                pts = self._parse_float(row.get("PTS", ""))
                ast = self._parse_float(row.get("AST", ""))
                orb = self._parse_float(row.get("ORB", ""))
                drb = self._parse_float(row.get("DRB", ""))
                reb = self._parse_float(row.get("REB", ""))
                
                # 如果 REB 欄位沒有值，則用 ORB + DRB 計算
                if reb is None and orb is not None and drb is not None:
                    reb = orb + drb
                
                # 解析分鐘數
                minutes = self._parse_minutes(row.get("MIN", ""))
                
                # 解析日期
                date_str = row.get("Date", "")
                game_date = None
                if date_str:
                    try:
                        # 嘗試解析日期格式：M/D/YYYY
                        game_date = datetime.strptime(date_str, "%m/%d/%Y")
                    except ValueError:
                        try:
                            # 嘗試其他格式：YYYY-MM-DD
                            game_date = datetime.strptime(date_str, "%Y-%m-%d")
                        except ValueError:
                            pass
                
                # 解析先發狀態
                status = row.get("Status", "").strip()
                is_starter = status.lower() == "starter"
                
                # Parse all 28 CSV columns
                season = row.get("Season", "").strip()
                wl = row.get("W/L", "").strip()
                pos = row.get("Pos", "").strip()

                fgm = self._parse_float(row.get("FGM", ""))
                fga = self._parse_float(row.get("FGA", ""))
                fg_pct = self._parse_float(row.get("FG%", ""))
                tpm = self._parse_float(row.get("3PM", ""))
                tpa = self._parse_float(row.get("3PA", ""))
                tp_pct = self._parse_float(row.get("3P%", ""))
                ftm = self._parse_float(row.get("FTM", ""))
                fta = self._parse_float(row.get("FTA", ""))
                ft_pct = self._parse_float(row.get("FT%", ""))
                stl = self._parse_float(row.get("STL", ""))
                blk = self._parse_float(row.get("BLK", ""))
                tov = self._parse_float(row.get("TOV", ""))
                pf = self._parse_float(row.get("PF", ""))
                fic = self._parse_float(row.get("FIC", ""))

                game_log = {
                    "player_name": player_name,
                    "game_date": game_date,
                    "season": season,
                    "points": pts,
                    "assists": ast,
                    "rebounds": reb,
                    "minutes": minutes,
                    "pra": (pts or 0) + (reb or 0) + (ast or 0) if pts is not None else None,
                    "team": row.get("Team", "").strip(),
                    "opponent": row.get("Opponent", "").strip(),
                    "status": status,
                    "is_starter": is_starter,
                    "wl": wl,
                    "pos": pos,
                    "fgm": fgm, "fga": fga, "fg_pct": fg_pct,
                    "tpm": tpm, "tpa": tpa, "tp_pct": tp_pct,
                    "ftm": ftm, "fta": fta, "ft_pct": ft_pct,
                    "orb": orb, "drb": drb,
                    "stl": stl, "blk": blk, "tov": tov, "pf": pf,
                    "fic": fic,
                }
                
                # 按球員分組
                if player_name not in self._cache:
                    self._cache[player_name] = []
                self._cache[player_name].append(game_log)
                
                # 建立 lineup cache：(team, date_str) -> 有出賽球員集合
                if minutes > 0 and game_date is not None:
                    team = row.get("Team", "").strip()
                    date_key = game_date.strftime("%Y-%m-%d")
                    lineup_key = (team, date_key)
                    if lineup_key not in self._lineup_cache:
                        self._lineup_cache[lineup_key] = set()
                    self._lineup_cache[lineup_key].add(player_name)
        
        # 建立球員名單（排序）
        self._all_players = sorted(self._cache.keys())
        
        # 對每個球員的比賽記錄按日期排序（最新的在前面）
        for player in self._cache:
            self._cache[player].sort(
                key=lambda x: x["game_date"] or datetime.min,
                reverse=True  # 最新的在前面
            )
        
        self._loaded = True
        print(f"✅ 已載入 CSV，共 {len(self._all_players)} 位球員")
    
    def get_all_players(self, search: Optional[str] = None) -> List[str]:
        """
        取得所有球員名單
        
        Args:
            search: 搜尋關鍵字（可選），用於過濾球員名稱
        
        Returns:
            List[str]: 球員名稱列表（已排序）
        
        Example:
            get_all_players()  # 返回所有球員
            get_all_players("curry")  # 返回包含 "curry" 的球員
        """
        self.load_csv()
        
        if not search:
            return self._all_players
        
        # 過濾（不區分大小寫）
        search_lower = search.lower()
        return [p for p in self._all_players if search_lower in p.lower()]
    
    def get_player_opponents(self, player_name: str) -> List[str]:
        """
        取得球員曾經對戰過的所有對手
        
        Args:
            player_name: 球員名稱
        
        Returns:
            List[str]: 對手球隊名稱列表（已去重並排序）
        """
        self.load_csv()
        
        player_games = self._cache.get(player_name, [])
        if not player_games:
            # 嘗試模糊匹配
            player_lower = player_name.lower()
            for p in self._all_players:
                if player_lower in p.lower() or p.lower() in player_lower:
                    player_games = self._cache.get(p, [])
                    break
        
        opponents = set()
        for game in player_games:
            opponent = game.get("opponent", "")
            if opponent:
                opponents.add(opponent)
        
        return sorted(list(opponents))

    def get_players_in_game(self, team: str, date: datetime) -> Set[str]:
        """
        查詢某隊在某天出賽的球員集合
        
        Args:
            team: 球隊名稱（如 "Bucks"）
            date: 比賽日期
        
        Returns:
            Set[str]: 出賽球員名稱集合
        """
        self.load_csv()
        date_key = date.strftime("%Y-%m-%d")
        return self._lineup_cache.get((team, date_key), set())
    
    def get_teammates(self, player_name: str) -> List[str]:
        """
        取得與該球員同隊出賽過的所有隊友名單
        
        遍歷該球員的所有 game log，從 _lineup_cache 中收集同場出賽的隊友。
        
        Args:
            player_name: 球員名稱
        
        Returns:
            List[str]: 隊友名稱列表（已去重、排序，不含自己）
        """
        self.load_csv()
        
        player_games = self._cache.get(player_name, [])
        if not player_games:
            player_lower = player_name.lower()
            for p in self._all_players:
                if player_lower in p.lower() or p.lower() in player_lower:
                    player_games = self._cache.get(p, [])
                    player_name = p
                    break
        
        teammates: Set[str] = set()
        for game in player_games:
            team = game.get("team", "")
            game_date = game.get("game_date")
            if not team or game_date is None:
                continue
            date_key = game_date.strftime("%Y-%m-%d")
            lineup = self._lineup_cache.get((team, date_key), set())
            teammates.update(lineup)
        
        teammates.discard(player_name)
        return sorted(teammates)

    def get_player_stats(
        self,
        player_name: str,
        metric: str,
        threshold: float,
        n: int = 0,
        bins: int = 15,
        exclude_dnp: bool = True,
        opponent: Optional[str] = None,
        is_starter: Optional[bool] = None,
        teammate_filter: Optional[List[str]] = None,
        teammate_played: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        計算球員歷史數據統計
        
        這是核心功能！計算指定球員在指定指標上的歷史機率分佈。
        
        Args:
            player_name: 球員名稱
            metric: 統計指標（points/assists/rebounds/pra）
            threshold: 閾值（例如 24.5）
            n: 最近 N 場比賽（0 表示全部）
            bins: 直方圖分箱數（預設 15）
            exclude_dnp: 是否排除 DNP（Did Not Play，分鐘數為 0 的場次）
            opponent: 對手篩選（可選，None 表示全部）
            is_starter: 先發狀態篩選（True=僅先發、False=僅替補、None=全部）
            teammate_filter: 星級隊友名稱列表（可選，例如 ["Giannis Antetokounmpo"]）
            teammate_played: True=僅隊友皆有上場、False=僅隊友皆未上場、None=不篩選
        
        Returns:
            Dict 包含：
            - player: 球員名稱
            - metric: 統計指標
            - threshold: 閾值
            - n_games: 樣本場次
            - p_over: Over 機率（value > threshold）
            - p_under: Under 機率（value < threshold）
            - mean: 平均值
            - std: 標準差
            - histogram: 直方圖資料（已棄用，保留兼容性）
            - game_logs: 每場比賽詳細資料
            - opponents: 對手列表
            - teammates: 隊友列表（用於前端多選）
        
        Example:
            get_player_stats("Stephen Curry", "points", 24.5, n=20)
            
            get_player_stats("A.J. Green", "points", 10.5,
                             teammate_filter=["Giannis Antetokounmpo"], teammate_played=False)
            # 返回 A.J. Green 在 Giannis 未上場時的得分統計
        """
        self.load_csv()
        
        # 取得球員的比賽記錄
        player_games = self._cache.get(player_name, [])
        
        if not player_games:
            # 嘗試模糊匹配
            player_lower = player_name.lower()
            matched_player = None
            for p in self._all_players:
                if player_lower in p.lower() or p.lower() in player_lower:
                    matched_player = p
                    break
            
            if matched_player:
                player_games = self._cache.get(matched_player, [])
                player_name = matched_player
        
        if not player_games:
            return {
                "player": player_name,
                "metric": metric,
                "threshold": threshold,
                "n_games": 0,
                "p_over": None,
                "p_under": None,
                "mean": None,
                "std": None,
                "histogram": [],
                "game_logs": [],
                "opponents": [],
                "teammates": [],
                "message": f"找不到球員 '{player_name}'"
            }
        
        # 取得所有對手（用於篩選器）
        all_opponents = self.get_player_opponents(player_name)
        # 取得所有隊友（用於星級隊友選擇器，僅限同隊）
        all_teammates = self.get_teammates(player_name)
        
        # 驗證 teammate_filter：只接受同隊隊友，過濾掉非隊友
        validated_teammate_filter = None
        if teammate_filter:
            teammate_set = set(all_teammates)
            validated_teammate_filter = [t for t in teammate_filter if t in teammate_set]
            if not validated_teammate_filter and teammate_filter:
                validated_teammate_filter = None
        
        # 收集有效的比賽記錄
        valid_games: List[Dict[str, Any]] = []
        values: List[float] = []
        
        for game in player_games:
            # 排除 DNP
            if exclude_dnp and game.get("minutes", 0) == 0:
                continue
            
            # 對手篩選
            if opponent and game.get("opponent", "") != opponent:
                continue
            
            # 先發狀態篩選
            # is_starter=True: 只要先發場次
            # is_starter=False: 只要替補場次
            # is_starter=None: 全部場次
            if is_starter is not None:
                if game.get("is_starter", False) != is_starter:
                    continue
            
            # 星級隊友篩選（僅限同隊隊友）
            # teammate_played=True: 所有選定隊友都有出賽
            # teammate_played=False: 所有選定隊友都未出賽
            if validated_teammate_filter and teammate_played is not None:
                game_team = game.get("team", "")
                game_date = game.get("game_date")
                if game_team and game_date:
                    date_key = game_date.strftime("%Y-%m-%d")
                    lineup = self._lineup_cache.get((game_team, date_key), set())
                    if teammate_played:
                        if not all(t in lineup for t in validated_teammate_filter):
                            continue
                    else:
                        if any(t in lineup for t in validated_teammate_filter):
                            continue
            
            # 取得對應指標的值
            value = game.get(metric)
            if value is not None:
                values.append(value)
                
                # 建構 game log 資料
                game_date = game.get("game_date")
                minutes = game.get("minutes", 0)
                game_is_starter = game.get("is_starter", False)
                
                valid_games.append({
                    "date": game_date.strftime("%m/%d") if game_date else "",
                    "date_full": game_date.strftime("%Y-%m-%d") if game_date else "",
                    "opponent": game.get("opponent", ""),
                    "value": value,
                    "is_over": value > threshold,
                    "team": game.get("team", ""),
                    "minutes": round(minutes, 1),  # 上場時間（分鐘）
                    "is_starter": game_is_starter,  # 是否先發
                })
        
        # 取最近 N 場
        if n > 0 and len(valid_games) > n:
            valid_games = valid_games[:n]
            values = values[:n]
        
        if not values:
            return {
                "player": player_name,
                "metric": metric,
                "threshold": threshold,
                "n_games": 0,
                "p_over": None,
                "p_under": None,
                "mean": None,
                "std": None,
                "histogram": [],
                "game_logs": [],
                "opponents": all_opponents,
                "teammates": all_teammates,
                "message": f"球員 '{player_name}' 沒有 {metric} 的有效資料"
            }
        
        # 計算 Over/Under 機率
        # Over: value > threshold
        # Under: value < threshold
        over_count = sum(1 for v in values if v > threshold)
        under_count = sum(1 for v in values if v < threshold)
        equal_count = sum(1 for v in values if v == threshold)
        
        n_games = len(values)
        p_over = over_count / n_games if n_games > 0 else None
        p_under = under_count / n_games if n_games > 0 else None
        
        # 計算平均值和標準差
        mean_val = statistics.mean(values)
        std_val = statistics.stdev(values) if len(values) > 1 else 0.0
        
        # 計算直方圖（保留兼容性）
        histogram = self._calculate_histogram(values, bins)
        
        # 反轉 game_logs 順序，讓最舊的在前（用於時間序列圖表）
        game_logs_for_chart = list(reversed(valid_games))
        
        return {
            "player": player_name,
            "metric": metric,
            "threshold": threshold,
            "n_games": n_games,
            "p_over": round(p_over, 4) if p_over is not None else None,
            "p_under": round(p_under, 4) if p_under is not None else None,
            "equal_count": equal_count,
            "mean": round(mean_val, 2),
            "std": round(std_val, 2),
            "histogram": histogram,
            "game_logs": game_logs_for_chart,
            "opponents": all_opponents,
            "teammates": all_teammates,
            "opponent_filter": opponent,
            "teammate_filter": validated_teammate_filter,
            "teammate_played": teammate_played,
            "message": None
        }
    
    def _calculate_histogram(
        self,
        values: List[float],
        bins: int
    ) -> List[Dict[str, Any]]:
        """
        計算直方圖（histogram）
        
        將數值分成 bins 個區間，計算每個區間的數量
        
        Args:
            values: 數值列表
            bins: 分箱數
        
        Returns:
            List[Dict] 每個元素包含：
            - binStart: 區間起始值
            - binEnd: 區間結束值
            - count: 該區間的數量
        
        分箱策略：
        - 計算 min 和 max
        - bin_width = (max - min) / bins
        - 最後一個 bin 包含 max 值
        """
        if not values or bins < 1:
            return []
        
        min_val = min(values)
        max_val = max(values)
        
        # 避免 max == min 導致除以 0
        if max_val == min_val:
            return [{
                "binStart": min_val,
                "binEnd": max_val,
                "count": len(values)
            }]
        
        bin_width = (max_val - min_val) / bins
        histogram = []
        
        for i in range(bins):
            bin_start = min_val + i * bin_width
            bin_end = min_val + (i + 1) * bin_width
            
            # 計算落在此區間的數量
            # 最後一個 bin 包含等於 max 的值
            if i == bins - 1:
                count = sum(1 for v in values if bin_start <= v <= bin_end)
            else:
                count = sum(1 for v in values if bin_start <= v < bin_end)
            
            histogram.append({
                "binStart": round(bin_start, 2),
                "binEnd": round(bin_end, 2),
                "count": count
            })
        
        return histogram


# 建立單例實例
# 這個實例會在模組被 import 時建立，之後都使用同一個實例
csv_player_service = CSVPlayerHistoryService()

