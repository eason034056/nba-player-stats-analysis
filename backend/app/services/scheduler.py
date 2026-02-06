"""
scheduler.py - 定時任務排程器

使用 APScheduler 實現定時任務,自動執行每日分析

APScheduler(Advanced Python Scheduler)是一個輕量級的 Python 定時任務庫
優點:
- 不需要額外的服務(如 Celery + Redis/RabbitMQ)
- 支援多種觸發器(cron、interval、date)
- 適合單機部署

主要功能:
- 每天定時執行每日分析
- 每天自動下載最新的 NBA 球員數據 CSV
- 支援手動觸發
- 錯誤處理和重試

排程策略:
- 每日分析:每天 UTC 12:00(美東 7:00 AM / 台北 20:00)執行
- CSV 下載:每天芝加哥時間 10:00 執行(自動處理夏令/冬令時間)
- NBA 比賽通常在美東晚上,這個時間賠率已經穩定
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.services.daily_analysis import daily_analysis_service
from app.services.csv_downloader import csv_downloader_service


class SchedulerService:
    """
    定時任務排程器服務
    
    管理所有定時任務的啟動、停止和執行
    
    使用方式:
        scheduler = SchedulerService()
        scheduler.start()  # 啟動排程器
        scheduler.stop()   # 停止排程器
    
    定時任務:
    - daily_analysis_job: 每天 UTC 12:00 執行每日分析
    """
    
    def __init__(self):
        """
        初始化排程器
        
        AsyncIOScheduler: 適用於 asyncio 的排程器
        - 可以執行 async 函數
        - 與 FastAPI 的 async 架構相容
        """
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._is_running = False
    
    def start(self):
        """
        啟動排程器
        
        建立 AsyncIOScheduler 並添加定時任務
        
        注意:排程器需要在 asyncio event loop 中運行
        FastAPI 的 lifespan 事件是適合的啟動時機
        """
        if self._is_running:
            print("⚠️ 排程器已經在運行中")
            return
        
        # 建立排程器
        self._scheduler = AsyncIOScheduler(
            timezone="UTC",  # 使用 UTC 時區
            job_defaults={
                'coalesce': True,      # 合併錯過的執行(只執行一次)
                'max_instances': 1,    # 同一任務最多同時執行 1 個實例
                'misfire_grace_time': 3600  # 錯過的任務在 1 小時內仍會執行
            }
        )
        
        # 添加每日分析任務
        # CronTrigger: 類似 Linux cron 的觸發器
        # hour=12, minute=0: 每天 UTC 12:00 執行
        self._scheduler.add_job(
            self._run_daily_analysis_job,
            trigger=CronTrigger(hour=12, minute=0),
            id='daily_analysis_job',
            name='每日高機率球員分析',
            replace_existing=True  # 如果任務已存在,替換它
        )
        
        # 添加 CSV 下載任務
        # 芝加哥時間 10:00 執行
        # timezone="America/Chicago": 指定時區,APScheduler 會自動處理夏令/冬令時間
        # 芝加哥時間 10:00 對應:
        #   - 冬令時間 (CST, UTC-6): UTC 16:00
        #   - 夏令時間 (CDT, UTC-5): UTC 15:00
        self._scheduler.add_job(
            self._run_csv_download_job,
            trigger=CronTrigger(
                hour=10, 
                minute=0, 
                timezone="America/Chicago"
            ),
            id='csv_download_job',
            name='下載 NBA 球員數據 CSV',
            replace_existing=True
        )
        
        # 啟動排程器
        self._scheduler.start()
        self._is_running = True
        
        print("✅ 排程器已啟動")
        print("📅 排程任務:")
        print("   - 每日分析:每天 UTC 12:00")
        print("   - CSV 下載:每天芝加哥時間 10:00")
        
        # 列出所有排程的任務
        jobs = self._scheduler.get_jobs()
        for job in jobs:
            print(f"   📌 {job.id}: {job.name}")
            print(f"      下次執行: {job.next_run_time}")
    
    def stop(self):
        """
        停止排程器
        
        優雅地關閉排程器,等待正在執行的任務完成
        """
        if not self._is_running or self._scheduler is None:
            return
        
        self._scheduler.shutdown(wait=True)
        self._is_running = False
        print("✅ 排程器已停止")
    
    async def _run_daily_analysis_job(self):
        """
        執行每日分析任務
        
        這是排程器呼叫的任務函數
        包含錯誤處理和日誌記錄
        """
        print("\n" + "=" * 50)
        print(f"🚀 開始執行每日分析任務: {datetime.now(timezone.utc).isoformat()}")
        print("=" * 50)
        
        try:
            # 執行今日分析
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            result = await daily_analysis_service.run_daily_analysis(
                date=today,
                use_cache=False  # 定時任務強制重新分析
            )
            
            print(f"\n✅ 每日分析完成!")
            print(f"   日期: {result.date}")
            print(f"   找到 {result.total_picks} 個高機率選擇")
            
            if result.stats:
                print(f"   分析賽事: {result.stats.total_events} 場")
                print(f"   分析球員: {result.stats.total_players} 人")
                print(f"   耗時: {result.stats.analysis_duration_seconds:.2f} 秒")
            
        except Exception as e:
            print(f"\n❌ 每日分析任務失敗: {e}")
            # 這裡可以加入通知機制(如 email、Slack)
            import traceback
            traceback.print_exc()
        
        print("=" * 50 + "\n")
    
    async def _run_csv_download_job(self):
        """
        執行 CSV 下載任務
        
        從 GitHub 下載最新的 NBA 球員比賽記錄 CSV
        這個任務在芝加哥時間每天 10:00 自動執行
        
        流程:
        1. 呼叫 csv_downloader_service.download()
        2. 記錄下載結果(成功/失敗)
        3. 錯誤處理和日誌
        """
        print("\n" + "=" * 50)
        print(f"📥 開始執行 CSV 下載任務: {datetime.now(timezone.utc).isoformat()}")
        print("=" * 50)
        
        try:
            # 呼叫下載服務
            success = await csv_downloader_service.download()
            
            if success:
                print(f"✅ CSV 下載任務完成!")
            else:
                print(f"⚠️ CSV 下載任務失敗,請檢查網路或 URL")
                
        except Exception as e:
            print(f"❌ CSV 下載任務異常: {e}")
            import traceback
            traceback.print_exc()
        
        print("=" * 50 + "\n")
    
    async def trigger_now(self):
        """
        立即觸發每日分析任務
        
        用於手動測試或需要立即更新數據時
        
        Returns:
            分析結果
        """
        return await self._run_daily_analysis_job()
    
    async def trigger_csv_download_now(self) -> bool:
        """
        立即觸發 CSV 下載任務
        
        用於手動測試或需要立即更新數據時
        不需要等到排程時間
        
        Returns:
            bool: 下載是否成功
        
        使用方式:
            success = await scheduler_service.trigger_csv_download_now()
        """
        return await csv_downloader_service.download()
    
    def get_next_run_time(self) -> Optional[str]:
        """
        取得每日分析的下次執行時間
        
        Returns:
            下次執行時間的 ISO 格式字串,或 None
        """
        if not self._scheduler:
            return None
        
        job = self._scheduler.get_job('daily_analysis_job')
        if job and job.next_run_time:
            return job.next_run_time.isoformat()
        return None
    
    def get_csv_download_next_run_time(self) -> Optional[str]:
        """
        取得 CSV 下載的下次執行時間
        
        Returns:
            下次執行時間的 ISO 格式字串,或 None
        """
        if not self._scheduler:
            return None
        
        job = self._scheduler.get_job('csv_download_job')
        if job and job.next_run_time:
            return job.next_run_time.isoformat()
        return None
    
    @property
    def is_running(self) -> bool:
        """檢查排程器是否正在運行"""
        return self._is_running


# 建立全域排程器實例
scheduler_service = SchedulerService()
