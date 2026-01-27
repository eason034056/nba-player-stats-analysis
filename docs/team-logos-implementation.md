# NBA 球隊 Logo 實作文件

## 概述

已將所有籃球 emoji (🏀) 替換為 NBA 球隊的官方 logo。Logo 來源為 ESPN CDN，提供高解析度的球隊標誌。

---

## 修改的檔案

### 1. **新增檔案**

#### `frontend/lib/team-logos.ts`
**用途：** 球隊名稱到 Logo URL 的映射工具

**功能：**
- `getTeamLogo(teamName: string)`: 根據球隊全名返回 ESPN CDN 的 logo URL
- `getAllTeamNames()`: 取得所有支援的球隊名稱列表
- `isValidTeamName(teamName: string)`: 檢查球隊名稱是否有效

**包含球隊：**
- 所有 30 支 NBA 球隊
- 支援完整球隊名稱（如 "Los Angeles Lakers", "Boston Celtics"）
- 自動映射到球隊縮寫（如 LAL, BOS）

**Logo URL 格式：**
```
https://a.espncdn.com/i/teamlogos/nba/500/{TEAM_ABBREVIATION}.png
```

#### `frontend/components/TeamLogo.tsx`
**用途：** 可重用的球隊 Logo React 元件

**Props：**
- `teamName` (string, 必填): 球隊全名
- `size` (number, 預設 24): Logo 尺寸（px）
- `className` (string, 可選): 額外的 CSS class
- `priority` (boolean, 預設 false): 是否優先載入

**特點：**
- 使用 Next.js Image 元件優化
- 自動處理圖片載入失敗
- 支援自訂樣式

---

### 2. **修改的檔案**

#### `frontend/next.config.js`
**修改內容：**
```javascript
images: {
  remotePatterns: [
    {
      protocol: "https",
      hostname: "a.espncdn.com",
      port: "",
      pathname: "/i/teamlogos/**",
    },
  ],
},
```
**原因：** 允許 Next.js 從 ESPN CDN 載入外部圖片

---

#### `frontend/components/EventList.tsx`
**修改內容：**
1. **匯入：** 新增 `TeamLogo` 元件和 `CalendarOff` icon
2. **客隊 logo：** 將籃球 emoji 替換為 `<TeamLogo teamName={event.away_team} size={40} />`
3. **主隊 logo：** 將籃球 emoji 替換為 `<TeamLogo teamName={event.home_team} size={40} />`
4. **空狀態：** 將大籃球 emoji 替換為 `<CalendarOff>` icon

**效果：**
- 賽事列表中顯示球隊官方 logo
- hover 時 logo 會放大（scale-110）
- 視覺效果更專業

---

#### `frontend/components/Navbar.tsx`
**修改內容：**
1. **匯入：** 新增 `Sparkles` icon
2. **Logo：** 將籃球 emoji 替換為 `<Sparkles>` icon

**原因：** 導航欄的 logo 代表整個網站，使用閃電 icon 更符合「No-Vig」品牌形象

---

#### `frontend/app/event/[eventId]/page.tsx`
**修改內容：**
1. **匯入：** 新增 `TeamLogo` 元件
2. **賽事標題：** 重新設計標題區域
   - 原本：`🏀 Lakers @ Warriors`
   - 現在：`[Lakers Logo] Lakers @ [Warriors Logo] Warriors`

**新的佈局：**
```tsx
<div className="flex items-center gap-4">
  <div className="flex items-center gap-3">
    <TeamLogo teamName={away_team} size={40} />
    <span>{away_team}</span>
  </div>
  <span>@</span>
  <div className="flex items-center gap-3">
    <TeamLogo teamName={home_team} size={40} />
    <span>{home_team}</span>
  </div>
</div>
```

---

#### `frontend/app/picks/page.tsx`
**修改內容：**
1. **匯入：** 新增 `TeamLogo` 元件
2. **精選卡片：** 重新設計球員卡片的球隊顯示
   - 原本：單一籃球 emoji
   - 現在：並排顯示客隊和主隊 logo

**新的佈局：**
```tsx
<div className="flex items-center gap-2">
  <TeamLogo teamName={pick.away_team} size={28} className="opacity-80" />
  <span className="text-slate-600">@</span>
  <TeamLogo teamName={pick.home_team} size={28} className="opacity-80" />
</div>
```

---

## 球隊縮寫對照表

### 東區

**大西洋組**
- Boston Celtics → BOS
- Brooklyn Nets → BKN
- New York Knicks → NY
- Philadelphia 76ers → PHI
- Toronto Raptors → TOR

**中央組**
- Chicago Bulls → CHI
- Cleveland Cavaliers → CLE
- Detroit Pistons → DET
- Indiana Pacers → IND
- Milwaukee Bucks → MIL

**東南組**
- Atlanta Hawks → ATL
- Charlotte Hornets → CHA
- Miami Heat → MIA
- Orlando Magic → ORL
- Washington Wizards → WSH

### 西區

**西南組**
- Dallas Mavericks → DAL
- Houston Rockets → HOU
- Memphis Grizzlies → MEM
- New Orleans Pelicans → NO
- San Antonio Spurs → SA

**西北組**
- Denver Nuggets → DEN
- Minnesota Timberwolves → MIN
- Oklahoma City Thunder → OKC
- Portland Trail Blazers → POR
- Utah Jazz → UTA

**太平洋組**
- Golden State Warriors → GS
- LA Clippers / Los Angeles Clippers → LAC
- Los Angeles Lakers → LAL
- Phoenix Suns → PHX
- Sacramento Kings → SAC

---

## 使用範例

### 基本用法
```tsx
import { TeamLogo } from "@/components/TeamLogo";

<TeamLogo teamName="Los Angeles Lakers" size={32} />
```

### 自訂樣式
```tsx
<TeamLogo 
  teamName="Boston Celtics" 
  size={48} 
  className="rounded-full shadow-lg hover:scale-110 transition-transform"
/>
```

### 優先載入（LCP 優化）
```tsx
<TeamLogo 
  teamName="Golden State Warriors" 
  size={64} 
  priority={true}
/>
```

---

## 技術細節

### CDN 選擇
選擇 ESPN CDN 的原因：
1. **穩定性：** ESPN 是官方合作夥伴，CDN 穩定可靠
2. **高解析度：** 提供 500x500 高解析度版本
3. **免費：** 無需 API key，直接使用
4. **無 CORS 限制：** 支援跨域請求

### 效能優化
1. **Next.js Image：** 自動優化圖片載入
2. **`unoptimized` 標記：** ESPN CDN 已優化，無需二次處理
3. **尺寸控制：** 根據使用場景選擇適當尺寸
4. **lazy loading：** 預設延遲載入（除非設定 `priority`）

### 錯誤處理
- 當找不到球隊時，自動使用預設 NBA logo
- Console 會印出警告訊息，便於除錯
- 不會造成頁面崩潰

---

## 測試建議

### 視覺測試
1. 首頁賽事列表：檢查所有球隊 logo 是否正確顯示
2. 詳細頁面標題：檢查兩支球隊 logo 是否並排顯示
3. 精選頁面卡片：檢查球員卡片的球隊 logo
4. hover 效果：確認 logo 的互動效果

### 功能測試
1. 載入速度：確認圖片載入不影響頁面效能
2. 錯誤處理：測試找不到球隊時的後備方案
3. 響應式：在不同螢幕尺寸下檢查顯示效果

### 球隊名稱測試
確認以下球隊名稱都能正確顯示：
- "Los Angeles Lakers"
- "LA Clippers" 和 "Los Angeles Clippers"（兩種寫法）
- "New York Knicks"
- "Philadelphia 76ers"

---

## 未來改進建議

1. **本地快取：** 考慮將常用 logo 下載到本地，減少外部依賴
2. **WebP 格式：** 使用更現代的圖片格式
3. **多尺寸支援：** 預先載入不同尺寸的 logo
4. **主題顏色：** 根據球隊主題色調整背景或邊框顏色
5. **動態效果：** 添加更多互動動畫（如 3D 旋轉）

---

## 相關資源

- [ESPN CDN](https://a.espncdn.com/)
- [Next.js Image 文件](https://nextjs.org/docs/app/api-reference/components/image)
- [NBA 官網](https://www.nba.com/)

