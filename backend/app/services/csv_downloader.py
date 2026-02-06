"""
csv_downloader.py - CSV 自動下載服務

從 GitHub 下載 NBA 球員比賽記錄 CSV 文件

功能：
- 從指定的 GitHub repo 下載 raw CSV 文件
- 儲存到 data/nba_player_game_logs.csv
- 下載完成後自動重新載入記憶體快取
- 支援錯誤處理和重試

GitHub URL 格式說明：
- 原始 URL: https://github.com/eason034056/nba-player-stats-scraper/blob/main/nba_player_game_logs.csv
- Raw URL:  https://raw.githubusercontent.com/eason034056/nba-player-stats-scraper/main/nba_player_game_logs.csv
- 使用 raw.githubusercontent.com 才能直接下載文件內容

快取更新策略：
- 下載完成後自動呼叫 csv_player_service.reload() 重新載入記憶體快取
- 可選：清除 Redis 中的每日分析快取（如果需要）
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

# 使用 TYPE_CHECKING 避免循環引入
# 這個 import 只在類型檢查時執行，實際運行時不會執行
if TYPE_CHECKING:
    from app.services.csv_player_history import CSVPlayerHistoryService

# GitHub raw 文件 URL
# raw.githubusercontent.com 是 GitHub 提供的原始文件存取服務
# 格式: https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}
GITHUB_RAW_URL = "https://raw.githubusercontent.com/eason034056/nba-player-stats-scraper/main/nba_player_game_logs.csv"


def _get_csv_save_path() -> Path:
    """
    取得 CSV 儲存路徑
    
    與 csv_player_history.py 使用相同的路徑邏輯，確保一致性
    
    優先順序：
    1. 環境變數 CSV_DATA_PATH
    2. /app/data/nba_player_game_logs.csv（Docker 環境）
    3. 相對於專案根目錄的 data/nba_player_game_logs.csv（本地開發）
    
    Returns:
        Path: CSV 儲存路徑
    """
    import os
    
    # 1. 優先使用環境變數
    env_path = os.environ.get("CSV_DATA_PATH")
    if env_path:
        return Path(env_path)
    
    # 2. Docker 環境路徑（/app/data/）
    # 這是 docker-compose.yml 中掛載的路徑
    docker_path = Path("/app/data/nba_player_game_logs.csv")
    if docker_path.parent.exists():
        return docker_path
    
    # 3. 本地開發路徑（相對於專案根目錄）
    # Path(__file__): csv_downloader.py 的絕對路徑
    # .parent (1): services/
    # .parent (2): app/
    # .parent (3): backend/
    # .parent (4): bet/ (專案根目錄)
    local_path = Path(__file__).parent.parent.parent.parent / "data" / "nba_player_game_logs.csv"
    return local_path


# CSV 儲存路徑（使用函數計算，確保與 csv_player_history.py 一致）
CSV_SAVE_PATH = _get_csv_save_path()


class CSVDownloaderService:
    """
    CSV 下載服務
    
    負責從 GitHub 下載最新的 NBA 球員比賽記錄 CSV
    
    使用方式：
        downloader = CSVDownloaderService()
        success = await downloader.download()
    
    屬性：
        url (str): GitHub raw 文件的 URL
        save_path (Path): CSV 儲存的本地路徑
    """
    
    def __init__(
        self, 
        url: str = GITHUB_RAW_URL, 
        save_path: Path = CSV_SAVE_PATH
    ):
        """
        初始化下載服務
        
        Args:
            url: GitHub raw 文件的 URL，預設為 GITHUB_RAW_URL 常數
            save_path: CSV 儲存的本地路徑，預設為 CSV_SAVE_PATH 常數
        
        為什麼用預設參數？
        - 方便測試時傳入不同的 URL 或路徑
        - 正式使用時不需要傳參數，直接用預設值
        """
        self.url = url
        self.save_path = save_path
    
    async def download(self) -> bool:
        """
        下載 CSV 文件
        
        從 GitHub 下載 CSV 並儲存到本地
        
        Returns:
            bool: 下載成功返回 True，失敗返回 False
        
        流程：
        1. 使用 httpx 發送 GET 請求到 GitHub raw URL
        2. 檢查 HTTP 狀態碼是否成功 (2xx)
        3. 確保目標目錄存在
        4. 將內容寫入本地文件
        
        為什麼用 async？
        - httpx.AsyncClient 是非同步的 HTTP 客戶端
        - 下載大文件時不會阻塞其他任務
        - 與 FastAPI 的 async 架構相容
        """
        print(f"\n📥 開始下載 CSV 文件...")
        print(f"   來源: {self.url}")
        print(f"   目標: {self.save_path}")
        
        try:
            # httpx.AsyncClient: 非同步 HTTP 客戶端
            # async with: 確保請求完成後自動關閉連線
            # timeout=60.0: 設定 60 秒超時，因為 CSV 文件可能較大
            async with httpx.AsyncClient(timeout=60.0) as client:
                # client.get(): 發送 GET 請求
                # await: 等待非同步操作完成
                response = await client.get(self.url)
                
                # raise_for_status(): 檢查 HTTP 狀態碼
                # 如果狀態碼不是 2xx（成功），會拋出 HTTPStatusError
                # 例如: 404 Not Found, 500 Internal Server Error
                response.raise_for_status()
                
                # response.text: 取得回應內容為字串
                # 這裡是 CSV 文件的完整內容
                content = response.text
                
                # 確保目標目錄存在
                # self.save_path.parent: 取得檔案的父目錄 (data/)
                # mkdir(): 建立目錄
                #   parents=True: 如果父目錄不存在，一併建立
                #   exist_ok=True: 如果目錄已存在，不拋出錯誤
                self.save_path.parent.mkdir(parents=True, exist_ok=True)
                
                # 寫入檔案
                # write_text(): Path 物件的方法，直接寫入文字內容
                # encoding='utf-8': 使用 UTF-8 編碼，支援中文等特殊字元
                self.save_path.write_text(content, encoding='utf-8')
                
                # 取得檔案大小用於日誌
                # stat(): 取得檔案狀態資訊
                # st_size: 檔案大小（位元組）
                file_size = self.save_path.stat().st_size
                file_size_mb = file_size / (1024 * 1024)  # 位元組轉 MB
                
                print(f"✅ CSV 下載成功！")
                print(f"   檔案大小: {file_size_mb:.2f} MB")
                print(f"   下載時間: {datetime.now(timezone.utc).isoformat()}")
                
                # 重新載入記憶體快取
                # 這樣前端的請求就會使用最新的 CSV 資料
                await self._reload_csv_cache()
                
                return True
                
        except httpx.HTTPStatusError as e:
            # HTTP 狀態碼錯誤
            # e.response.status_code: 錯誤的狀態碼
            print(f"❌ HTTP 錯誤: {e.response.status_code}")
            print(f"   URL: {self.url}")
            return False
            
        except httpx.RequestError as e:
            # 網路請求錯誤（連線超時、DNS 解析失敗等）
            print(f"❌ 網路請求錯誤: {e}")
            return False
            
        except Exception as e:
            # 其他錯誤（檔案寫入失敗等）
            print(f"❌ 下載失敗: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_last_modified(self) -> str | None:
        """
        取得本地 CSV 的最後修改時間
        
        Returns:
            最後修改時間的 ISO 格式字串，或 None（如果檔案不存在）
        
        用途：
        - 檢查本地文件是否需要更新
        - 在 API 中顯示資料更新時間
        """
        if not self.save_path.exists():
            return None
        
        # stat().st_mtime: 檔案最後修改的 Unix 時間戳
        # fromtimestamp(): 將時間戳轉換為 datetime 物件
        # isoformat(): 轉換為 ISO 8601 格式字串
        mtime = self.save_path.stat().st_mtime
        return datetime.fromtimestamp(mtime, timezone.utc).isoformat()
    
    async def _reload_csv_cache(self) -> None:
        """
        重新載入 CSV 記憶體快取並清除相關 Redis 快取
        
        下載新的 CSV 後，需要：
        1. 重新載入記憶體快取（csv_player_service）
        2. 清除 Redis 中的每日分析快取（daily_picks:*）
        
        這樣前端的請求就會使用最新的資料
        
        為什麼用延遲 import？
        - 避免循環引入（csv_downloader -> csv_player_history -> csv_downloader）
        - 只在真正需要時才 import
        """
        # ===== 1. 重新載入記憶體快取 =====
        try:
            # 延遲 import，避免循環引入
            # csv_player_service 是在模組層級建立的單例
            from app.services.csv_player_history import csv_player_service
            
            # 重新載入 CSV 到記憶體
            # reload() 會清除舊的快取並重新讀取 CSV 檔案
            csv_player_service.reload()
            print("🔄 記憶體快取已更新")
            
        except Exception as e:
            # 快取更新失敗不應該影響下載結果
            print(f"⚠️ 重新載入記憶體快取失敗: {e}")
            import traceback
            traceback.print_exc()
        
        # ===== 2. 清除 Redis 快取 =====
        try:
            from app.services.cache import cache_service
            
            # 清除每日精選快取
            # 這樣下次請求 /api/daily-picks 會重新分析
            deleted = await cache_service.clear_daily_picks_cache()
            
            if deleted > 0:
                print(f"🗑️ 已清除 {deleted} 個 Redis 快取")
            else:
                print("ℹ️ 沒有需要清除的 Redis 快取")
            
            print("✅ 所有快取已更新，前端請求將使用最新資料")
            
        except Exception as e:
            # Redis 快取清除失敗不影響主要功能
            print(f"⚠️ 清除 Redis 快取失敗: {e}")


# 建立全域服務實例
# 這樣其他模組可以直接 import csv_downloader_service 使用
# 不需要每次都建立新的實例
csv_downloader_service = CSVDownloaderService()
