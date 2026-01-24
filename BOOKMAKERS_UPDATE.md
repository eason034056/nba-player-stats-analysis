# 博彩公司列表更新說明

## 📋 更新內容

已將博彩公司列表從 **8 家** 擴充至 **30 家**，涵蓋美國地區所有主流和常見的運彩平台。

---

## ✅ 新增的博彩公司（22 家）

### 主流平台（1 家新增）
- **ESPN Bet** (espnbet)

### 知名線上博彩（1 家新增）
- **Bet365** (bet365)

### 賭場/區域型（5 家新增）
- **Hard Rock Bet** (hardrockbet)
- **Borgata** (borgata)
- **Bally Bet** (bally_bet)
- **SI Sportsbook** (sisportsbook)
- **WynnBet** (wynnbet)

### 其他美國運彩平台（15 家新增）
- **Betfred** (betfred)
- **Betway** (betway)
- **Circa Sports** (circasports)
- **Fliff** (fliff)
- **LiveScore Bet** (livescorebet_us)
- **LowVig.ag** (lowvig)
- **MyBookie** (mybookieag)
- **Bovada** (bovada)
- **BetOnline.ag** (betonlineag)
- **SuperBook** (superbook)
- **TwinSpires** (twinspires)
- **BetPARX** (betparx)
- **FOX Bet** (foxbet)
- **SugarHouse** (sugarhouse)
- **Wind Creek** (windcreek)

---

## 🎨 UI 改進

### 1. 分組顯示
- **主流平台**：最常用的 6 家（DraftKings, FanDuel, BetMGM, Caesars, ESPN Bet, Bet365）
- **其他博彩公司**：剩餘 24 家，可摺疊顯示

### 2. 視覺優化
- 全選按鈕使用琥珀色漸層高亮
- 已選項目使用翡翠綠色勾選標記
- 改用更現代的圓角樣式 (rounded-xl)
- 摺疊展開動畫效果

### 3. 資訊顯示
- 顯示總共可選的博彩公司數量
- 顯示當前已選擇的數量
- 摺疊區塊顯示內含數量

---

## 📝 修改的檔案

1. **`frontend/lib/schemas.ts`**
   - 擴充 `BOOKMAKERS` 常數從 8 家到 30 家
   - 更新註解說明

2. **`frontend/lib/utils.ts`**
   - 擴充 `getBookmakerDisplayName()` 函數
   - 新增所有 30 家博彩公司的顯示名稱映射

3. **`frontend/components/BookmakerSelect.tsx`**
   - 新增分組功能（主流 vs 其他）
   - 實作摺疊展開邏輯
   - 優化 UI 設計和動畫

---

## 🔍 使用方式

### 用戶操作
1. 點擊「選擇全部」可一鍵選擇所有 30 家博彩公司
2. 「主流平台」區塊永遠顯示最常用的 6 家
3. 點擊「其他博彩公司」可展開/收合剩餘的 24 家
4. 個別點擊可選擇/取消選擇特定博彩公司

### 預設行為
- 預設狀態：全選（空陣列 `[]`）
- API 會查詢所有可用的博彩公司
- 用戶可以自由選擇特定的博彩公司組合

---

## ⚠️ 注意事項

### API 可用性
並非所有 30 家博彩公司都會為每場比賽提供賠率數據。實際可用的博彩公司取決於：
- The Odds API 的數據來源
- 特定賽事的賠率覆蓋範圍
- 博彩公司是否提供該市場（如 player_points）

### 建議
- 建議用戶選擇「全部」或「主流平台」以獲得最完整的市場共識
- 如果某些博彩公司沒有返回數據，系統會自動跳過
- 結果頁面只顯示有提供賠率的博彩公司

---

## 🚀 後續可優化項目

1. **智能推薦**：根據歷史查詢記錄推薦常用組合
2. **數據標記**：標示哪些博彩公司更常有數據
3. **快速選擇**：預設組合按鈕（如「主流五大」「低水專區」）
4. **搜尋功能**：當列表更長時可新增搜尋框
5. **記住選擇**：使用 localStorage 記住用戶的偏好設定

---

**更新日期**：2026-01-20  
**版本**：v1.1

