"""
test_matching.py - 球員名稱匹配模組的單元測試

測試內容：
1. 名稱正規化（normalize）
2. 精確匹配（exact match）
3. 模糊匹配（fuzzy match）
4. 主要匹配函數（find_player）
"""

import pytest
import sys
import os

# 將專案根目錄加入 Python 路徑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.normalize import (
    normalize_name,
    exact_match,
    fuzzy_match,
    find_player,
    extract_player_names
)


class TestNormalizeName:
    """
    測試名稱正規化函數
    
    normalize_name 會：
    1. 去除前後空白
    2. 轉小寫
    3. 移除特殊符號（. ' -）
    4. 合併多餘空白
    """
    
    def test_basic_normalization(self):
        """
        測試基本正規化：去空白、轉小寫
        """
        result = normalize_name("  Stephen Curry  ")
        assert result == "stephen curry"
    
    def test_remove_period(self):
        """
        測試移除句點
        
        例如 "P.J. Washington" 變成 "pj washington"
        """
        result = normalize_name("P.J. Washington")
        assert result == "pj washington"
    
    def test_remove_apostrophe(self):
        """
        測試移除單引號
        
        例如 "D'Angelo Russell" 變成 "dangelo russell"
        """
        result = normalize_name("D'Angelo Russell")
        assert result == "dangelo russell"
    
    def test_remove_hyphen(self):
        """
        測試移除連字號
        
        例如 "Shai Gilgeous-Alexander" 變成 "shai gilgeousalexander"
        """
        result = normalize_name("Shai Gilgeous-Alexander")
        assert result == "shai gilgeousalexander"
    
    def test_multiple_spaces(self):
        """
        測試合併多餘空白
        """
        result = normalize_name("Stephen    Curry")
        assert result == "stephen curry"
    
    def test_empty_string(self):
        """
        測試空字串
        """
        result = normalize_name("")
        assert result == ""
    
    def test_mixed_case(self):
        """
        測試混合大小寫
        """
        result = normalize_name("LeBron JAMES")
        assert result == "lebron james"


class TestExactMatch:
    """
    測試精確匹配函數
    
    exact_match 在正規化後進行完全相等比較
    """
    
    def test_exact_match_found(self):
        """
        測試找到精確匹配
        """
        candidates = ["Stephen Curry", "Seth Curry", "LeBron James"]
        result = exact_match("Stephen Curry", candidates)
        assert result == "Stephen Curry"
    
    def test_case_insensitive_match(self):
        """
        測試大小寫不敏感匹配
        """
        candidates = ["Stephen Curry", "Seth Curry"]
        result = exact_match("stephen curry", candidates)
        assert result == "Stephen Curry"
    
    def test_no_match(self):
        """
        測試找不到匹配
        """
        candidates = ["Stephen Curry", "Seth Curry"]
        result = exact_match("Kevin Durant", candidates)
        assert result is None
    
    def test_special_characters_match(self):
        """
        測試特殊字元不影響匹配
        """
        candidates = ["D'Angelo Russell", "P.J. Washington"]
        result = exact_match("dangelo russell", candidates)
        assert result == "D'Angelo Russell"
    
    def test_empty_candidates(self):
        """
        測試空候選列表
        """
        result = exact_match("Stephen Curry", [])
        assert result is None


class TestFuzzyMatch:
    """
    測試模糊匹配函數
    
    fuzzy_match 使用字串相似度演算法
    """
    
    def test_fuzzy_match_similar(self):
        """
        測試相似名稱的模糊匹配
        """
        candidates = ["Stephen Curry", "Seth Curry", "LeBron James"]
        result = fuzzy_match("Steph Curry", candidates, threshold=80)
        
        # 應該匹配到 Stephen Curry
        assert result is not None
        assert result[0] == "Stephen Curry"
        assert result[1] >= 80  # 分數應該 >= 門檻
    
    def test_fuzzy_match_threshold(self):
        """
        測試門檻值過濾
        
        太不相似的名稱不應該匹配
        """
        candidates = ["Stephen Curry", "Seth Curry"]
        result = fuzzy_match("Kevin Durant", candidates, threshold=90)
        
        # 不應該匹配（因為差異太大）
        assert result is None
    
    def test_fuzzy_match_typo(self):
        """
        測試拼寫錯誤的模糊匹配
        """
        candidates = ["Stephen Curry", "LeBron James"]
        result = fuzzy_match("Stefen Curry", candidates, threshold=80)
        
        assert result is not None
        assert result[0] == "Stephen Curry"
    
    def test_fuzzy_match_empty_candidates(self):
        """
        測試空候選列表
        """
        result = fuzzy_match("Stephen Curry", [], threshold=80)
        assert result is None


class TestFindPlayer:
    """
    測試主要匹配函數
    
    find_player 先嘗試精確匹配，失敗則嘗試模糊匹配
    """
    
    def test_find_player_exact(self):
        """
        測試精確匹配優先
        """
        candidates = ["Stephen Curry", "Seth Curry", "Steph Curry Jr"]
        result = find_player("Stephen Curry", candidates)
        assert result == "Stephen Curry"
    
    def test_find_player_fuzzy(self):
        """
        測試模糊匹配回退
        """
        candidates = ["Stephen Curry", "Seth Curry"]
        result = find_player("Steph Curry", candidates, threshold=80)
        assert result == "Stephen Curry"
    
    def test_find_player_not_found(self):
        """
        測試找不到匹配
        """
        candidates = ["Stephen Curry", "Seth Curry"]
        result = find_player("Kevin Durant", candidates, threshold=90)
        assert result is None
    
    def test_find_player_similar_names(self):
        """
        測試相似名稱（如 Curry 兄弟）
        
        應該匹配到最相似的
        """
        candidates = ["Stephen Curry", "Seth Curry"]
        
        # 查詢 Stephen 應該找到 Stephen
        result1 = find_player("Stephen Curry", candidates)
        assert result1 == "Stephen Curry"
        
        # 查詢 Seth 應該找到 Seth
        result2 = find_player("Seth Curry", candidates)
        assert result2 == "Seth Curry"
    
    def test_find_player_case_insensitive(self):
        """
        測試大小寫不敏感
        """
        candidates = ["LeBron James"]
        result = find_player("lebron james", candidates)
        assert result == "LeBron James"


class TestExtractPlayerNames:
    """
    測試從 outcomes 提取球員名稱
    """
    
    def test_extract_from_description(self):
        """
        測試從 description 欄位提取
        """
        outcomes = [
            {"name": "Over", "description": "Stephen Curry", "price": -110},
            {"name": "Under", "description": "Stephen Curry", "price": -110},
            {"name": "Over", "description": "LeBron James", "price": -115},
            {"name": "Under", "description": "LeBron James", "price": -105}
        ]
        
        players = extract_player_names(outcomes)
        
        assert len(players) == 2
        assert "Stephen Curry" in players
        assert "LeBron James" in players
    
    def test_extract_from_player_field(self):
        """
        測試從 player 欄位提取（某些 API 可能使用此欄位）
        """
        outcomes = [
            {"name": "Over", "player": "Kevin Durant"},
            {"name": "Under", "player": "Kevin Durant"}
        ]
        
        players = extract_player_names(outcomes)
        
        assert len(players) == 1
        assert "Kevin Durant" in players
    
    def test_extract_empty_outcomes(self):
        """
        測試空 outcomes 列表
        """
        players = extract_player_names([])
        assert players == []
    
    def test_extract_no_player_info(self):
        """
        測試沒有球員資訊的 outcomes
        """
        outcomes = [
            {"name": "Over", "price": -110},
            {"name": "Under", "price": -110}
        ]
        
        players = extract_player_names(outcomes)
        assert players == []
    
    def test_extract_duplicate_removal(self):
        """
        測試去除重複名稱
        
        同一球員有 Over/Under 兩個 outcome，
        應該只返回一次
        """
        outcomes = [
            {"name": "Over", "description": "Stephen Curry"},
            {"name": "Under", "description": "Stephen Curry"},
            {"name": "Over", "description": "Stephen Curry"}  # 重複
        ]
        
        players = extract_player_names(outcomes)
        
        assert len(players) == 1
        assert players[0] == "Stephen Curry"


# 整合測試
class TestMatchingIntegration:
    """
    整合測試：模擬真實場景
    """
    
    def test_real_world_scenario(self):
        """
        測試真實場景：用戶輸入 vs API 返回的名稱
        """
        # API 返回的球員列表
        api_players = [
            "Stephen Curry",
            "Seth Curry",
            "LeBron James",
            "Anthony Davis",
            "D'Angelo Russell",
            "P.J. Washington",
            "Shai Gilgeous-Alexander"
        ]
        
        # 各種用戶輸入測試
        test_cases = [
            ("Stephen Curry", "Stephen Curry"),
            ("stephen curry", "Stephen Curry"),
            ("steph curry", "Stephen Curry"),  # 暱稱
            ("LEBRON JAMES", "LeBron James"),
            ("dangelo russell", "D'Angelo Russell"),  # 沒有單引號
            ("pj washington", "P.J. Washington"),  # 沒有句點
        ]
        
        for user_input, expected in test_cases:
            result = find_player(user_input, api_players, threshold=80)
            assert result == expected, f"Failed for input '{user_input}'"

