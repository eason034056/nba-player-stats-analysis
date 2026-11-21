# Dockerfile - 後端 FastAPI 應用的 Docker 映像檔
#
# 這個 Dockerfile 定義如何將 FastAPI 應用打包成 Docker 容器
# 
# 建置命令：docker build -t no-vig-nba-backend .
# 運行命令：docker run -p 8000:8000 no-vig-nba-backend

# ==================== 基底映像 ====================
# 使用 Python 3.11 slim 版本作為基底
# - slim: 較小的映像檔大小
# - 3.11: 穩定且效能良好的 Python 版本
FROM python:3.11-slim

# ==================== 環境變數 ====================
# 設定 Python 環境變數
# PYTHONDONTWRITEBYTECODE: 不生成 .pyc 檔案（減少容器大小）
# PYTHONUNBUFFERED: 不緩衝輸出（即時顯示日誌）
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ==================== 工作目錄 ====================
# 設定容器內的工作目錄
# 後續的命令都會在此目錄下執行
WORKDIR /app

# ==================== 系統依賴 ====================
# 安裝系統層級的依賴
# - gcc: 某些 Python 套件需要編譯
# - curl: 健康檢查用
# --no-install-recommends: 不安裝建議套件（減少大小）
# rm -rf /var/lib/apt/lists/*: 清除快取（減少大小）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ==================== Python 依賴 ====================
# 先複製依賴檔案（利用 Docker 快取機制）
# 如果 backend/requirements.txt 沒變，這一層會使用快取
COPY backend/requirements.txt ./requirements.txt

# 安裝 Python 依賴
# --no-cache-dir: 不快取下載的套件（減少映像大小）
RUN pip install --no-cache-dir -r requirements.txt

# ==================== 複製應用程式 ====================
# 複製 backend 應用與資料目錄到容器
COPY backend/ ./
COPY data ./data

# The entrypoint applies migrations before the process becomes uvicorn.
RUN chmod +x /app/docker-entrypoint.sh

# ==================== 暴露端口 ====================
# 聲明容器會使用的端口
# 這只是文件說明，實際端口映射由 docker run -p 決定
EXPOSE 8000

# ==================== 健康檢查 ====================
# 定義如何檢查容器是否健康
# - --interval: 每 30 秒檢查一次
# - --timeout: 檢查超時時間
# - --start-period: 啟動後等待時間
# - --retries: 失敗幾次才標記為不健康
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# ==================== 啟動命令 ====================
# ENTRYPOINT 先跑 migration，再 exec CMD。
# compose 若只換 CMD（例如加上 --proxy-headers），migration 仍會先跑。
# 不要把 ENTRYPOINT 換成一支直接啟動 uvicorn 的命令。
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
