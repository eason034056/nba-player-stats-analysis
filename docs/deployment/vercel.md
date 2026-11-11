# 把前端部署到 Vercel

後端會放在 AWS EC2，前面是 HTTPS。網域還沒決定，所以這份文件用 `https://api.example.com` 當佔位，不要把這串字留在正式環境。

瀏覽器不直接打後端。它只打同一個 Vercel 網域上的 `/api/backend/...`。`frontend/middleware.ts` 在伺服器上把這段路徑轉到 `BACKEND_API_URL`，並在每個被轉送的請求加上兩個東西：

- `x-sportslab-proxy-secret`：值來自伺服器環境變數 `VERCEL_PROXY_SECRET`。瀏覽器送來的同名 header 會先被刪掉，再寫上這個值。
- `x-real-ip`：訪客的 IP。後端前面的 Caddy 會覆寫 `X-Forwarded-For`，所以後端要先讀 `x-real-ip`。瀏覽器自己帶的 `x-real-ip` 會被換掉。同一個 IP 也會寫進 `x-forwarded-for`。

這兩個變數都沒有 `NEXT_PUBLIC_` 前綴，不會被寫進瀏覽器的 JavaScript。

選這條路、不選「瀏覽器直接打 `NEXT_PUBLIC_API_URL`」的原因：

- 前端每一個後端呼叫都在 `frontend/lib/api.ts` 的 `fetchApi`，而且都是等整份 JSON（`response.json()`）。Agent Widget 的 `sendAgentChat` 也是一次 POST、一次 JSON。後端 `POST /api/nba/agent/chat` 回的是一整個回應物件，不是串流。
- 沒有 `EventSource`、沒有 `text/event-stream` 的呼叫端、沒有 Next.js route handler、沒有 server component 在伺服器上打後端。球隊 logo 來自 `a.espncdn.com`，不是後端網址。
- 同源路徑不需要瀏覽器 CORS，後端網址也不出現在 client bundle。
- 實測（`next dev` 與 `next start`，代理指到本機的測試伺服器）：`GET /api/health`、帶 query 的 `/api/nba/events`、`/api/wnba/events`、以及 `POST /api/nba/agent/chat` 的 JSON body，都會到達後端，而且路徑上的 `/api/backend` 前綴已被拿掉。分段的 `text/event-stream` 在後端回應帶 `Cache-Control: no-cache, no-transform` 時會一段一段轉送；沒有這個 header 時，Next 會把整段收齊再一次送出。現在的畫面沒有這種串流呼叫，所以不影響目前功能。

代價：Vercel 對「轉送到外部網址」的 120 秒是第一個 byte 的等待時間（time to first byte）。後端開始回資料之後，只要至少每 120 秒有資料送出，連線可以超過兩分鐘。超過第一個 byte 的等待會回 `ROUTER_EXTERNAL_TARGET_ERROR`。本機的 `next dev` / `next start` 預設 30 秒就切斷，`next.config.js` 的 `proxyTimeout: 120000` 只影響這兩個本機指令。Vercel 不讀那個設定。

本機 `npm run dev` 和本機 `next build` 都不用設變數，代理會指向 `http://localhost:8000`，而且不帶 `x-sportslab-proxy-secret`。只要環境裡有 `VERCEL` 或 `VERCEL_ENV`（Vercel 的 Production 與 Preview build 都會設），卻沒有 `BACKEND_API_URL` 或 `VERCEL_PROXY_SECRET`，build 會失敗，不會偷偷指回 localhost。這兩個值在 `next build` 當下讀得到，所以缺值是在 build 失敗，不是等到有人開網頁才發現。請求當下若 Vercel 環境仍然沒有 secret，代理回 `500`，內文是 `The API proxy is not configured.`，不會把 secret 或後端網址印出來，也不會把請求轉出去。

這個 repo 的預設分支是 `master`，沒有 `main`。不要新建 `main`。Production 用 `master`，Preview 用 `dev`。

在後端（SPO-133）完成之前，不要把正式流量導到這個前端。原因在下面「後端還沒核對之前不要上線」。

## 環境變數

你要自己填兩個變數。`VERCEL` 和 `VERCEL_ENV` 是 Vercel 在它的 build 裡自己設的，不要寫進本機 `.env`。

| 變數 | Production | Preview | Development |
|---|---|---|---|
| `BACKEND_API_URL` | 正式後端的 HTTPS origin，沒有路徑。網域還沒定之前不要用真的主機名稱；可暫時用 `https://api.example.com` 讓專案先建起來 | 與 Production 同一個 origin，或一台 staging 的 origin。兩種都可以，由你決定 | 不勾。本機用 `frontend/` 裡的 `npm run dev`，沒設變數就走 `http://localhost:8000` |
| `VERCEL_PROXY_SECRET` | `openssl rand -hex 32` 產生的一長串。和後端 AWS SSM 裡同名變數用同一個值。選 Sensitive（若畫面上有這個選項） | 與 Production 同一個值，除非 staging 後端用另一把。兩邊的值必須和該環境的後端一致 | 不勾。本機沒設這個變數時，代理不帶 secret header |

`frontend/.env.example` 裡的網址和 secret 都是註解掉的佔位，不是真的後端、也不是真的密鑰。不要把那個檔案原樣匯入 Vercel。

## 後端還沒核對之前不要上線

走這個代理之後，EC2 上看到的 TCP 來源是 Vercel 的出口 IP，不是訪客。`backend/app/middleware/rate_limit.py` 的 slowapi 用 `get_remote_address`（`request.client.host`）。`backend/Dockerfile` 的 uvicorn 沒有 `--proxy-headers`。所以預設的 `60/minute`、props 的 `20/minute`、bot picks 的 `12/minute` 會變成所有訪客共用，很快就回 429。

這支前端已經在每個被轉送的請求上放了 `x-sportslab-proxy-secret` 和 `x-real-ip`。後端必須先核對 secret，再把限流的 key 改成 `x-real-ip`。Caddy 會覆寫 `X-Forwarded-For`，所以不要拿 `X-Forwarded-For` 當訪客 IP。在 SPO-133 做完並確認之前，不要把正式流量指過來。前端這份改動沒有改後端的限流程式。

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
19. 在你自己的電腦終端機執行 `openssl rand -hex 32`。終端機會印出一行十六進位字。那一行就是 secret。不要把它貼進聊天、PR、commit 或這個文件。
    預期：你手上有一串只有你看得到的值。
20. 再加一列環境變數。Key 輸入 `VERCEL_PROXY_SECRET`。Value 貼上剛剛那一行。Environments 選 **Production and Preview**（staging 後端若用另一把 secret，就照第 18 步分成兩列）。不要勾 **Development**。若這一列有名為 **Sensitive** 的選項，打開它。Sensitive 變數存檔後不能再被讀回來，這是預期的。說明見 [Sensitive environment variables](https://vercel.com/docs/environment-variables/sensitive-environment-variables)。
    預期：Production 與 Preview 都有 `VERCEL_PROXY_SECRET`。畫面上若因 Sensitive 而看不到值，代表已存進去。
21. 把同一個值交給後端。後端讀的變數名稱也是 `VERCEL_PROXY_SECRET`，來源是 AWS SSM。怎麼寫進 SSM 寫在 SPO-133 的後端文件，這一步只要求兩邊的字完全相同。之後要換 secret：先改 Vercel 的值、再改 SSM 的值，然後照下面「改了環境變數之後」重新部署前端。只改一邊時，代理請求會被後端拒絕。
    預期：Vercel 與後端握有同一把 secret。你沒有把這把值寫進 git。
22. 不要點 **Import .env**。repo 裡沒有可以匯入的真值；`frontend/.env.example` 只是說明，而且那兩行是註解。
    預期：畫面上只有你剛剛打的那幾列。
23. 先確認 `master` 已經含有這次 SPO-134 的 commit。新專案的第一次部署一定是 Production，而且 Vercel 會先找 `main`、沒有才用 `master`。這個 repo 沒有 `main`，所以第一次 Production 建的是 `master`。`master` 在 `dev` 被合併進去之前，不會有這份前端。舊前端不讀 `BACKEND_API_URL`，那個 build 會成功，但 API 仍打 `http://localhost:8000`。紀錄裡不會出現 `BACKEND_API_URL is required`。若 `master` 還沒有這次改動，第一次 Production 的畫面開得起來、API 是壞的，這是預期，等 `dev` 合併進 `master` 再部署一次。
    預期：你知道第一次 Production 建的是哪一個 commit。
24. 在點 Deploy 之前設定 Node.js。打開 **Settings → Build and Deployment**，找到 **Node.js Version**（不在 General）。選 **22.x**。現在選單裡有 26.x（新專案預設）、24.x、22.x，沒有 20.x。`frontend/package.json` 的 `engines.node` 是 `22.x`，CI 也用 22。Next.js 14.2.35 要求 Node `>=18.17.0`。不要留在 26.x。
    預期：Node.js Version 顯示 22.x。若你還沒建立專案、畫面上還沒有 Settings，就在 Deploy 之後立刻做這一步，然後照下一節 Redeploy 一次。不要用 26.x 的那一次當正式結果。
25. 點 **Deploy**。
    預期：進入部署畫面，狀態從 Building 變成 Ready。第一次部署一定是 Production deployment，用的是 Production 環境變數，即使你的 git 預設分支之後會再確認。Build 成功時，畫面上有一個可以打開的網址。Build 失敗且紀錄裡有 `BACKEND_API_URL is required` 或 `VERCEL_PROXY_SECRET is required` 時，回到上面的環境變數補上，再部署一次（見下方「改了環境變數之後」）。紀錄不該印出 secret 的值，也不該印出你填錯的那串 origin。
26. 打開這個專案的 **Settings**。
    預期：進入 Project Settings。
27. 打開 **Environments**，點 **Production**，找到 **Branch Tracking**。
    預期：看得到目前的 Production 分支名稱。官方文件寫的位置是：Project Settings 的 Environments 頁 → 點 Production → Branch Tracking。若你的畫面把同一個欄位放在 **Git** 設定裡，欄位名稱是 **Production Branch**，用那個欄位即可。
28. 把分支名稱改成 `master`，點 **Save**。不要輸入 `main`，也不要在 GitHub 新建 `main`。這個 repo 沒有 `main`。
    預期：Production 的 Branch Tracking 顯示 `master`。之後只有推上 `master` 的 commit 會更新正式站。
29. `dev` 不要設成 Production。Vercel 會把每一個不是 Production 的分支部署成 Preview，`dev` 因此用 Preview 的環境變數。其他 feature 分支也會有 Preview，那是預設行為；這個 repo 要拿來對照後端的 Preview，是 `dev`。
    預期：沒有把 `dev` 寫進 Production Branch。
30. 回到專案的 **Overview**。找到沒有 `git-`、也沒有一長串 hash 的那個 `*.vercel.app` 網址。那就是目前的 Production URL。Deployments 清單裡 Environment 為 Production 的那一筆，網址相同。
    預期：可以打開前端畫面。在網域還沒換成真的後端、以及 SPO-133 還沒核對 secret 之前，不要把正式流量指過來。
31. 要看 `dev` 的 Preview：等 `dev` 上有一次由 Vercel 建出來的部署（把含這次改動的 commit 推進 `dev` 之後會自動發生）。打開專案的 **Deployments**。文件寫這個頁面可以用 **Branch** 篩選；篩 `dev`。
    預期：有一筆 Preview。分支網址的形狀是 `<project>-git-dev-<scope>.vercel.app`。某一筆 commit 的網址形狀是 `<project>-<hash>-<scope>.vercel.app`。`<project>` 是 Vercel 專案名稱，`<scope>` 是帳號或團隊的 slug。GitHub pull request 上，**Visit Preview** 是分支網址，**View deployment** 是該 commit 的網址。以 Deployments 頁上印出來的網址為準。

## Deployment Protection

2025 之後新建的專案，預設是 Standard Protection，並打開 Vercel Authentication。除了正式網域以外，其他網址都要先登入 Vercel 才打得開。這包含 `dev` 的分支網址、每一個 `*-hash-*.vercel.app`，以及 Production 那筆部署自己產生的 deployment URL。位置是 **Settings → Deployment Protection**。

1. 你用自己的 Vercel 帳號登入後可以看 Preview。瀏覽器打同源的 `/api/backend` 會帶上那個登入 cookie，所以 API 代理在你自己的瀏覽器裡可以通。
2. 要給沒有 Vercel 帳號的人看時，用 **Shareable Link** 或 **Protection Bypass**。不要把保護整個關掉。
3. **Password Protection** 是付費的 Pro 功能，Hobby 方案沒有。

## 自訂網域

網域還沒決定。決定之後：

1. 打開 **Settings → Domains**。
2. 點 **Add**，輸入網域。
3. 到你的 DNS 廠商，照 Vercel 畫面上給的 A 或 CNAME 去設。
4. 等到畫面上變成 **Valid Configuration**。
5. 確認這個網域指到 Production。

加網域不會觸發重新部署，也不用改 `BACKEND_API_URL`。

## 改了環境變數之後要重新部署

改 `BACKEND_API_URL` 或 `VERCEL_PROXY_SECRET` 不會更新已經建好的部署。代理的目的地和 secret 是 build 的時候寫進去的。

1. 打開專案，點側邊的 **Deployments**。
   預期：看到部署清單。
2. 找到要更新的那一筆（正式站改 Production 那筆，`dev` 改 Preview 那筆）。點該列的 **⋯**（文件寫 ellipsis icon）。
   預期：選單打開。
3. 點 **Redeploy**。
   預期：出現確認視窗。文件稱 Production 的這個視窗為 Redeploy to Production。
4. 若視窗裡有要不要沿用既有 **Build Cache** 的選項，關掉它。文件只說你可以決定是否使用 existing Build Cache，沒有把核取方塊的逐字標籤寫死；以畫面上提到 Build Cache 的那個控制項為準，不要沿用舊的 build。舊快取可能仍指著上一個 origin 或上一把 secret。
   預期：這次會重新執行 `next build`。
5. 點確認視窗裡的 **Redeploy**。
   預期：新的一筆部署變成 Ready。換 secret 時，後端的 SSM 也要是同一把值。

## CORS

用現在這個代理，瀏覽器認為 API 和網頁是同一個網址，所以沒有 CORS preflight。請求是 Vercel 的伺服器轉給 EC2，不是瀏覽器直接跨網域。

Starlette 的 `CORSMiddleware` 仍會看到這筆一般請求。若 `Origin` 不在 allowlist，它只是不加 `Access-Control-Allow-Origin`，不會把請求擋下。後端的 `ALLOWED_ORIGINS` 不需要加入 Vercel 的網域。不要設 `Access-Control-Allow-Origin: *`。

之後若改回瀏覽器直接打 EC2，才需要把這些 origin 加進後端的 allowlist：

- Production：`https://<project>.vercel.app`，以及你之後加的自訂網域
- 分支 Preview：`https://<project>-git-<branch>-<scope>.vercel.app`
- 單次部署：`https://<project>-<hash>-<scope>.vercel.app`

`<branch>` 裡若有 `/`，以 Deployments 頁上的實際網址為準，不要自己組。

## 快取

2026-04-06 之後建立的專案，外部 rewrite 預設會遵守上游的 `Cache-Control`。目前後端沒有送 `Cache-Control`，所以 Vercel CDN 不會快取這些 API 回應。之後若後端送出 `Cache-Control: public`，CDN 會快取。不想被快取時，後端要送 `private` 或 `no-store`。

## 為什麼沒有 vercel.json

Root Directory 設成 `frontend` 之後，Vercel 會把那個目錄裡的 Next.js 專案當成專案根目錄。框架、安裝指令、build 指令都用上面的預設。

`vercel.json` 的 `routes` transform 可以在外部 rewrite 上用 `$VERCEL_PROXY_SECRET` 設定一個固定 header，也可以和 `rewrites` 同時存在。這份改動仍不用它，原因有三個：

- 專案沒設那個環境變數時，`$VAR` 會原樣留在送出去的 header，請求還是會被轉走。我們要的是不轉送、回 500。見 [vercel.json 的 routes](https://vercel.com/docs/project-configuration/vercel-json)。
- transform 沒有把訪客 IP 寫進 `x-real-ip` 的代換。Caddy 會覆寫 `X-Forwarded-For`，後端要讀的是 `x-real-ip`。見 [Rewrites](https://vercel.com/docs/routing/rewrites) 與 [Request headers](https://vercel.com/docs/headers/request-headers)。
- `next dev` 和 `next start` 不會套用 `vercel.json` 的 routes。本機零設定的代理就不會帶這些 header。

所以只有一條代理：`frontend/middleware.ts`。Vercel 會覆寫瀏覽器送來的 `x-forwarded-for`，不轉送外部 IP，避免偽造。`x-real-ip` 在 Vercel 上和 `x-forwarded-for` 是同一個訪客 IP。middleware 不採用瀏覽器的 `x-real-ip`；它讀 `x-vercel-forwarded-for`，沒有才讀 `x-forwarded-for` 的第一個位址，然後同時寫進 `x-real-ip` 和 `x-forwarded-for`。

Production 分支和環境變數都在 dashboard，不在 `vercel.json`。

## 疑難排解

### Build 失敗，紀錄說缺少後端網址

紀錄裡會有這句：

`BACKEND_API_URL is required when VERCEL or VERCEL_ENV is set.`

後面會寫它不會退回 `http://localhost:8000`。

若 origin 不是 https，紀錄是：

`BACKEND_API_URL must use https on a Vercel build.`

處理：到專案的 **Environment Variables**，確認 Production（以及你要部署的 Preview）有 `BACKEND_API_URL`，值是 https origin、沒有路徑。存檔後照上一節 Redeploy，並且不要沿用舊的 Build Cache。只設給 Preview 的變數不會進第一次的 Production deployment。

本機要重現這個失敗：在 `frontend/` 執行 `VERCEL=1 npx next build`，而且不要設 `BACKEND_API_URL`。本機正常 build 不要設 `VERCEL`。

### Build 失敗，紀錄說缺少 proxy secret

紀錄裡會有 `VERCEL_PROXY_SECRET is required`。它不會印出你曾經填過的值。

處理：照部署步驟第 19–21 步產生一把 secret，設進 Production 和 Preview，交給後端的 SSM，然後 Redeploy。

### API 回 500，內文是 The API proxy is not configured.

這筆部署在執行時沒有 `VERCEL_PROXY_SECRET`，或後端 origin 無法解析。請求沒有被轉到後端。到 Environment Variables 補上變數，Redeploy，不要沿用舊的 Build Cache。

### API 回 404

打開瀏覽器的開發者工具，看失敗那筆請求的網址。

- 網址是 `https://<vercel 網域>/api/backend/api/nba/...` 或 `/api/wnba/...`：代理有在工作。404 是後端回的。請到 EC2 上看同一個路徑（沒有 `/api/backend` 前綴）是否存在，以及 `BACKEND_API_URL` 是不是 origin、有沒有多寫 `/api`。
- 網址是 `http://localhost:8000/...`：線上還在跑舊的前端。確認這次部署的 commit 含這個改動，並在改完環境變數後重新部署。第一次 Production 若建的是還沒合併的 `master`，就會是這個情況。
- 網址是 `/api/nba/...`，沒有 `/api/backend`：Root Directory 不是 `frontend`，或部署的不是這份設定。到 Project Settings 找 **Root Directory**，設成 `frontend`，然後重新部署。
- HTML 404 頁、而不是 JSON：請求打到了 Next 自己，代理沒有配上。同樣先確認 Root Directory 是 `frontend`，再確認 build 紀錄裡沒有把 `BACKEND_API_URL` 設成空的。

### Root Directory 設錯

症狀：build 找不到 Next.js、在 repo 根目錄執行 `next build`，或部署成功但畫面上不是這個前端。

處理：Project Settings 裡名為 **Root Directory** 的欄位設成 `frontend`（匯入時是該欄位旁的 **Edit**）。存檔後重新部署。不要把 Output Directory 設成 `.next`。

### 請求等很久才失敗

第一個 byte 等超過約 120 秒時，Vercel 回 `ROUTER_EXTERNAL_TARGET_ERROR`。後端開始送資料之後，只要至少每 120 秒還有資料，連線可以比兩分鐘更長。把 `next.config.js` 的 `proxyTimeout` 調大不會提高 Vercel 的上限，那個值只給本機的 `next dev` / `next start`。
