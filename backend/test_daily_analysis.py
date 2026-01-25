"""
test_daily_analysis.py - 手動測試每日分析功能

使用方式：
    python test_daily_analysis.py

這個腳本會：
1. 直接呼叫 daily_analysis_service 執行分析
2. 顯示分析結果
3. 不需要啟動 FastAPI 服務
"""

import asyncio
from datetime import datetime, timezone
from app.services.daily_analysis import daily_analysis_service


async def main():
    """
    主函數 - 執行每日分析
    """
    print("=" * 60)
    print("🚀 手動執行每日分析")
    print("=" * 60)
    print()
    
    # 執行分析（使用今天的日期）
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"📅 分析日期: {today}")
    print()
    
    try:
        # 執行分析（不使用快取，強制重新分析）
        # 使用 UTC+8（台北時間）
        result = await daily_analysis_service.run_daily_analysis(
            date=today,
            use_cache=False,
            tz_offset_minutes=480  # UTC+8
        )
        
        # 顯示結果
        print()
        print("=" * 60)
        print("✅ 分析完成！")
        print("=" * 60)
        print()
        print(f"📊 分析結果：")
        print(f"   日期: {result.date}")
        print(f"   分析時間: {result.analyzed_at}")
        print(f"   高機率選擇: {result.total_picks} 個")
        print()
        
        if result.stats:
            print(f"📈 統計資訊：")
            print(f"   分析賽事: {result.stats.total_events} 場")
            print(f"   分析球員: {result.stats.total_players} 人")
            print(f"   分析 Props: {result.stats.total_props} 個")
            print(f"   高機率數量: {result.stats.high_prob_count} 個")
            print(f"   耗時: {result.stats.analysis_duration_seconds:.2f} 秒")
            print()
        
        if result.picks:
            print(f"🎯 高機率選擇（前 10 個）：")
            print()
            for i, pick in enumerate(result.picks[:10], 1):
                print(f"   {i}. {pick.player_name}")
                print(f"      {pick.away_team} @ {pick.home_team}")
                print(f"      {pick.metric} {pick.direction} {pick.threshold}")
                print(f"      機率: {pick.probability:.1%} ({pick.n_games} 場樣本)")
                print()
        else:
            print("⚠️ 沒有找到高機率選擇")
            if result.message:
                print(f"   訊息: {result.message}")
        
    except Exception as e:
        print()
        print("=" * 60)
        print("❌ 分析失敗")
        print("=" * 60)
        print()
        print(f"錯誤訊息: {e}")
        print()
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 執行 async 主函數
    asyncio.run(main())

