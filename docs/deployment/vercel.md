# 把前端部署到 Vercel

後端會放在 AWS EC2，前面是 HTTPS。網域還沒決定，所以這份文件用 `https://api.example.com` 當佔位，不要把這串字留在正式環境。

瀏覽器不直接打後端。它只打同一個 Vercel 網域上的 `/api/backend/...`。Next.js 的 rewrite 在伺服器上把這段路徑轉到 `BACKEND_API_URL`。這個變數沒有 `NEXT_PUBLIC_` 前綴，不會被寫進瀏覽器的 JavaScript。

選這條路、不選「瀏覽器直接打 `NEXT_PUBLIC_API_URL`」的原因：

- 前端每一個後端呼叫都在 `frontend/lib/api.ts` 的 `fetchApi`，而且都是等整份 JSON（`response.json()`）。Agent Widget 的 `sendAgentChat` 也是一次 POST、一次 JSON。後端 `POST /api/nba/agent/chat` 回的是一整個回應物件，不是串流。
- 沒有 `EventSource`、沒有 `text/event-stream` 的呼叫端、沒有 Next.js route handler、沒有 server component 在伺服器上打後端。球隊 logo 來自 `a.espncdn.com`，不是後端網址。
- 同源路徑不需要瀏覽器 CORS，後端網址也不出現在 client bundle。
- 實測（`next dev` 與 `next start`，rewrite 指到本機的測試伺服器）：`GET /api/health`、帶 query 的 `/api/nba/events`、`/api/wnba/events`、以及 `POST /api/nba/agent/chat` 的 JSON body，都會到達後端，而且路徑上的 `/api/backend` 前綴已被拿掉。分段的 `text/event-stream` 在後端回應帶 `Cache-Control: no-cache, no-transform` 時會一段一段轉送；沒有這個 header 時，Next 會把整段收齊再一次送出。現在的畫面沒有這種串流呼叫，所以不影響目前功能。

代價：Vercel 對「rewrite 到外部網址」的上限是 120 秒。超過會回 `ROUTER_EXTERNAL_TARGET_ERROR`。本機的 `next dev` / `next start` 預設 30 秒就切斷，`next.config.js` 把這個本機代理設成同樣的 120 秒。Vercel 不讀那個設定，平台自己卡在 120 秒。

本機 `npm run dev` 和本機 `next build` 都不用設變數，rewrite 會指向 `http://localhost:8000`。只要環境裡有 `VERCEL` 或 `VERCEL_ENV`（Vercel 的 Production 與 Preview build 都會設），卻沒有 `BACKEND_API_URL`，build 會失敗，不會偷偷指回 localhost。

這個 repo 的預設分支是 `master`，沒有 `main`。不要新建 `main`。Production 用 `master`，Preview 用 `dev`。

## 環境變數

只需要你自己填一個變數。`VERCEL` 和 `VERCEL_ENV` 是 Vercel 在它的 build 裡自己設的，不要寫進本機 `.env`。

| 變數 | Production | Preview | Development |
|---|---|---|---|
| `BACKEND_API_URL` | 正式後端的 HTTPS origin，沒有路徑。網域還沒定之前不要用真的主機名稱；可暫時用 `https://api.example.com` 讓專案先建起來 | 與 Production 同一個 origin，或一台 staging 的 origin。兩種都可以，由你決定 | 不勾。本機用 `frontend/` 裡的 `npm run dev`，沒設變數就走 `http://localhost:8000` |

`frontend/.env.example` 裡的 `https://api.example.com` 是佔位，不是真的後端。不要把那個檔案原樣匯入 Vercel。

## 部署步驟

下面每一步只做一件事。按鈕與欄位的英文用 Vercel 畫面上的文字。說明是中文。Vercel 的畫面會改版；若某個按鈕不在寫的位置，用欄位名稱找，不要猜一個看起來相近的選單。

1. 打開 [https://vercel.com/login](https://vercel.com/login)。
   預期：登入頁。上面有用 GitHub 登入的按鈕。
2. 點 **Continue with GitHub**（用 GitHub 帳號繼續）。若按鈕寫的是 **Log in with GitHub** 或 GitHub 圖示，點那個。
   預期：瀏覽器轉到 GitHub。若這個瀏覽器已經登入 GitHub，會進入授權頁或直接回 Vercel。
3. 在 GitHub 的授權頁點授權 Vercel 的按鈕（常見文字是 **Authorize**）。已經授權過的帳號不會再看到這一頁。
   預期：回到 Vercel dashboard。右上角看得到你的帳號或團隊。
4. 看 dashboard 左上角的團隊切換（team switcher）。選你自己要拿來放這個專案的個人帳號或團隊。
   預期：接下來建立的專案會落在這個團隊底下。
5. 打開 [https://vercel.com/new](https://vercel.com/new)。也可以在 dashboard 點 **Create New**，再點 **Project**。有些帳號這個按鈕仍寫 **Add New**，那是同一個選單，接著仍點 **Project**。
   預期：進入 Import Git Repository，下面是一份 GitHub repo 清單。
6. 看清單左上角的帳號選單。選 **eason034056**。這個 repo 在個人帳號下，不在某個 GitHub organization。
   預期：清單換成該帳號底下、Vercel GitHub App 看得到的 repo。
7. 在搜尋框輸入 `nba-player-stats-analysis`。
   預期：出現 `eason034056/nba-player-stats-analysis`。若沒有，做第 8–10 步。已經看得到就跳到第 11 步。
8. 在清單下方點 **Adjust GitHub App Permissions**。若清單是空的、畫面上寫的是 **Configure GitHub App**，點那個。另一條路：GitHub → Settings → Applications → Installed GitHub Apps → Vercel 旁邊的 **Configure**。
   預期：打開 GitHub 上 Vercel app 的設定頁。
9. 在 **Repository access** 裡，把 `nba-player-stats-analysis` 加進已授權的 repo；或改選 **All repositories**。
   預期：該 repo 出現在授權範圍裡。
10. 點 **Save**。
    預期：GitHub 顯示已儲存。回到 Vercel 的 import 畫面，重新搜尋 `nba-player-stats-analysis`，這次看得到該 repo。
11. 在 `eason034056/nba-player-stats-analysis` 那一列點 **Import**。
    預期：進入 Configure Project。頁面上有 Project Name、Framework Preset、Root Directory、Build and Output Settings、Environment Variables。
12. 找到 **Root Directory**。它現在多半是 `./` 或 repo 根目錄。點旁邊的 **Edit**。
    預期：出現目錄選擇或一個可以輸入路徑的欄位。
13. 選 `frontend`，或在欄位輸入 `frontend`，然後確認（按鈕可能是 **Continue** 或 **Save**，以對話框上的確認鈕為準）。
    預期：Root Directory 顯示 `frontend`。Framework Preset 變成 **Next.js**。
14. 看 **Framework Preset**。它應該已經是 **Next.js**。若不是，打開選單，選 **Next.js**。
    預期：選單顯示 Next.js。
15. 展開 **Build and Output Settings**（若它是收合的）。Install Command、Build Command、Output Directory 都留空，使用框架預設。不要填 Output Directory。
    預期：三個覆寫欄位是空的。`frontend/package-lock.json` 存在，所以安裝用 npm。Build Command 的預設是 `next build`（在 Root Directory `frontend` 裡執行）。這個 Next.js app 不是靜態輸出，沒有要你填的 Output Directory。
16. 在 **Environment Variables** 的 **Key**（有的畫面寫 **Name**）輸入 `BACKEND_API_URL`。
    預期：名字欄裡只有這個變數名稱。
17. 在 **Value** 輸入後端的 HTTPS origin。必須是 `https://主機`，可以帶連接埠，不能帶路徑、問號或帳號密碼。網域還沒決定時，先輸入 `https://api.example.com`，並在網域決定後換成真的 origin。
    預期：值是一個 origin。例如 `https://api.example.com`，不是 `https://api.example.com/api`。
18. 在 **Environments** 選擇要套用的環境。Production 和 Preview 要用同一個 origin 時，選 **Production and Preview**。Preview 要另用一台 staging 時，這一列只選 **Production**；再點 **Add More**，Key 仍是 `BACKEND_API_URL`，Value 改成 staging 的 origin，Environments 只選 **Preview**。不要勾 **Development**。
    預期：Production 與 Preview 都有 `BACKEND_API_URL`。Development 沒有。
19. 不要點 **Import .env**。repo 裡沒有可以匯入的真值；`frontend/.env.example` 只是說明。
    預期：畫面上只有你剛剛打的那一列（或 Production、Preview 各一列）。
20. 點 **Deploy**。
    預期：進入部署畫面，狀態從 Building 變成 Ready。第一次部署一定是 Production deployment，用的是 Production 環境變數，即使你的 git 預設分支之後會再確認。Build 成功時，畫面上有一個可以打開的網址。Build 失敗且紀錄裡有 `BACKEND_API_URL is required` 時，回到上面的環境變數，補上 origin，再部署一次（見下方「改了環境變數之後」）。
21. 打開這個專案的 **Settings**。
    預期：進入 Project Settings。
22. 打開 **Environments**，點 **Production**，找到 **Branch Tracking**。
    預期：看得到目前的 Production 分支名稱。官方文件寫的位置是：Project Settings 的 Environments 頁 → 點 Production → Branch Tracking。若你的畫面把同一個欄位放在 **Git** 設定裡，欄位名稱是 **Production Branch**，用那個欄位即可。
23. 把分支名稱改成 `master`，點 **Save**。不要輸入 `main`，也不要在 GitHub 新建 `main`。這個 repo 沒有 `main`；Vercel 的預設順序是先找 `main`、沒有才用 `master`，所以多半已經是 `master`，仍然要看一眼並存檔。
    預期：Production 的 Branch Tracking 顯示 `master`。之後只有推上 `master` 的 commit 會更新正式站。
24. `dev` 不要設成 Production。Vercel 會把每一個不是 Production 的分支部署成 Preview，`dev` 因此用 Preview 的環境變數。其他 feature 分支也會有 Preview，那是預設行為；這個 repo 要拿來對照後端的 Preview，是 `dev`。
    預期：沒有把 `dev` 寫進 Production Branch。
25. 回到專案的 **Overview**。找到沒有 `git-`、也沒有一長串 hash 的那個 `*.vercel.app` 網址。那就是目前的 Production URL。Deployments 清單裡 Environment 為 Production 的那一筆，網址相同。
    預期：可以打開前端畫面。在網域還沒換成真的後端之前，畫面開得起來，打 API 會失敗。
26. 要看 `dev` 的 Preview：等 `dev` 上有一次由 Vercel 建出來的部署（把含這次改動的 commit 推進 `dev` 之後會自動發生）。打開專案的 **Deployments**。文件寫這個頁面可以用 **Branch** 篩選；篩 `dev`。
    預期：有一筆 Preview。分支網址的形狀是 `<project>-git-dev-<scope>.vercel.app`。某一筆 commit 的網址形狀是 `<project>-<hash>-<scope>.vercel.app`。`<project>` 是 Vercel 專案名稱，`<scope>` 是帳號或團隊的 slug。GitHub pull request 上，**Visit Preview** 是分支網址，**View deployment** 是該 commit 的網址。以 Deployments 頁上印出來的網址為準。
27. Node.js 版本：`frontend/package.json` 沒有 `engines`，Vercel 不會從這個欄位幫你選。lockfile 裡的 Next.js 14.2.35 要求 Node `>=18.17.0`。到 Project Settings 找名為 **Node.js Version** 的設定（常見放在 General）。選單裡若有 **22.x**，選 22.x。不要選 18（Vercel 已不能用）。20 自 2026-10-01 起是 deprecated。若畫面上的預設已經讓第 20 步的 build 成功，可以先留著，不必為了改版本再部署一次。
    預期：專案使用的 Node 符合 `>=18.17.0`。

自訂網域還沒決定。之後要加時，到專案設定裡名為 **Domains** 的地方，把網域指到 Production。那個網域會和 `*.vercel.app` 的正式網址一起開著。

## 改了環境變數之後要重新部署

改 `BACKEND_API_URL` 不會更新已經建好的部署。rewrite 的目的地是 build 的時候寫進去的。

1. 打開專案，點側邊的 **Deployments**。
   預期：看到部署清單。
2. 找到要更新的那一筆（正式站改 Production 那筆，`dev` 改 Preview 那筆）。點該列的 **⋯**（文件寫 ellipsis icon）。
   預期：選單打開。
3. 點 **Redeploy**。
   預期：出現確認視窗。文件稱 Production 的這個視窗為 Redeploy to Production。
4. 若視窗裡有要不要沿用既有 **Build Cache** 的選項，關掉它。文件只說你可以決定是否使用 existing Build Cache，沒有把核取方塊的逐字標籤寫死；以畫面上提到 Build Cache 的那個控制項為準，不要沿用舊的 build。rewrite 目的地是在 build 時寫入的，舊快取可能仍指著上一個 origin。
   預期：這次會重新執行 `next build`。
5. 點確認視窗裡的 **Redeploy**。
   預期：新的一筆部署變成 Ready，API 路徑改走新的 origin。

## CORS

用現在這個 rewrite，瀏覽器認為 API 和網頁是同一個網址，所以瀏覽器 CORS 不是必要條件。請求是 Vercel 的伺服器轉給 EC2，不是瀏覽器直接跨網域。

後端不必為了這個前端去放行下面的 origin。也不要設 `Access-Control-Allow-Origin: *`。FastAPI 的 CORS middleware 通常只會決定要不要在回應上加 header，不會因為 origin 不合就拒絕伺服器對伺服器的請求。

之後若改回瀏覽器直接打 EC2，才需要把這些 origin 加進後端的 allowlist：

- Production：`https://<project>.vercel.app`，以及你之後加的自訂網域
- 分支 Preview：`https://<project>-git-<branch>-<scope>.vercel.app`
- 單次部署：`https://<project>-<hash>-<scope>.vercel.app`

`<branch>` 裡若有 `/`，以 Deployments 頁上的實際網址為準，不要自己組。

## 為什麼沒有 vercel.json

Root Directory 設成 `frontend` 之後，Vercel 會把那個目錄裡的 Next.js 專案當成專案根目錄。框架、安裝指令、build 指令都用上面的預設。rewrite 寫在 `frontend/next.config.js`，Next 會收進部署，不需要再寫一份 `vercel.json`。`vercel.json` 解決不了「Production 分支是 master」或「環境變數」這兩件事，那兩個都在 dashboard。

## 疑難排解

### Build 失敗，紀錄說缺少後端網址

紀錄裡會有這句：

`BACKEND_API_URL is required when VERCEL or VERCEL_ENV is set.`

後面會寫它不會退回 `http://localhost:8000`。

處理：到專案的 **Environment Variables**，確認 Production（以及你要部署的 Preview）有 `BACKEND_API_URL`，值是 https origin、沒有路徑。存檔後照上一節 Redeploy，並且不要沿用舊的 Build Cache。只設給 Preview 的變數不會進第一次的 Production deployment。

本機要重現這個失敗：在 `frontend/` 執行 `VERCEL=1 npx next build`，而且不要設 `BACKEND_API_URL`。本機正常 build 不要設 `VERCEL`。

### API 回 404

打開瀏覽器的開發者工具，看失敗那筆請求的網址。

- 網址是 `https://<vercel 網域>/api/backend/api/nba/...` 或 `/api/wnba/...`：rewrite 有在工作。404 是後端回的。請到 EC2 上看同一個路徑（沒有 `/api/backend` 前綴）是否存在，以及 `BACKEND_API_URL` 是不是 origin、有沒有多寫 `/api`。
- 網址是 `http://localhost:8000/...`：線上還在跑舊的前端。確認這次部署的 commit 含這個改動，並在改完環境變數後重新部署。
- 網址是 `/api/nba/...`，沒有 `/api/backend`：Root Directory 不是 `frontend`，或部署的不是這份設定。到 Project Settings 找 **Root Directory**，設成 `frontend`，然後重新部署。
- HTML 404 頁、而不是 JSON：請求打到了 Next 自己，rewrite 沒有配上。同樣先確認 Root Directory 是 `frontend`，再確認 build 紀錄裡沒有把 `BACKEND_API_URL` 設成空的。

### Root Directory 設錯

症狀：build 找不到 Next.js、在 repo 根目錄執行 `next build`，或部署成功但畫面上不是這個前端。

處理：Project Settings 裡名為 **Root Directory** 的欄位設成 `frontend`（匯入時是該欄位旁的 **Edit**）。存檔後重新部署。不要把 Output Directory 設成 `.next`。

### 請求超過約兩分鐘失敗

那是 Vercel 對外部 rewrite 的 120 秒上限，錯誤名稱是 `ROUTER_EXTERNAL_TARGET_ERROR`。把後端變快，或之後另做一條不受這個上限約束的呼叫方式。把 `next.config.js` 的 `proxyTimeout` 調大不會提高 Vercel 的上限。
