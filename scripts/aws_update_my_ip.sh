#!/usr/bin/env bash
# Update the Mac's public IP in the gitignored Terraform var file.
# The box CIDR stays. This script does not call AWS. terraform apply is
# printed for you to run, unless you pass --apply.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF_DIR="${TF_DIR:-${ROOT}/infra/aws}"
CURL_BIN="${CURL:-curl}"
TERRAFORM_BIN="${TERRAFORM:-terraform}"

usage() {
  cat <<EOF
Usage:
  ./scripts/aws_update_my_ip.sh
  ./scripts/aws_update_my_ip.sh --apply

Reads the current public IP from https://checkip.amazonaws.com (no AWS
credentials, no resource API). Prints that IP. Rewrites the gitignored
file \${TF_DIR}/terraform.tfvars: the "# mac-home" line is replaced, and
the "# box" line is left as it is. That line is where the real box /32
belongs. The tracked example uses a documentation address only.

By default it then prints the terraform apply command and exits. It does
not run terraform, so it makes no AWS call.

Pass --apply only when you want this script to launch terraform apply
for you. The only AWS calls in that mode are the ones terraform makes.

If terraform.tfvars does not exist yet, it is copied from
terraform.tfvars.example first. Never commit terraform.tfvars.

Optional environment:
  TF_DIR     directory that holds terraform.tfvars (default infra/aws)
  CURL       curl binary (default curl)
  TERRAFORM  terraform binary (default terraform)
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

apply=0
if [[ "${1:-}" == "--apply" ]]; then
  apply=1
elif [[ -n "${1:-}" ]]; then
  echo "error: unknown argument." >&2
  usage >&2
  exit 2
fi

if ! command -v "$CURL_BIN" >/dev/null 2>&1; then
  echo "error: curl not found." >&2
  usage >&2
  exit 2
fi

raw="$("$CURL_BIN" -fsS https://checkip.amazonaws.com || true)"
ip="$(printf '%s' "$raw" | tr -d '[:space:]')"
octet='(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])'
if [[ ! "$ip" =~ ^${octet}\.${octet}\.${octet}\.${octet}$ || "$ip" == "0.0.0.0" ]]; then
  echo "error: could not read a public IPv4 address. No file was changed and terraform was not started." >&2
  usage >&2
  exit 1
fi

echo "Current public IP: ${ip}"

example="${TF_DIR}/terraform.tfvars.example"
target="${TF_DIR}/terraform.tfvars"
if [[ ! -f "$target" ]]; then
  if [[ ! -f "$example" ]]; then
    echo "error: neither terraform.tfvars nor terraform.tfvars.example is in ${TF_DIR}." >&2
    exit 1
  fi
  cp "$example" "$target"
fi

if ! grep -q '# mac-home' "$target"; then
  echo "error: ${target} has no \"# mac-home\" line to replace. The box line was left unchanged." >&2
  exit 1
fi

tmp="$(mktemp)"
while IFS= read -r line || [[ -n "$line" ]]; do
  case "$line" in
    *"# mac-home"*)
      printf '  "%s/32", # mac-home\n' "$ip"
      ;;
    *)
      printf '%s\n' "$line"
      ;;
  esac
done < "$target" > "$tmp"
mv "$tmp" "$target"

echo "Updated ${target} (gitignored). The Mac CIDR is now ${ip}/32."
box_cidr="$(sed -n 's/.*"\([0-9][0-9.]*\/32\)".*# box.*/\1/p' "$target" | head -n 1)"
if [[ -z "$box_cidr" ]]; then
  echo "error: ${target} has no \"# box\" IPv4 /32. The mac-home line was updated. terraform was not started." >&2
  exit 1
fi
echo "Box CIDR kept: ${box_cidr}"
echo "No AWS call was made by this script."
echo "When you are ready, run:"
echo "  ${TERRAFORM_BIN} -chdir=${TF_DIR} apply -var-file=terraform.tfvars -var 'allowed_cidrs=[\"${box_cidr}\",\"${ip}/32\"]'"

if [[ "$apply" -eq 1 ]]; then
  echo "Starting terraform apply because --apply was passed."
  "$TERRAFORM_BIN" -chdir="$TF_DIR" apply \
    -var-file=terraform.tfvars \
    -var "allowed_cidrs=[\"${box_cidr}\",\"${ip}/32\"]"
fi
