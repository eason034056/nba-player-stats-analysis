# SPO-132b — 沒有 default VPC 的帳號

- Ticket: SPO-132b
- Branch: `feature/SPO-132b-optional-vpc-id`（從 `origin/dev`）
- Base: `dev`

## Summary

`infra/aws` 的 `data "aws_vpc" "default" { default = true }` 在沒有 default VPC 的帳號會失敗，錯誤是 `no matching EC2 VPC found`。這張票加上可選的 `vpc_id`。不設時仍找該 region 的 default VPC。設了就用那個 VPC。安全群組和 RDS subnet group 改讀同一組 local。SPO-133 之後會用 `public_subnet_ids` 放 EC2。這次沒有呼叫 AWS，也沒有 plan 或 apply。

## Changes

| 範圍 | 檔案 | 變更 |
|---|---|---|
| 變數 | `infra/aws/variables.tf` | `variable "vpc_id"`，型別 `string`，預設 `null`。驗證是 `var.vpc_id == null \|\| can(regex("^vpc-[0-9a-f]{8,17}$", var.vpc_id))`。空字串不當成 null，會被拒絕。 |
| 網路 | `infra/aws/network.tf` | 單一資料來源 `data "aws_vpc" "selected"`：`id = var.vpc_id`，`default = var.vpc_id == null ? true : null`。`aws_subnets.selected` 用這個 VPC。另加 `aws_subnets.public`，同一 VPC 再加上 `map-public-ip-on-launch = true`。local `vpc_id`、`subnet_ids`、`public_subnet_ids`。兩個安全群組的 `vpc_id` 和 subnet group 的 `subnet_ids` 改用這些 local。subnet group 的 description 不再寫 Default VPC。 |
| 輸出 | `infra/aws/outputs.tf` | 新增 `vpc_id`、`public_subnet_ids`。 |
| 範例 | `infra/aws/terraform.tfvars.example` | 註解掉的 `# vpc_id = "vpc-0123456789abcdef0"`。說明不設就用 default VPC，並附上列出 VPC 的指令。 |
| 文件 | `infra/aws/README.md`、`docs/deployment/aws.md`、`docs/deployment/aws-steps-zh-TW.md` | 各加一節 `If your account has no default VPC`：錯誤長什麼樣子、怎麼查 VPC、路由表和子網、把 `vpc_id` 寫進 gitignore 的 `terraform.tfvars`、再跑 plan。繁中步驟寫在 zh-TW 那份。 |
| 測試 | `backend/tests/test_spo132b_optional_vpc.py` | 讀檔檢查變數、條件式 `default`、local、範例裡只有佔位 id。不呼叫 AWS。 |
| 摘要 | `docs/task-summaries/SPO-132b-optional-vpc-id.md` | 本檔。 |

## Why

AWS provider 5.100.0 的 `aws_vpc` data source 把 `id` 和 `default` 都標成 Optional。`default` 為 true 時才加 `isDefault=true` 過濾；null 在 Terraform 裡等於沒寫這個參數，provider 讀到的布林是 false，不會加那條過濾。`id` 有值時用 `VpcIds`。所以一個 data source 就夠：`vpc_id` 是 null 時只留 `default = true`，有 id 時只留 `id`。兩個同時設會要求那個 id 本身也是 default VPC，沒有 default VPC 的帳號還是會失敗。

空字串不合併成 null。`var.vpc_id == null` 對 `""` 是 false，條件式會把 `default` 也設成 null；provider 的 `GetOk` 又把空的 `id` 當成沒設。兩個條件都不成立時，查詢沒有 VPC id 也沒有 default 過濾。驗證直接拒絕 `""`、`subnet-123`、`vpc-XYZ`。

資料來源改名不會改 managed resource 的位址。`network.tf` 裡的 resource 仍是 `aws_db_subnet_group.this`、`aws_security_group.app`、`aws_security_group.rds`。安全群組的 `vpc_id` 和 `name`、`description` 在 provider 5.100.0 是 ForceNew；這次沒改 `name` 和安全群組的 `description`。`vpc_id` 在沒設變數時仍是同一種查詢（`isDefault=true`），default VPC 帳號算出來的 id 字串不變，所以不會因為改名而被替換。subnet group 的 ForceNew 只有 `name` 和 `name_prefix`，這兩個沒改。`subnet_ids` 不是 ForceNew；沒設 `vpc_id` 時清單仍是同一個 VPC 的全部子網。description 從「Default VPC subnets ...」改成「Subnets for ...」，這個欄位可以就地更新。VPC 與子網的 data source 改名成 `selected`，並多了 public 子網清單。這三個是 data source，不是 managed resource。這次沒有跑 `terraform plan`，所以上面是依 provider schema 和表達式，不是依一份 plan diff。

`public_subnet_ids` 由 SPO-133 的 EC2 使用 `try(sort(...)[0], null)`。空清單不會丟 Invalid index。多這個 data source 不會改 RDS 的 name 或 subnet_ids。

範例和文件裡的 `vpc-0123456789abcdef0` 是佔位，不是帳號裡的 VPC。

## Tests / Verification

- 後端 pytest：`cd backend && /tmp/nba-venv/bin/python -m pytest -q --tb=line` → 1308 passed、27 skipped、6 xfailed、0 failed。其中 `tests/test_spo132b_optional_vpc.py` 是這張票的讀檔測試。
- 前端：沒改。
- Integration test: SKIPPED。沒有 AWS 呼叫，沒有 `RUN_INTEGRATION`。
- Fabrication scan: PASS。沒有手寫的外部 API 回應。
- Terraform 1.9.8、provider hashicorp/aws v5.100.0。`terraform fmt -check -recursive` 乾淨。`terraform init -backend=false` 成功。`terraform validate`：Success! The configuration is valid.
- `terraform console`（另給 `bucket_name` 與 `allowed_cidrs` 佔位，沒有呼叫 AWS）：`vpc_id=vpc-0123456789abcdef0` 印出 `"vpc-0123456789abcdef0"`，沒有錯誤。不設 `vpc_id` 印出 `tostring(null)`，也就是 null。`subnet-123`、`vpc-XYZ`、`""` 都印 `Error: Invalid value for variable`，訊息是驗證的 error_message。Terraform 1.9 的 console 在變數驗證失敗後仍會把那個值印出來，行程結束碼仍是 0；拒絕的依據是 stderr 的 Error，不是結束碼。沒有把 `""` 收成 null。沒有 `terraform plan`，沒有 `terraform apply`。

## Follow-ups

- [ ] Eason 在自己的機器上，對沒有 default VPC 的帳號把 `vpc_id` 寫進 gitignore 的 `terraform.tfvars`，確認主路由表的 `0.0.0.0/0` 指向 `igw-`，而且子網 `MapPublicIpOnLaunch=true`，然後自己 plan。不要把真實 VPC id commit。
- [ ] SPO-133 用 `public_subnet_ids` 放後端 EC2，並掛上 `app_security_group_id`。
- [ ] 有 default VPC 的帳號不要設 `vpc_id`。設了另一個 VPC 會換掉安全群組的 `vpc_id`，那個欄位是 ForceNew，安全群組會被重建。
