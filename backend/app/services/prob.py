"""
prob.py - 機率計算模組

包含所有與賠率轉換、去水計算相關的數學函數
這是核心計算邏輯，用於將博彩公司賠率轉換為公平機率
"""

from typing import Tuple, List, Optional


def american_to_prob(odds: float) -> float:
    """
    將美式賠率（American Odds）轉換為隱含機率（Implied Probability）
    
    美式賠率有兩種形式：
    - 負數（如 -110）：表示要贏 $100 需要下注多少
    - 正數（如 +150）：表示下注 $100 可以贏多少
    
    轉換公式：
    - 若 odds < 0（負數，如 -110）：p = |odds| / (|odds| + 100)
      例如 -110: p = 110 / (110 + 100) = 110 / 210 ≈ 0.5238
      
    - 若 odds > 0（正數，如 +150）：p = 100 / (odds + 100)
      例如 +150: p = 100 / (150 + 100) = 100 / 250 = 0.4
    
    Args:
        odds: 美式賠率（可為正或負）
    
    Returns:
        隱含機率（0 到 1 之間的浮點數）
    
    Raises:
        ValueError: 當賠率為 0 時（無效賠率）
    """
    if odds == 0:
        raise ValueError("賠率不能為 0")
    
    if odds < 0:
        # 負數賠率：favorite（熱門）
        # 公式：p = A / (A + 100)，其中 A = |odds|
        return abs(odds) / (abs(odds) + 100)
    else:
        # 正數賠率：underdog（冷門）
        # 公式：p = 100 / (B + 100)，其中 B = odds
        return 100 / (odds + 100)


def calculate_vig(p_over: float, p_under: float) -> float:
    """
    計算水錢（Vig / Vigorish / Juice）
    
    水錢是博彩公司的利潤來源。理論上 Over 和 Under 的機率應該加起來等於 1，
    但博彩公司會讓兩者相加超過 1，超出的部分就是水錢。
    
    公式：vig = (p_over_implied + p_under_implied) - 1
    
    例如：
    - Over: -110 → p = 0.5238
    - Under: -110 → p = 0.5238
    - vig = 0.5238 + 0.5238 - 1 = 0.0476（約 4.76%）
    
    Args:
        p_over: Over 的隱含機率
        p_under: Under 的隱含機率
    
    Returns:
        水錢比例（通常為正數，越小越好）
    """
    return (p_over + p_under) - 1


def devig(p_over: float, p_under: float) -> Tuple[float, float]:
    """
    去水計算：將含水的隱含機率轉換為公平機率
    
    原理：將 Over 和 Under 的機率正規化（normalize），使其加起來等於 1
    
    公式：
    - p_over_fair = p_over / (p_over + p_under)
    - p_under_fair = p_under / (p_over + p_under)
    
    這樣可以去除博彩公司加入的水錢，得到更接近真實的機率
    
    例如：
    - p_over = 0.5238, p_under = 0.5238
    - total = 0.5238 + 0.5238 = 1.0476
    - p_over_fair = 0.5238 / 1.0476 = 0.5（50%）
    - p_under_fair = 0.5238 / 1.0476 = 0.5（50%）
    
    Args:
        p_over: Over 的隱含機率（含水）
        p_under: Under 的隱含機率（含水）
    
    Returns:
        Tuple[float, float]: (p_over_fair, p_under_fair) 去水後的公平機率
    
    Raises:
        ValueError: 當兩個機率相加為 0 時（無法計算）
    """
    total = p_over + p_under
    
    if total == 0:
        raise ValueError("機率總和不能為 0")
    
    p_over_fair = p_over / total
    p_under_fair = p_under / total
    
    return (p_over_fair, p_under_fair)


def calculate_consensus_mean(fair_probs: List[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    """
    計算市場共識（平均法）
    
    將多家博彩公司的去水機率取簡單平均，得出市場共識
    這是 MVP 階段使用的方法，簡單但有效
    
    Args:
        fair_probs: 各博彩公司的去水機率列表，每個元素為 (p_over_fair, p_under_fair)
    
    Returns:
        Optional[Tuple[float, float]]: (consensus_over, consensus_under) 共識機率
        如果列表為空則返回 None
    
    Example:
        >>> probs = [(0.51, 0.49), (0.52, 0.48), (0.50, 0.50)]
        >>> calculate_consensus_mean(probs)
        (0.51, 0.49)
    """
    if not fair_probs:
        return None
    
    n = len(fair_probs)
    sum_over = sum(p[0] for p in fair_probs)
    sum_under = sum(p[1] for p in fair_probs)
    
    return (sum_over / n, sum_under / n)


def calculate_consensus_weighted(
    fair_probs: List[Tuple[float, float]], 
    vigs: List[float],
    eps: float = 0.001
) -> Optional[Tuple[float, float]]:
    """
    計算市場共識（加權法）- Phase 2 功能
    
    水錢越低的博彩公司，其賠率越接近真實機率，因此給予較高權重
    
    權重公式：w_i = 1 / max(vig_i, eps)
    - vig 越低 → 權重越高
    - eps 防止除以 0
    
    加權平均：p = Σ(w_i × p_i) / Σ(w_i)
    
    Args:
        fair_probs: 各博彩公司的去水機率列表
        vigs: 對應的水錢列表
        eps: 最小水錢值（防止除以 0）
    
    Returns:
        Optional[Tuple[float, float]]: 加權共識機率
    """
    if not fair_probs or len(fair_probs) != len(vigs):
        return None
    
    # 計算每個 bookmaker 的權重（vig 越低權重越高）
    weights = [1 / max(vig, eps) for vig in vigs]
    total_weight = sum(weights)
    
    if total_weight == 0:
        return None
    
    # 加權平均
    weighted_over = sum(w * p[0] for w, p in zip(weights, fair_probs))
    weighted_under = sum(w * p[1] for w, p in zip(weights, fair_probs))
    
    return (weighted_over / total_weight, weighted_under / total_weight)

