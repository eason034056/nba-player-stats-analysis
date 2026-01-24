"""
normalize.py - 球員名稱正規化與匹配模組

處理球員名稱的標準化和模糊匹配
由於不同資料源的球員名稱可能有差異（如 "Stephen Curry" vs "S. Curry"），
需要透過正規化和模糊匹配來找到正確的球員
"""

import re
from typing import List, Optional, Tuple


def normalize_name(name: str) -> str:
    """
    正規化球員名稱
    
    執行以下處理：
    1. 去除前後空白（strip）
    2. 轉換為小寫（lower）
    3. 移除特殊符號：句點(.)、單引號(')、連字號(-)
    4. 將多個空白合併為一個
    
    這樣可以讓 "Stephen Curry" 和 "stephen curry" 匹配
    也可以讓 "D'Angelo Russell" 和 "dangelo russell" 匹配
    
    Args:
        name: 原始球員名稱
    
    Returns:
        正規化後的名稱
    
    Example:
        >>> normalize_name("  Stephen Curry  ")
        "stephen curry"
        >>> normalize_name("D'Angelo Russell")
        "dangelo russell"
        >>> normalize_name("P.J. Washington")
        "pj washington"
    """
    # 去除前後空白
    normalized = name.strip()
    
    # 轉小寫
    normalized = normalized.lower()
    
    # 移除特殊符號：. ' -
    normalized = re.sub(r"[.'\-]", "", normalized)
    
    # 多個空白合併為一個
    normalized = re.sub(r"\s+", " ", normalized)
    
    return normalized


def exact_match(query: str, candidates: List[str]) -> Optional[str]:
    """
    精確匹配：在候選列表中尋找與查詢完全相同的名稱
    
    先將查詢和所有候選者正規化後比對
    
    Args:
        query: 查詢的球員名稱
        candidates: 候選球員名稱列表
    
    Returns:
        匹配到的原始名稱（非正規化），找不到則返回 None
    
    Example:
        >>> exact_match("stephen curry", ["Stephen Curry", "Seth Curry"])
        "Stephen Curry"
    """
    normalized_query = normalize_name(query)
    
    for candidate in candidates:
        if normalize_name(candidate) == normalized_query:
            return candidate
    
    return None


def fuzzy_match(
    query: str, 
    candidates: List[str], 
    threshold: int = 90
) -> Optional[Tuple[str, int]]:
    """
    模糊匹配：使用字串相似度演算法找出最相似的名稱
    
    使用 rapidfuzz 套件（如果可用）進行模糊匹配
    如果 rapidfuzz 不可用，則退回到簡單的包含匹配
    
    門檻值（threshold）越高，匹配越嚴格：
    - 100: 完全相同
    - 90: 非常相似（建議值）
    - 80: 相似
    - 70: 有點相似
    
    Args:
        query: 查詢的球員名稱
        candidates: 候選球員名稱列表
        threshold: 相似度門檻（0-100）
    
    Returns:
        Tuple[str, int]: (匹配到的原始名稱, 相似度分數)
        找不到符合門檻的則返回 None
    
    Example:
        >>> fuzzy_match("Steph Curry", ["Stephen Curry", "Seth Curry"])
        ("Stephen Curry", 92)
    """
    try:
        from rapidfuzz import fuzz, process
        
        normalized_query = normalize_name(query)
        
        # 建立正規化名稱到原始名稱的映射
        normalized_candidates = {normalize_name(c): c for c in candidates}
        
        # 使用 rapidfuzz 找出最佳匹配
        result = process.extractOne(
            normalized_query,
            list(normalized_candidates.keys()),
            scorer=fuzz.ratio  # 使用 ratio 演算法計算相似度
        )
        
        if result and result[1] >= threshold:
            # result 格式: (matched_string, score, index)
            matched_normalized = result[0]
            score = result[1]
            original_name = normalized_candidates[matched_normalized]
            return (original_name, score)
        
        return None
        
    except ImportError:
        # rapidfuzz 不可用時的備用方案：簡單的包含匹配
        return _simple_fuzzy_match(query, candidates, threshold)


def _simple_fuzzy_match(
    query: str, 
    candidates: List[str], 
    threshold: int = 90
) -> Optional[Tuple[str, int]]:
    """
    簡單的模糊匹配（備用方案）
    
    當 rapidfuzz 不可用時使用
    基於字串包含關係進行匹配
    
    Args:
        query: 查詢的球員名稱
        candidates: 候選球員名稱列表
        threshold: 相似度門檻（這裡簡化處理）
    
    Returns:
        匹配結果或 None
    """
    normalized_query = normalize_name(query)
    query_parts = normalized_query.split()
    
    best_match = None
    best_score = 0
    
    for candidate in candidates:
        normalized_candidate = normalize_name(candidate)
        
        # 計算匹配的單詞數量
        candidate_parts = normalized_candidate.split()
        matching_parts = sum(
            1 for qp in query_parts 
            if any(qp in cp or cp in qp for cp in candidate_parts)
        )
        
        # 簡單的相似度分數計算
        if query_parts:
            score = (matching_parts / len(query_parts)) * 100
        else:
            score = 0
        
        if score > best_score:
            best_score = score
            best_match = candidate
    
    if best_match and best_score >= threshold:
        return (best_match, int(best_score))
    
    return None


def find_player(query: str, candidates: List[str], threshold: int = 90) -> Optional[str]:
    """
    主要的球員名稱匹配函數
    
    匹配策略（按優先順序）：
    1. 先嘗試精確匹配（正規化後完全相同）
    2. 若精確匹配失敗，嘗試模糊匹配
    
    Args:
        query: 使用者輸入的球員名稱
        candidates: 從 API 取得的球員名稱列表
        threshold: 模糊匹配的門檻值（預設 90）
    
    Returns:
        匹配到的球員原始名稱，找不到則返回 None
    
    Example:
        >>> find_player("curry", ["Stephen Curry", "Seth Curry", "LeBron James"])
        None  # 太模糊，無法確定
        >>> find_player("stephen curry", ["Stephen Curry", "Seth Curry"])
        "Stephen Curry"
    """
    # 1. 嘗試精確匹配
    exact = exact_match(query, candidates)
    if exact:
        return exact
    
    # 2. 嘗試模糊匹配
    fuzzy = fuzzy_match(query, candidates, threshold)
    if fuzzy:
        return fuzzy[0]
    
    return None


def extract_player_names(outcomes: List[dict]) -> List[str]:
    """
    從 Odds API 的 outcomes 資料中提取所有球員名稱
    
    outcomes 是 The Odds API 返回的投注選項列表
    每個 outcome 通常包含 "description" 或 "name" 欄位，內含球員名稱
    
    Args:
        outcomes: Odds API 返回的 outcomes 列表
    
    Returns:
        去重後的球員名稱列表
    
    Example:
        >>> outcomes = [
        ...     {"name": "Over", "description": "Stephen Curry"},
        ...     {"name": "Under", "description": "Stephen Curry"},
        ...     {"name": "Over", "description": "LeBron James"}
        ... ]
        >>> extract_player_names(outcomes)
        ["Stephen Curry", "LeBron James"]
    """
    players = set()
    
    for outcome in outcomes:
        # 嘗試從 description 欄位取得球員名稱
        if "description" in outcome and outcome["description"]:
            players.add(outcome["description"])
        # 某些 API 可能使用其他欄位名稱
        elif "player" in outcome and outcome["player"]:
            players.add(outcome["player"])
    
    return list(players)

