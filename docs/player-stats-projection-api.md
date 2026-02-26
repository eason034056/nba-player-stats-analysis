

# SportsDataIO – Projected Player Game Stats (By Date)

**Endpoint**

```
GET https://api.sportsdata.io/v3/nba/projections/json/PlayerGameProjectionStatsByDate/{date}
```

* `{date}`：**比賽日（EST 時區）**，格式 `YYYY-MM-DD`
* 回傳：**該日期所有 NBA 球員的「單場比賽投影資料」**
* 資料來源：SportsDataIO 內部 ML 投影模型
* 用途：Fantasy、DFS、比賽表現預測、建模

---

## 一、基礎識別與賽事資訊（Identity & Game Info）

| 欄位           | 說明                                    |
| ------------ | ------------------------------------- |
| `StatID`     | 該筆投影紀錄的唯一 ID                          |
| `PlayerID`   | SportsDataIO 球員 ID                    |
| `Name`       | 球員姓名                                  |
| `TeamID`     | 球隊 ID                                 |
| `Team`       | 球隊縮寫                                  |
| `Position`   | 球員場上位置（PG / SG / SF / PF / C）         |
| `Season`     | 賽季年份（例如 2026）                         |
| `SeasonType` | 賽季類型（1 = Regular Season，2 = Playoffs） |

---

## 二、比賽對戰資訊（Matchup Info）

| 欄位                 | 說明              |
| ------------------ | --------------- |
| `GameID`           | 本場比賽 ID         |
| `GlobalGameID`     | 全域比賽 ID         |
| `OpponentID`       | 對手球隊 ID         |
| `GlobalOpponentID` | 對手全域 ID         |
| `Opponent`         | 對手球隊縮寫          |
| `HomeOrAway`       | `HOME` / `AWAY` |
| `Day`              | 比賽日期（EST，00:00） |
| `DateTime`         | 比賽實際開打時間（EST）   |
| `IsGameOver`       | 比賽是否已結束         |
| `Updated`          | 此筆投影最後更新時間      |

---

## 三、先發與陣容狀態（Lineup & Role）

| 欄位                | 說明                              |
| ----------------- | ------------------------------- |
| `Started`         | 是否預期為先發（1 = Yes，0 = No）         |
| `LineupConfirmed` | 先發是否已官方確認                       |
| `LineupStatus`    | 先發狀態（Free Trial 會是 `Scrambled`） |

📌 **重點**

* `Started` + `LineupConfirmed` 是你「推估 projected minutes」時非常重要的特徵
* 即使沒有 `ProjectedMinutes` 欄位，這裡就是關鍵訊號

---

## 四、傷病資訊（Injury Info）

| 欄位                | 說明                           |
| ----------------- | ---------------------------- |
| `InjuryStatus`    | 傷病狀態（Free Trial 為 Scrambled） |
| `InjuryBodyPart`  | 傷病部位                         |
| `InjuryStartDate` | 傷病開始日期                       |
| `InjuryNotes`     | 傷病備註                         |

📌 **正式版 API 這些欄位是可用的**
📌 Free Trial 只保留欄位結構，內容會被模糊

---

## 五、DFS / Fantasy 平台相關欄位（Salary & Position）

| 欄位                     | 說明                      |
| ---------------------- | ----------------------- |
| `FanDuelSalary`        | FanDuel DFS 薪資          |
| `DraftKingsSalary`     | DraftKings DFS 薪資       |
| `FantasyDataSalary`    | SportsDataIO Fantasy 薪資 |
| `YahooSalary`          | Yahoo Fantasy 薪資        |
| `FanDuelPosition`      | FanDuel 對應位置            |
| `DraftKingsPosition`   | DraftKings 對應位置         |
| `YahooPosition`        | Yahoo 對應位置              |
| `FantasyDraftSalary`   | FantasyDraft 薪資         |
| `FantasyDraftPosition` | FantasyDraft 位置         |

📌 DFS 薪資通常 **高度相關於 projected minutes + usage**

---

## 六、對位強度（Matchup Difficulty）

| 欄位                     | 說明          |
| ---------------------- | ----------- |
| `OpponentRank`         | 對手整體防守強度排名  |
| `OpponentPositionRank` | 對手對該位置的防守排名 |

📌 常被用作 ML feature（例如 minutes / usage 調整）

---

## 七、核心「投影數據」欄位（Projected Stats）

> ⚠️ 注意：
> 這個 endpoint **是投影 API**，但欄位名稱與「實際比賽 stats」相同
> 比賽未開打前 → 代表「預測值」
> 比賽結束後 → 可能被回填為實際數值（依 subscription）

### ⏱ 上場時間（**關鍵！**）

| 欄位        | 說明              |
| --------- | --------------- |
| `Minutes` | **預計上場分鐘數（投影）** |
| `Seconds` | 上場秒數補充          |

👉 這裡就是你要的 **Projected Minutes**
👉 SportsDataIO 沒有另外叫 `ProjectedMinutes`，而是 **直接用 `Minutes`**

---

### 🏀 投籃 & 得分

* `FieldGoalsMade`
* `FieldGoalsAttempted`
* `FieldGoalsPercentage`
* `TwoPointersMade / Attempted / Percentage`
* `ThreePointersMade / Attempted / Percentage`
* `FreeThrowsMade / Attempted / Percentage`
* `Points`

---

### 📊 其他基本數據

* `Assists`
* `Rebounds`
* `OffensiveRebounds`
* `DefensiveRebounds`
* `Steals`
* `BlockedShots`
* `Turnovers`
* `PersonalFouls`
* `PlusMinus`

---

### 📈 進階 / 效率指標（部分可能為 null）

* `TrueShootingPercentage`
* `UsageRatePercentage`
* `AssistsPercentage`
* `StealsPercentage`
* `BlocksPercentage`
* `PlayerEfficiencyRating`

---

## 八、Fantasy 分數（Projected Fantasy Points）

| 欄位                          | 說明                      |
| --------------------------- | ----------------------- |
| `FantasyPoints`             | SportsDataIO Fantasy 分數 |
| `FantasyPointsFanDuel`      | FanDuel Fantasy 分數      |
| `FantasyPointsDraftKings`   | DraftKings Fantasy 分數   |
| `FantasyPointsYahoo`        | Yahoo Fantasy 分數        |
| `FantasyPointsFantasyDraft` | FantasyDraft 分數         |

---

## 九、總結（非常重要）

### ✅ 這個 API **確實包含「預計上場時間」**

* 欄位名稱：**`Minutes`**
* 屬性：**投影值（Projected）**
* 不會叫 `ProjectedMinutes`，但語意就是

### 🧠 實務建議

如果你要做 **Projected Minutes Model**，最佳特徵組合是：

```
Minutes (target or baseline)
Started
LineupConfirmed
OpponentRank
OpponentPositionRank
DFS Salary
InjuryStatus
Depth Chart（另一支 API）
```

