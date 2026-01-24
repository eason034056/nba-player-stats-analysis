# No-Vig NBA 🏀

NBA 球員得分 Props「去水機率」計算網站

## 功能

- 📅 查看 NBA 每日賽事
- 🎯 計算球員得分 Props 的去水機率
- 📊 比較多家博彩公司的賠率
- 📈 顯示市場共識機率

## 技術棧

### 後端 (Python)
- **FastAPI** - 現代化的 Web 框架
- **Redis** - 快取服務
- **Pydantic** - 資料驗證
- **HTTPX** - HTTP 客戶端
- **RapidFuzz** - 模糊字串匹配

### 前端 (TypeScript)
- **Next.js 14** - React 框架
- **TanStack Query** - 資料管理
- **Tailwind CSS** - 樣式框架
- **react-hook-form** - 表單處理
- **Zod** - 資料驗證

## 快速開始

### 前置需求

- Docker & Docker Compose
- Node.js 18+ (前端開發用)
- Python 3.11+ (後端開發用)
- The Odds API 金鑰 ([註冊](https://the-odds-api.com/))

### 使用 Docker Compose 啟動

1. **複製環境變數檔案**

```bash
cp env.example .env
```

2. **編輯 .env 填入 API 金鑰**

```bash
# 編輯 .env 檔案，填入你的 Odds API 金鑰
# 可在 https://the-odds-api.com/ 註冊取得免費金鑰
ODDS_API_KEY=your_api_key_here
```

3. **（可選）設定前端環境變數**

```bash
# 在 frontend 目錄建立 .env.local
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > frontend/.env.local
```

4. **啟動服務**

```bash
# 啟動後端 + Redis
docker-compose up -d

# 查看日誌
docker-compose logs -f backend
```

5. **啟動前端（開發模式）**

```bash
cd frontend
npm install
npm run dev
```

6. **開啟瀏覽器**

- 前端：http://localhost:3000
- 後端 API：http://localhost:8000
- API 文件：http://localhost:8000/docs

### 本地開發（不使用 Docker）

#### 後端

```bash
cd backend

# 建立虛擬環境
python -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate   # Windows

# 安裝依賴
pip install -r requirements.txt

# 啟動 Redis（需要本地安裝）
redis-server

# 啟動後端
uvicorn app.main:app --reload
```

#### 前端

```bash
cd frontend

# 安裝依賴
npm install

# 啟動開發伺服器
npm run dev
```

## API 端點

| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/api/health` | 健康檢查 |
| GET | `/api/nba/events` | 取得賽事列表 |
| POST | `/api/nba/props/no-vig` | 計算去水機率 |
| GET | `/api/nba/players/suggest` | 球員名稱建議 |

詳細 API 文件請參考：http://localhost:8000/docs

## 專案結構

```
.
├── backend/                 # 後端 FastAPI
│   ├── app/
│   │   ├── api/            # API 路由
│   │   ├── models/         # Pydantic 模型
│   │   ├── services/       # 業務邏輯
│   │   ├── main.py         # 應用入口
│   │   └── settings.py     # 設定
│   ├── tests/              # 單元測試
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/               # 前端 Next.js
│   ├── app/               # 頁面
│   ├── components/        # 元件
│   ├── lib/               # 工具函數
│   ├── package.json
│   └── tailwind.config.ts
│
├── docker-compose.yml      # Docker Compose 配置
├── .env.example           # 環境變數範例
└── README.md
```

## 測試

### 後端測試

```bash
cd backend
pytest
```

### 測試內容

- `test_prob.py` - 機率計算測試
- `test_matching.py` - 球員名稱匹配測試

## 計算說明

### 美式賠率轉機率

```
若 odds < 0: p = |odds| / (|odds| + 100)
若 odds > 0: p = 100 / (odds + 100)
```

### 去水計算

```
p_fair = p_implied / (p_over + p_under)
```

### 市場共識

```
consensus = mean(p_fair) across all bookmakers
```

## 免責聲明

⚠️ 本站為資訊與數據分析用途，不構成投注建議。

- 賠率資料可能有延遲或缺漏
- 請以官方來源為準
- 請根據當地法律合法使用博彩服務

## 授權

MIT License

