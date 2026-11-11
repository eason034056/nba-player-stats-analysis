#!/usr/bin/env bash
# Copy local Ball Don't Lie caches to S3. Never deletes remote objects.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  S3_BUCKET=... AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_REGION=... \
    ./scripts/sync_raw_to_s3.sh

Runs aws s3 sync (no --delete) for three directories:

  BDL_CACHE_DIR    default /workspace/bdl-cache           -> s3://$S3_BUCKET/bdl-raw/
  BDL_ARCHIVE_DIR  default /workspace/bdl-archive         -> s3://$S3_BUCKET/bdl-archive/
  BDL_SAMPLES_DIR  default /workspace/bdl-eval/samples    -> s3://$S3_BUCKET/bdl-samples/

Excludes *.pid, *.lock, __pycache__/*, and *.nohup.out.
AWS credentials are read by the AWS CLI from the environment and are not printed.

If a required variable is missing, this script prints this help and exits
without calling aws.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

missing=()
[[ -z "${S3_BUCKET:-}" ]] && missing+=("S3_BUCKET")
[[ -z "${AWS_ACCESS_KEY_ID:-}" ]] && missing+=("AWS_ACCESS_KEY_ID")
[[ -z "${AWS_SECRET_ACCESS_KEY:-}" ]] && missing+=("AWS_SECRET_ACCESS_KEY")
[[ -z "${AWS_REGION:-}" ]] && missing+=("AWS_REGION")
if ((${#missing[@]} > 0)); then
  echo "error: missing required environment: ${missing[*]}" >&2
  echo "Dry run: aws s3 sync was not started." >&2
  usage >&2
  exit 2
fi

cache_dir="${BDL_CACHE_DIR:-/workspace/bdl-cache}"
archive_dir="${BDL_ARCHIVE_DIR:-/workspace/bdl-archive}"
samples_dir="${BDL_SAMPLES_DIR:-/workspace/bdl-eval/samples}"
AWS_CLI="${AWS_CLI:-aws}"

sync_one() {
  local src="$1"
  local prefix="$2"
  if [[ ! -d "$src" ]]; then
    echo "error: source directory does not exist: $src" >&2
    return 1
  fi
  # No --delete. Versioning on the bucket keeps overwritten objects.
  "$AWS_CLI" s3 sync "$src" "s3://${S3_BUCKET}/${prefix}" \
    --exclude '*.pid' \
    --exclude '*.lock' \
    --exclude '__pycache__/*' \
    --exclude '*.nohup.out'
}

sync_one "$cache_dir" "bdl-raw/"
sync_one "$archive_dir" "bdl-archive/"
sync_one "$samples_dir" "bdl-samples/"

echo "synced bdl-raw/, bdl-archive/, and bdl-samples/ to s3://${S3_BUCKET}/"
