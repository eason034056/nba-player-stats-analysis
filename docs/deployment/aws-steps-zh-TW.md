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

`plan` 裡不該出現 `0.0.0.0/0`。如果 plan 停在 `no matching EC2 VPC found`，先看下一節，改完再 plan。apply 結束後記下 `db_endpoint`、`master_user_secret_arn`、`bucket_name`、`app_security_group_id`、`vpc_id`，以及 `public_subnet_ids`。

`app_security_group_id` 是 `sportslab-app` 這個安全群組。它現在沒有任何進站規則，是留給之後的 EC2 後端（SPO-133）掛上去用的。RDS 已經用安全群組 id 放行這個群組的 TCP 5432，也放行 `rds_allowed_security_group_ids` 裡的每一個 id（預設是空清單）。

EC2 後端上線、而且實例已經掛在 `sportslab-app` 之後，把 gitignore 的 `terraform.tfvars` 改成 `allowed_cidrs = []` 再 `terraform apply`。這樣 Mac 和 box 的 IP 規則會消失。RDS 仍然允許 `sportslab-app`。之後不要再跑 `./scripts/aws_update_my_ip.sh --apply`，因為 `--apply` 會把那兩個 `/32` 再傳回去。`0.0.0.0/0` 和 `::/0` 仍然會被拒絕。空清單是允許的。

`infra/aws/README.md` 裡的 provisioner IAM JSON 是舊計畫的對照清單。不要照它去建立另一把金鑰。

## If your account has no default VPC

帳號沒有 default VPC 時，`vpc_id` 沒寫，`terraform plan` 會停在這個錯誤：

```text
Error: no matching EC2 VPC found
```

這表示 Terraform 在這個 region 找不到 default VPC。先列出 VPC。指令印出的 id 不要 commit。

```bash
aws ec2 describe-vpcs --query 'Vpcs[].{id:VpcId,cidr:CidrBlock,default:IsDefault,name:Tags[?Key==`Name`]|[0].Value}' --output table
```

選一個 VPC，確認兩件事。下面的 `vpc-0123456789abcdef0` 只是佔位，換成上一行印出的 id。

主路由表要有一條 `0.0.0.0/0`，目標是 `igw-` 開頭的網際網路閘道：

```bash
aws ec2 describe-route-tables \
  --filters Name=vpc-id,Values=vpc-0123456789abcdef0 \
  --query 'RouteTables[?Associations[?Main]].{id:RouteTableId,defaultRoute:Routes[?DestinationCidrBlock==`0.0.0.0/0`].GatewayId}' \
  --output table
```

子網的 `MapPublicIpOnLaunch` 要是 true。RDS 的 subnet group 仍使用該 VPC 的全部子網。`public_subnet_ids` 是其中會自動配發公開 IPv4 的子網，SPO-133 會用來放 EC2。

```bash
aws ec2 describe-subnets \
  --filters Name=vpc-id,Values=vpc-0123456789abcdef0 \
  --query 'Subnets[].{id:SubnetId,az:AvailabilityZone,public:MapPublicIpOnLaunch,cidr:CidrBlock}' \
  --output table
```

在 gitignore 的 `terraform.tfvars` 加上（換成你的 id）：

```hcl
vpc_id = "vpc-0123456789abcdef0"
```

再跑一次 `terraform plan`。不要 commit `terraform.tfvars`。帳號有 default VPC 時，不要寫 `vpc_id`。空字串不是「沒設定」，驗證會拒絕 `""`。

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

若 restore 之後的檢查失敗，用 `--verify-only` 再跑一次。它不會再 dump 或 restore，只比較資料表筆數、`max(id)` 和 sequence 的 `last_value`。任一邊的 public 資料表是 0 張時，腳本 exit 1，不印 `ok:`。錯誤訊息只有兩邊的張數。sequence 兩邊都是 0 才算通過，因為資料庫可以沒有 sequence。

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
