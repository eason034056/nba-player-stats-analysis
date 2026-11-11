# 在 Mac 上把 Sports Lab 接到 AWS（繁體中文步驟）

英文版與環境變數說明在 [docs/deployment/aws.md](aws.md)。這份只寫 Eason 在自己的 Mac 上要做的事。

後端跑在這台 Mac。Postgres 跑在同一台 Mac 的 Docker 裡，容器名稱是 `no-vig-nba-postgres`（映像 `postgres:16-alpine`，`docker-compose.yml` 沒有把 5432 發佈到 Mac 本身）。這台 Mac 沒有部署到任何主機，也沒有固定 IP，家裡的對外 IP 會變。AWS 帳號已經存在。`terraform apply` 由 Eason 自己執行。不要建立 provisioner 使用者，也不要把任何金鑰貼到 repo 或聊天裡。

允許連上 RDS 5432 的位址只有兩個 `/32`：固定的 box `184.193.214.44/32`，以及這台 Mac 目前的對外 IP。每天一份的 `pg-dumps/` 保留 90 天。

## 1. 用 Homebrew 安裝工具

```bash
brew install terraform awscli
brew install --cask docker
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

帳號已經存在。這一步是檢查，不是把帳號升級成 Paid。

1. 打開 AWS Console → Billing。看目前的方案，以及最近幾個月的帳單。
2. 再建一個每月 25 美元的預算。實際花費到 80% 寄信，預測花費到 100% 也寄信。收件人用你自己的信箱。

## 4. terraform init、plan、apply

在 repo 根目錄：

```bash
cd infra/aws
cp terraform.tfvars.example terraform.tfvars
```

編輯 `terraform.tfvars`（這個檔已被 gitignore，不要 commit）：

- `bucket_name` 換成全域唯一的名稱，例如 `sportslab-data-<帳號編號>-us-east-2`。
- `allowed_cidrs` 保留 `184.193.214.44/32` 那一行（註解是 `# box`）。
- 把 `# mac-home` 那一行的 `203.0.113.10` 換成這台 Mac 現在的對外 IP。`203.0.113.10` 只是文件用的佔位，不是真的位址。

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

`plan` 裡不該出現 `0.0.0.0/0`。apply 結束後記下三個輸出：`db_endpoint`、`master_user_secret_arn`、`bucket_name`。

`infra/aws/README.md` 裡的 provisioner IAM JSON 是舊計畫的對照清單。不要照它去建立另一把金鑰。

## 5. 家裡 IP 變了就更新允許清單

在 repo 根目錄：

```bash
./scripts/aws_update_my_ip.sh
```

腳本會：

1. 用 `curl` 讀 `https://checkip.amazonaws.com`，把 IP 印出來。這不是 AWS 資源 API，也不使用你的金鑰。
2. 改寫 gitignore 的 `infra/aws/terraform.tfvars`：只換 `# mac-home` 那一行，`184.193.214.44/32` 維持不動。
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
  --region us-east-2
```

密碼只留在這台 Mac 的終端機記憶裡。不要貼到聊天、不要寫進 git。Terraform 不會把這組密碼寫進輸出。

接著用 SQL 建立應用程式角色 `sportslab_app`（Terraform 不建立這個角色）。後端用這個角色，不用 master。

## 7. 用 docker exec 把本機資料庫搬到 RDS

先停掉會寫入本機資料庫的後端，避免搬移過程中筆數對不上。

`5432` 沒有發佈到 Mac，所以不要在 Mac 上直接跑 `pg_dump` 去連 `localhost:5432`。預設路徑是進到容器裡執行 `pg_dump`。在容器裡面，`localhost:5432` 就是這顆 Postgres。

在 repo 根目錄（把密碼和端點換成上一步的值；指令列會含有密碼，不要把這行貼出去）：

```bash
LOCAL_DATABASE_URL='postgresql://novig:novig@localhost:5432/novig_nba' \
RDS_DATABASE_URL='postgresql://sportslab_admin:PASSWORD@ENDPOINT:5432/novig_nba' \
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

`.env` 已被 gitignore。下載 RDS CA（`global-bundle.pem`），路徑要是後端行程讀得到的路徑。

```bash
DATABASE_URL=postgresql://sportslab_app:APP_PASSWORD@ENDPOINT:5432/novig_nba?sslmode=verify-full&sslrootcert=/絕對路徑/global-bundle.pem
DATABASE_REQUIRED=true
```

第一次確認成功之後再把 `DATABASE_REQUIRED` 設成 `true`。設成 `true` 時，資料庫連不上，後端會停止，而不是繼續提供沒有資料庫的 API。

若後端是用 `docker compose` 啟動，`DATABASE_URL` 會覆寫 compose 裡的本機預設值 `postgresql://novig:novig@postgres:5432/novig_nba`。CA 檔要掛進後端容器，或把 `sslrootcert` 指到容器內看得到的路徑。

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
