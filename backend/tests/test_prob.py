"""
test_prob.py - 機率計算模組的單元測試

使用 pytest 框架進行測試
測試內容：
1. 美式賠率轉換為機率
2. 水錢計算
3. 去水機率計算
4. 共識計算
"""

import pytest
import sys
import os

# 將專案根目錄加入 Python 路徑，以便能匯入 app 模組
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.prob import (
    american_to_prob,
    calculate_vig,
    devig,
    calculate_consensus_mean,
    calculate_consensus_weighted
)


class TestAmericanToProb:
    """
    測試美式賠率轉機率函數
    
    american_to_prob 將美式賠率轉換為隱含機率
    """
    
    def test_negative_odds_minus_110(self):
        """
        測試負數賠率 -110
        
        -110 是常見的「標準賠率」
        計算：110 / (110 + 100) = 110 / 210 ≈ 0.5238
        """
        result = american_to_prob(-110)
        # 允許小數點誤差
        assert abs(result - 0.5238) < 0.001
    
    def test_negative_odds_minus_150(self):
        """
        測試負數賠率 -150（較大熱門）
        
        計算：150 / (150 + 100) = 150 / 250 = 0.6
        """
        result = american_to_prob(-150)
        assert abs(result - 0.6) < 0.001
    
    def test_positive_odds_plus_150(self):
        """
        測試正數賠率 +150（冷門）
        
        計算：100 / (150 + 100) = 100 / 250 = 0.4
        """
        result = american_to_prob(150)
        assert abs(result - 0.4) < 0.001
    
    def test_positive_odds_plus_100(self):
        """
        測試正數賠率 +100（平盤）
        
        計算：100 / (100 + 100) = 100 / 200 = 0.5
        """
        result = american_to_prob(100)
        assert abs(result - 0.5) < 0.001
    
    def test_negative_odds_minus_100(self):
        """
        測試負數賠率 -100（平盤）
        
        計算：100 / (100 + 100) = 0.5
        """
        result = american_to_prob(-100)
        assert abs(result - 0.5) < 0.001
    
    def test_zero_odds_raises_error(self):
        """
        測試賠率為 0 時應該拋出例外
        
        美式賠率不能為 0，這是無效值
        """
        with pytest.raises(ValueError, match="賠率不能為 0"):
            american_to_prob(0)
    
    def test_large_negative_odds(self):
        """
        測試極端負數賠率 -1000（大熱門）
        
        計算：1000 / (1000 + 100) = 1000 / 1100 ≈ 0.909
        """
        result = american_to_prob(-1000)
        assert abs(result - 0.909) < 0.01
    
    def test_large_positive_odds(self):
        """
        測試極端正數賠率 +1000（大冷門）
        
        計算：100 / (1000 + 100) = 100 / 1100 ≈ 0.091
        """
        result = american_to_prob(1000)
        assert abs(result - 0.091) < 0.01


class TestCalculateVig:
    """
    測試水錢計算函數
    
    vig = (p_over + p_under) - 1
    水錢代表博彩公司的利潤
    """
    
    def test_standard_vig(self):
        """
        測試標準水錢（-110/-110）
        
        p_over = p_under = 0.5238
        vig = 0.5238 + 0.5238 - 1 = 0.0476（約 4.76%）
        """
        p_over = american_to_prob(-110)
        p_under = american_to_prob(-110)
        vig = calculate_vig(p_over, p_under)
        assert abs(vig - 0.0476) < 0.001
    
    def test_zero_vig(self):
        """
        測試零水錢（理論上的公平市場）
        
        當 p_over + p_under = 1 時，vig = 0
        """
        vig = calculate_vig(0.5, 0.5)
        assert vig == 0
    
    def test_high_vig(self):
        """
        測試高水錢（-130/-130）
        
        p = 130 / 230 ≈ 0.565
        vig = 0.565 + 0.565 - 1 = 0.13（約 13%）
        """
        p_over = american_to_prob(-130)
        p_under = american_to_prob(-130)
        vig = calculate_vig(p_over, p_under)
        assert abs(vig - 0.13) < 0.01
    
    def test_asymmetric_odds(self):
        """
        測試不對稱賠率（-115/-105）
        
        p_over = 115 / 215 ≈ 0.535
        p_under = 105 / 205 ≈ 0.512
        vig ≈ 0.047
        """
        p_over = american_to_prob(-115)
        p_under = american_to_prob(-105)
        vig = calculate_vig(p_over, p_under)
        assert vig > 0


class TestDevig:
    """
    測試去水機率計算函數
    
    去水後 p_over_fair + p_under_fair 應該等於 1
    """
    
    def test_symmetric_odds(self):
        """
        測試對稱賠率去水
        
        -110/-110 去水後應該各為 0.5
        """
        p_over = american_to_prob(-110)
        p_under = american_to_prob(-110)
        
        p_over_fair, p_under_fair = devig(p_over, p_under)
        
        # 去水後應該各為 50%
        assert abs(p_over_fair - 0.5) < 0.001
        assert abs(p_under_fair - 0.5) < 0.001
        # 總和應該等於 1
        assert abs(p_over_fair + p_under_fair - 1.0) < 0.0001
    
    def test_asymmetric_odds(self):
        """
        測試不對稱賠率去水
        
        驗證去水後總和仍為 1
        """
        p_over = american_to_prob(-130)
        p_under = american_to_prob(110)
        
        p_over_fair, p_under_fair = devig(p_over, p_under)
        
        # 總和應該等於 1
        assert abs(p_over_fair + p_under_fair - 1.0) < 0.0001
        # over 應該比 under 高（因為 -130 比 +110 更可能）
        assert p_over_fair > p_under_fair
    
    def test_devig_preserves_ratio(self):
        """
        測試去水保持原始機率比例
        
        去水只是將機率正規化，應該保持 p_over/p_under 的比例
        """
        p_over = 0.6
        p_under = 0.5  # 總和 1.1，有 0.1 的水
        
        p_over_fair, p_under_fair = devig(p_over, p_under)
        
        # 原始比例
        original_ratio = p_over / p_under
        # 去水後比例
        fair_ratio = p_over_fair / p_under_fair
        
        assert abs(original_ratio - fair_ratio) < 0.0001
    
    def test_zero_sum_raises_error(self):
        """
        測試總和為 0 時應該拋出例外
        """
        with pytest.raises(ValueError, match="機率總和不能為 0"):
            devig(0, 0)


class TestConsensusMean:
    """
    測試平均共識計算
    """
    
    def test_single_bookmaker(self):
        """
        測試單一博彩公司（共識就是該博彩公司的機率）
        """
        probs = [(0.52, 0.48)]
        result = calculate_consensus_mean(probs)
        
        assert result is not None
        assert result[0] == 0.52
        assert result[1] == 0.48
    
    def test_multiple_bookmakers(self):
        """
        測試多家博彩公司平均
        """
        probs = [
            (0.50, 0.50),
            (0.52, 0.48),
            (0.54, 0.46)
        ]
        result = calculate_consensus_mean(probs)
        
        assert result is not None
        # 平均：(0.50 + 0.52 + 0.54) / 3 ≈ 0.52
        assert abs(result[0] - 0.52) < 0.001
        # 平均：(0.50 + 0.48 + 0.46) / 3 ≈ 0.48
        assert abs(result[1] - 0.48) < 0.001
    
    def test_empty_list(self):
        """
        測試空列表返回 None
        """
        result = calculate_consensus_mean([])
        assert result is None
    
    def test_consensus_sums_to_one(self):
        """
        測試共識機率總和為 1
        """
        probs = [
            (0.51, 0.49),
            (0.53, 0.47),
            (0.49, 0.51)
        ]
        result = calculate_consensus_mean(probs)
        
        assert result is not None
        assert abs(result[0] + result[1] - 1.0) < 0.0001


class TestConsensusWeighted:
    """
    測試加權共識計算
    """
    
    def test_equal_vigs(self):
        """
        測試相同水錢時，加權等同平均
        """
        probs = [
            (0.50, 0.50),
            (0.52, 0.48),
            (0.54, 0.46)
        ]
        vigs = [0.05, 0.05, 0.05]
        
        weighted = calculate_consensus_weighted(probs, vigs)
        mean = calculate_consensus_mean(probs)
        
        assert weighted is not None
        assert mean is not None
        assert abs(weighted[0] - mean[0]) < 0.001
    
    def test_different_vigs(self):
        """
        測試不同水錢時，低水錢博彩公司權重較高
        """
        probs = [
            (0.50, 0.50),  # 低水（好）
            (0.55, 0.45)   # 高水（差）
        ]
        vigs = [0.02, 0.10]  # 第一家水錢低 5 倍
        
        result = calculate_consensus_weighted(probs, vigs)
        
        assert result is not None
        # 結果應該更接近低水博彩公司的機率
        assert result[0] < 0.525  # 應該更接近 0.50 而非 0.525（平均）
    
    def test_empty_list(self):
        """
        測試空列表返回 None
        """
        result = calculate_consensus_weighted([], [])
        assert result is None
    
    def test_mismatched_lengths(self):
        """
        測試長度不匹配返回 None
        """
        probs = [(0.5, 0.5), (0.5, 0.5)]
        vigs = [0.05]  # 長度不匹配
        
        result = calculate_consensus_weighted(probs, vigs)
        assert result is None


# 整合測試：驗證完整的計算流程
class TestIntegration:
    """
    整合測試：驗證從賠率到去水機率的完整流程
    """
    
    def test_full_calculation_flow(self):
        """
        測試完整計算流程：
        賠率 → 隱含機率 → 水錢 → 去水機率
        """
        # 模擬真實場景：DraftKings 的賠率
        over_odds = -115
        under_odds = -105
        
        # 1. 轉換為隱含機率
        p_over_imp = american_to_prob(over_odds)
        p_under_imp = american_to_prob(under_odds)
        
        # 2. 計算水錢
        vig = calculate_vig(p_over_imp, p_under_imp)
        
        # 3. 去水
        p_over_fair, p_under_fair = devig(p_over_imp, p_under_imp)
        
        # 驗證
        assert p_over_imp > 0.5  # -115 應該 > 50%
        assert p_under_imp > 0.5  # -105 應該 > 50%
        assert vig > 0  # 應該有水錢
        assert abs(p_over_fair + p_under_fair - 1.0) < 0.0001  # 去水後總和 = 1
        assert p_over_fair > p_under_fair  # Over 應該略高（因為 -115 < -105）

