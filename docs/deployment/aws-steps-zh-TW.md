# 在 Mac 上把 Sports Lab 接到 AWS（繁體中文步驟）

英文版與環境變數說明在 [docs/deployment/aws.md](aws.md)。這份只寫 Eason 在自己的 Mac 上要做的事。

後端跑在這台 Mac。Postgres 跑在同一台 Mac 的 Docker 裡，容器名稱是 `no-vig-nba-postgres`（映像 `postgres:16-alpine`，`docker-compose.yml` 沒有把 5432 發佈到 Mac 本身）。這台 Mac 沒有部署到任何主機，也沒有固定 IP，家裡的對外 IP 會變。AWS 帳號已經存在。`terraform apply` 由 Eason 自己執行。不要建立 provisioner 使用者，也不要把任何金鑰貼到 repo 或聊天裡。

允許連上 RDS 5432 的位址只有兩個 `/32`：真實的 box `/32`（只寫在 gitignore 的 `terraform.tfvars`；範例檔用 `198.51.100.10/32`），以及這台 Mac 目前的對外 IP。每天一份的 `pg-dumps/` 保留 90 天。

## 1. 用 Homebrew 安裝工具

```bash
brew install terraform awscli jq
brew install --cask docker-desktop
```

安裝完打開 Docker Desktop，等它顯示正在執行。`terraform version`、`aws --version`、`docker version` 都要有輸出。

## 2. 在這台 Mac 設定自己的 AWS 登入

```bash
aws configure
```

四個欄位：

- Access Key ID：你自己的金鑰
- Secret Access Key：你自己的密鑰
- Default region name：`us-east-2`
- Default output format：`json`

這兩個檔只留在這台 Mac：`~/.aws/credentials`、`~/.aws/config`。不要複製進 repo、不要貼進聊天、不要寫進 `.env`。

確認登入的是預期的帳號（這行只印帳號編號，不印金鑰）：

```bash
aws sts get-caller-identity
```

## 3. 先看方案與帳單，再設警報

帳號已經存在。這一步是看帳單並設警報，不是改方案。AWS 沒有一個叫做 Paid plan 的升級按鈕。

1. 打開主控台，搜尋 **Billing and Cost Management**，看目前的帳單。
2. 搜尋 **AWS Budgets**，或打開 **Billing and Cost Management → Budgets**。建立每月成本預算 25 美元。實際花費到 80% 寄信，預測花費到 100% 也寄信。收件人用你自己的信箱。

25 美元是預算上限，不是估價，也不是這個月的固定帳單。`db.t4g.micro` 的運算大約每小時 0.016 美元（一個月大約 12 美元）。除此之外還要算：gp3 儲存、超過免費額度的備份儲存、資料傳出，以及 T4g unlimited 的 CPU credit。

## 4. terraform init、plan、apply

在 repo 根目錄：

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars
```

編輯 `terraform.tfvars`（這個檔已被 gitignore，不要 commit）：

- `bucket_name` 換成全域唯一的名稱，例如 `sportslab-data-<帳號編號>-us-east-2`。
- `allowed_cidrs` 的 `# box` 範例是 `198.51.100.10/32`。在這份 gitignore 檔裡把它換成真實的 box `/32`。不要把真實位址寫回 repo。
- 把 `# mac-home` 那一行的 `203.0.113.10` 換成這台 Mac 現在的對外 IP。`203.0.113.10` 和 `198.51.100.10` 都只是文件用的佔位。

查目前的對外 IP（下一節的腳本也會查）：

```bash
curl -s https://checkip.amazonaws.com
```

然後：

```bash
terraform init
terraform plan
terraform apply
```

`plan` 裡不該出現 `0.0.0.0/0`。apply 結束後記下 `db_endpoint`、`master_user_secret_arn`、`bucket_name`，以及 `app_security_group_id`。

`app_security_group_id` 是 `sportslab-app` 這個安全群組。它現在沒有任何進站規則，是留給之後的 EC2 後端（SPO-133）掛上去用的。RDS 已經用安全群組 id 放行這個群組的 TCP 5432，也放行 `rds_allowed_security_group_ids` 裡的每一個 id（預設是空清單）。

EC2 後端上線、而且實例已經掛在 `sportslab-app` 之後，把 gitignore 的 `terraform.tfvars` 改成 `allowed_cidrs = []` 再 `terraform apply`。這樣 Mac 和 box 的 IP 規則會消失。RDS 仍然允許 `sportslab-app`。之後不要再跑 `./scripts/aws_update_my_ip.sh --apply`，因為 `--apply` 會把那兩個 `/32` 再傳回去。`0.0.0.0/0` 和 `::/0` 仍然會被拒絕。空清單是允許的。

`infra/aws/README.md` 裡的 provisioner IAM JSON 是舊計畫的對照清單。不要照它去建立另一把金鑰。

## 5. 家裡 IP 變了就更新允許清單

在 repo 根目錄：

```bash
./scripts/aws_update_my_ip.sh
```

腳本會：

1. 用 `curl` 讀 `https://checkip.amazonaws.com`，把 IP 印出來。這不是 AWS 資源 API，也不使用你的金鑰。
2. 改寫 gitignore 的 `infra/aws/terraform.tfvars`：只換 `# mac-home` 那一行。`# box` 那一行維持你已經寫進去的真實 `/32`，腳本不會改它，腳本裡也沒有那個位址。
3. 印出 `terraform apply` 指令。預設到這裡就停，不呼叫 AWS。

你看過印出的指令之後，自己執行它，或再跑一次並加上 `--apply`（只有這個旗標會啟動 terraform，AWS 呼叫都是 terraform 發的）：

```bash
./scripts/aws_update_my_ip.sh --apply
```

apply 完成之前，這台 Mac 連不上 RDS 的 5432。

## 6. 從 Secrets Manager 讀 master 密碼

在 `infra/aws`：

```bash
terraform output -raw master_user_secret_arn
aws secretsmanager get-secret-value \
  --secret-id "$(terraform output -raw master_user_secret_arn)" \
  --query SecretString --output text \
  --region us-east-2 | jq -r .password
```

`--query SecretString` 印出來的是 JSON，裡面有 `username` 和 `password`。上面的 `jq -r .password` 只取出密碼。不要把整段 JSON 貼進 `RDS_DATABASE_URL`。終端機會留下這段輸出。不要貼到聊天，也不要寫進 git。Terraform 不會把這組密碼寫進輸出。

遷移腳本和每日 dump 腳本不會自己去 Secrets Manager。它們只讀你已經組好的 `RDS_DATABASE_URL`。密碼若含 `@`、`:`、`/`、`%`，寫進網址前要做百分比編碼（`/` 寫成 `%2F`）。

接著用 master 帳號、加上 SSL，建立應用程式角色 `sportslab_app`（Terraform 不建立這個角色）。後端用這個角色，不用 master。把連線資訊放在權限 `600` 的檔案裡再載入，不要把密碼寫在同一行指令上：

```bash
touch ~/.sportslab-psql.env
chmod 600 ~/.sportslab-psql.env
# 檔案內容一行：
# MASTER_URL=postgresql://sportslab_admin:ENCODED@ENDPOINT:5432/novig_nba?sslmode=require
set -a
source ~/.sportslab-psql.env
set +a
psql "$MASTER_URL"
```

連上之後執行（密碼只留在這台 Mac，不要 commit）：

```sql
CREATE ROLE sportslab_app LOGIN PASSWORD 'REPLACE_ME';
GRANT CONNECT ON DATABASE novig_nba TO sportslab_app;
GRANT USAGE, CREATE ON SCHEMA public TO sportslab_app;
```

PostgreSQL 15 以後，`public` schema 不會讓每個角色都能 `CREATE`。上面的 `GRANT` 讓 `sportslab_app` 能建立那六張表，並成為擁有者。

## 7. 用 docker exec 把本機資料庫搬到 RDS

先停掉會寫入本機資料庫的後端，避免搬移過程中筆數對不上。

`5432` 沒有發佈到 Mac，所以不要在 Mac 上直接跑 `pg_dump` 去連 `localhost:5432`。預設路徑是進到容器裡執行 `pg_dump`。在容器裡面，`localhost:5432` 就是這顆 Postgres。

在 repo 根目錄。不要把 DSN 打在指令列上，否則密碼會進 shell history。兩條網址放在權限 `600`、且不在 repo 裡的檔案，或用 `read -s` 輸入（不回顯、也不會變成一條指令）。腳本不會呼叫 Secrets Manager。

```bash
touch ~/.sportslab-migrate.env
chmod 600 ~/.sportslab-migrate.env
# LOCAL_DATABASE_URL=postgresql://novig:novig@localhost:5432/novig_nba
# RDS_DATABASE_URL=postgresql://sportslab_admin:ENCODED@ENDPOINT:5432/novig_nba
set -a
source ~/.sportslab-migrate.env
set +a
./scripts/db_migrate_to_rds.sh
```

或兩條都用 `read -s` 輸入，不要把網址寫在指令上：

```bash
read -s -p "Local URL: " LOCAL_DATABASE_URL
echo
read -s -p "RDS URL: " RDS_DATABASE_URL
echo
export LOCAL_DATABASE_URL RDS_DATABASE_URL
./scripts/db_migrate_to_rds.sh
```

預設等於 `--pg-client docker-exec --local-container no-vig-nba-postgres`。容器名稱若不同：

```bash
./scripts/db_migrate_to_rds.sh --local-container <容器名稱>
```

或設定環境變數 `LOCAL_PG_CONTAINER`。

若容器裡的客戶端不能用，改用一次即丟的 `postgres:16` 客戶端（與伺服器主版本相同）。dump 會加入資料庫容器的網路；restore 走映像自己的網路，才連得到 RDS：

```bash
PG_CLIENT=docker-run ./scripts/db_migrate_to_rds.sh
```

RDS 網址若沒有 `sslmode`，腳本會在 restore 與 RDS 端的筆數檢查加上 `sslmode=require`。已經寫了 `sslmode`（例如 `verify-full`）就保持原樣。腳本不會印出任一條網址或密碼。`pg_restore` 主版本不是 16 會直接停止。

結束時應看到 `name|metric|local|rds|status`，每一列都是 `OK`，最後一行是 `ok: ...`。目標資料庫要是空的；腳本不會加 `--clean`。

## 8. 把 DATABASE_URL 寫進這台 Mac 的 .env

`.env` 已被 gitignore。範本是 repo 根目錄的 `env.example`（`cp env.example .env`）。下載 RDS CA，路徑要是後端行程讀得到的路徑：

```bash
curl -fsSL -o "$HOME/global-bundle.pem" https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
```

第一次先把 `DATABASE_REQUIRED` 留成 `false`，確認日誌之後再改成 `true`。密碼含 `@`、`:`、`/`、`%` 時要先百分比編碼。

```bash
DATABASE_URL=postgresql://sportslab_app:ENCODED@ENDPOINT:5432/novig_nba?sslmode=verify-full&sslrootcert=/絕對路徑/global-bundle.pem
DATABASE_REQUIRED=false
```

確認成功之後再把 `DATABASE_REQUIRED` 改成 `true`。設成 `true` 時，資料庫連不上，後端會停止，而不是繼續提供沒有資料庫的 API。

若後端是用 `docker compose` 啟動，`DATABASE_URL` 會覆寫 compose 裡的本機預設值 `postgresql://novig:novig@postgres:5432/novig_nba`。把 `global-bundle.pem` 掛進後端容器，並把 `sslrootcert` 指到容器內看得到的路徑。

## 9. 驗證

- 後端日誌裡的資料庫網址，密碼位置是 `***`，主機是 RDS 端點。
- 日誌接著出現 tables are ready。
- 從這台 Mac（安全群組已放行家裡 IP）：`psql "$DATABASE_URL" -c 'select version();'`，版本是 PostgreSQL 16。
- 遷移腳本的對照表每一列都是 `OK`。
- 下一次排程快照的新列寫在 RDS，不是只寫在本機 `pg-data`。
- 跑一次 `./scripts/sync_raw_to_s3.sh`。每天 10:00 UTC 跑 `./scripts/pg_dump_to_s3.sh`。物件鍵是 `pg-dumps/<UTC 日期>.dump`。生命週期會在 90 天後刪除 `pg-dumps/` 裡的現行物件。腳本本身不刪舊檔。

本機 `pg-data` volume 再留兩週。

## 10. 回滾

後端還沒改指向 RDS：不要在 `.env` 設定 `DATABASE_URL`。`docker compose` 會繼續使用 `postgresql://novig:novig@postgres:5432/novig_nba`。

已經切換之後：從 `.env` 移除 `DATABASE_URL`（或改回上面那條 compose 網址），重啟 compose 後端。不要把 Mac 上的行程指到 `localhost:5432`，因為 compose 沒有發佈這個埠。切換之後才寫進 RDS 的列，不會自動回到 `pg-data`。若要救回本機，用同一支遷移腳本、對調兩條網址，而且客戶端必須是 PostgreSQL 16。`pg-data` 留到 RDS 穩定跑過兩週再刪。

## 11. EC2 後端（在這台 Mac 上操作）

英文說明在 [docs/deployment/aws.md](aws.md) 的 EC2 段。這裡只寫你在 Mac 上要下的指令。`terraform apply` 還是你自己跑。這份變更不會幫你呼叫 AWS。

順序要照下面。EC2 活著之後，才做最後一步把 RDS 收成私有。

1. 先 apply SPO-132 的 RDS 和 S3（上面第 4 到第 8 節），遷移完成。
2. 同一份 `infra/aws` 再 apply 這次的 EC2。
3. 把密鑰放進 SSM，第一次把程式拉上主機，Vercel 的 `BACKEND_API_URL` 指到 `http://<EIP>`。
4. 確認健康檢查和一筆真實讀取都打到 RDS 之後，另一次 apply 才把 RDS 改成私有。

### 變數

在 gitignore 的 `infra/aws/terraform.tfvars` 加上（值可以維持預設）：

```hcl
instance_type             = "t4g.small"
root_volume_gb            = 30
enable_ssh                = false
domain                    = ""
alarm_email               = ""
enable_github_deploy_role = false
```

`enable_ssh = false` 時 22 埠關閉。不要為了方便把它打開。要用 SSH 時才改成 `true`，而且只會放行 `allowed_cidrs` 裡的 `/32`。`domain` 先留空，Caddy 只提供 HTTP。

```bash
cd infra/aws
terraform init
terraform fmt -recursive
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
terraform output eip
terraform output instance_id
terraform output instance_role_arn
```

`plan` 和 `apply` 會打到 AWS。看完 plan 再 apply。

### 把密鑰放進 SSM SecureString

路徑是 `/sportslab/prod/<名稱>`，用預設的 `aws/ssm` 金鑰。不要寫進 git，不要貼進聊天。

在這台 Mac 產生一把給 Vercel rewrite 用的密鑰，直接送進 SSM，終端機不要把它印出來：

```bash
openssl rand -hex 32 | aws ssm put-parameter \
  --region us-east-2 \
  --name /sportslab/prod/VERCEL_PROXY_SECRET \
  --type SecureString \
  --value file:///dev/stdin
```

同一個值貼進 Vercel 專案的環境變數 `VERCEL_PROXY_SECRET`。前端的 rewrite 會把它放在標頭 `x-sportslab-proxy-secret`。後端只在這把密鑰對上時，才用 `x-real-ip`（沒有的話用 `x-forwarded-for` 最左邊那個）當速率限制的 key。

`PROXY_SECRET_REQUIRED` 預設是 false，本機不會擋請求。`deploy/docker-compose.prod.yml` 設成 `true`，而且這個值蓋過 `/etc/sportslab/backend.env`。正式環境除了 `GET /api/health` 和 `GET /health`，每個請求都要帶對的標頭，否則回 401。密鑰是空的也回 401，不會因為忘了放 SSM 就把 API 打開。健康檢查留著，是因為 compose 的 healthcheck 和 `deploy/remote-up.sh` 打 `/api/health` 時不帶這個標頭。

這件事對過 Frontend #63 的 `7c034de`。唯一打後端的地方是 `frontend/lib/api.ts`，它走同源的 `/api/backend/*`。`frontend/middleware.ts` 再把這條路徑轉到 `BACKEND_API_URL`，並帶上密鑰。沒有 `NEXT_PUBLIC` 的後端網址，也沒有 `EventSource`，所以瀏覽器不會自己打這支 API。

對不上密鑰時，限流 key 用的是 `request.client.host`。在這台主機上，uvicorn 的 `--proxy-headers` 會在進 key 函式之前，只在 TCP 對端正好是 Caddy `172.30.133.10` 時，用 `X-Forwarded-For` 改寫這個位址。Caddy 沒有 `trusted_proxies`，所以那個標頭是 Caddy 看到的 TCP 對端（Vercel 出口或直連的客戶端），不是 Caddy 容器自己的位址，客戶端也不能靠自己帶的 `X-Forwarded-For` 偽造。以後若加上 `trusted_proxies`，這條路徑要重看。不要用 Origin 標頭做登入。

其他參數用同樣的方式建立，名稱對環境變數：`DATABASE_URL`、`ODDS_API_KEY`、`OPENAI_API_KEY`、`SPORTSDATA_API_KEY`、`BALLDONTLIE_API_KEY`、`BOT_API_KEYS`、`BOT_API_KEYS_PREMIUM`、`CORS_ALLOWED_ORIGINS`、`CORS_ALLOWED_ORIGIN_REGEX`。

`DATABASE_URL` 要帶 `sslmode=verify-full`，`sslrootcert` 指到容器裡的 `/app/certs/global-bundle.pem`。主機第一次開機會把公開的 RDS CA 下載到 `/opt/sportslab/certs/global-bundle.pem`。

輪替 `VERCEL_PROXY_SECRET`：SSM 和 Vercel 都改成新值，然後讓後端重新載入（`deploy/pull-ssm-env.sh` 再 `docker compose up -d`）並重新部署前端，兩件事盡量接在一起。兩邊不一致的那段時間，健康檢查以外的請求會回 401。新值不要進 git 或聊天。

在有網域之前，Vercel 到 EC2 是明文 HTTP，這個標頭也走在那段路上。這是已知且接受的風險。

### 第一次部署

Session Manager，不開 22 埠：

```bash
aws ssm start-session --target "$(terraform output -raw instance_id)" --region us-east-2
```

在主機上（把 `<git-sha>` 換成要跑的 commit）：

```bash
sudo mkdir -p /opt/sportslab
sudo git clone https://github.com/eason034056/nba-player-stats-analysis.git /opt/sportslab/repo
cd /opt/sportslab/repo
sudo git fetch --depth 1 origin <git-sha>
sudo git checkout --detach --force FETCH_HEAD
sudo deploy/remote-up.sh <git-sha>
```

看到 `healthy` 就表示 Caddy 後面的 `/api/health` 過了。腳本不會印出密鑰。

Vercel 專案設定 `BACKEND_API_URL=http://<EIP>`，不要加路徑。`<EIP>` 是 `terraform output -raw eip`。

### 換網域

1. DNS 的 A 記錄指到 EIP。
2. `terraform.tfvars` 的 `domain` 改成主機名稱，不要加 `https://`。
3. 主機上的 `/etc/sportslab/caddy.env` 寫 `DOMAIN=那個名稱`。user data 只在第一次開機寫這個檔。
4. 重啟 compose。Caddy 會自己申請憑證。80 和 443 已經開放。
5. Vercel 的 `BACKEND_API_URL` 改成 `https://<domain>`，仍然不要加路徑。

在這之前，Vercel 伺服器轉送到 `http://<EIP>` 沒有 TLS。

### 把 RDS 收成私有（另外一步）

EC2 已經是唯一需要連資料庫的客戶之後，再改 `terraform.tfvars`：

```hcl
allowed_cidrs       = []
publicly_accessible = false
```

再 apply 一次。RDS 仍然允許 `sportslab-app`，所以主機上的後端還連得到。不要在主機還沒接上之前做這一步。做完之後不要再跑 `scripts/aws_update_my_ip.sh --apply`，那個參數會把家裡和 box 的 `/32` 加回來。

Mac 或 box 要連資料庫時，從 Session Manager 轉埠，不把 5432 開回你家的 IP：

```bash
aws ssm start-session \
  --target i-INSTANCE \
  --region us-east-2 \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["RDS主機名稱"],"portNumber":["5432"],"localPortNumber":["5432"]}'
```

然後連 `127.0.0.1:5432`。

### CORS 範例

正式站（等 SPO-134 有真實專案名稱再填）：`https://<project>.vercel.app`。

預覽站 regex 要涵蓋 `https://<project>-git-<branch>-<scope>.vercel.app` 和 `https://<project>-<hash>-<scope>.vercel.app`。範例：

```text
^https://sports-lab(-git-[a-z0-9-]+-team|-[a-z0-9]+-team)\.vercel\.app$
```

`sports-lab` 和 `team` 以後換成真實名稱。在那之前 regex 留空。不要填 `*`。

### 排程器與較大的機型

現在排程器跟 API 在同一個 Python 行程，機型維持 `t4g.small`。以後若要拆開，再加一個只跑排程器的容器，API 啟動時不要再啟動排程器，並把 `instance_type` 改成 `t4g.medium`（4 GiB）。不要在這台主機上 `docker build`。

### 費用估計

下面是 us-east-2、730 小時、on-demand、稅前的估計，不是帳單。價格表日期寫在英文文件的 EC2 段。重點：`t4g.small` 約 12.26 美元，30 GB gp3 約 2.40 美元，使用中的公網 IPv4 約 3.65 美元，CloudWatch 落在免費額度裡。這一台大約 18.3 到 19 美元。加上 SPO-132 大約 18 到 21 美元，兩份一起大約 36 到 40 美元。RDS 改成私有、拿掉它的公網 IPv4 之後，大約少 3.65 美元，變成大約 32 到 36 美元。不要假設帳戶還有 Free Tier。這是公開價目表的估計。

### GitHub 部署

`.github/workflows/deploy-backend.yml` 現在只有手動 `workflow_dispatch`。儲存庫變數 `DEPLOY_ENABLED` 不是 `true` 時，它會在建置之前停止。預設分支是 `master`，沒有 `main`。以後若要 push 到 `master` 就部署，在 workflow 的 `on` 加上 `push: branches: [master]`，並留著 `DEPLOY_ENABLED` 那個檢查。不要寫 `main`。

要讓它真的跑起來，還要：

- `enable_github_deploy_role = true` 並且 `github_repository = "eason034056/nba-player-stats-analysis"`，再 apply。
- 儲存庫變數 `AWS_DEPLOY_ROLE_ARN` 設成 `terraform output -raw github_deploy_role_arn`。
- 儲存庫變數 `AWS_REGION=us-east-2`、`EC2_INSTANCE_ID` 設成 instance id。
- `DEPLOY_ENABLED=true`。

Workflow 用 GitHub OIDC 擔任那個角色，不需要靜態 AWS 金鑰。第一次推上 GHCR 之後，把套件改成 public，主機才拉得到且不用 token。若套件維持 private，把 `GHCR_PULL_USER` 和 `GHCR_PULL_TOKEN` 放進 SSM，部署腳本會登入且不印出 token。
