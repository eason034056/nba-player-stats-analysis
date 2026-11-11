#!/usr/bin/env bash
# Write one custom-format dump to s3://$S3_BUCKET/pg-dumps/<UTC date>.dump.
# The database URL is never printed.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  S3_BUCKET=... AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_REGION=... \
    RDS_DATABASE_URL=... ./scripts/pg_dump_to_s3.sh

pg_dump -Fc the database and upload the file to pg-dumps/<date>.dump.
The bucket lifecycle keeps each current object under pg-dumps/ for 90 days
(pg_dump_retention_days). This script does not delete older dumps.
RDS_DATABASE_URL is preferred. DATABASE_URL is used when RDS_DATABASE_URL
is unset. DUMP_DATE (YYYY-MM-DD) overrides the UTC date. PG_DUMP and AWS_CLI
override the binaries.

A PostgreSQL 17 client can dump a PostgreSQL 16 server. The v17
transaction_timeout warning applies to pg_restore, not to this dump.

If a required variable is missing, this script prints this help and exits
without dumping or uploading.
EOF
}

redact_file() {
  sed -E \
    -e 's#([a-zA-Z][a-zA-Z0-9+.-]*://[^[:space:]/@]+:)[^[:space:]@]+#\1***#g' \
    -e 's#([Pp]assword=)[^[:space:]]+#\1***#g' \
    "$1"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

dump_url="${RDS_DATABASE_URL:-${DATABASE_URL:-}}"

missing=()
[[ -z "${S3_BUCKET:-}" ]] && missing+=("S3_BUCKET")
[[ -z "${AWS_ACCESS_KEY_ID:-}" ]] && missing+=("AWS_ACCESS_KEY_ID")
[[ -z "${AWS_SECRET_ACCESS_KEY:-}" ]] && missing+=("AWS_SECRET_ACCESS_KEY")
[[ -z "${AWS_REGION:-}" ]] && missing+=("AWS_REGION")
[[ -z "$dump_url" ]] && missing+=("RDS_DATABASE_URL or DATABASE_URL")
if ((${#missing[@]} > 0)); then
  echo "error: missing required environment: ${missing[*]}" >&2
  echo "Dry run: pg_dump was not started and nothing was uploaded." >&2
  usage >&2
  exit 2
fi

dump_date="${DUMP_DATE:-$(date -u +%Y-%m-%d)}"
if [[ ! "$dump_date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "error: DUMP_DATE must be YYYY-MM-DD." >&2
  exit 2
fi

PG_DUMP="${PG_DUMP:-pg_dump}"
AWS_CLI="${AWS_CLI:-aws}"
key="pg-dumps/${dump_date}.dump"

export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-15}"
umask 077

tmp="$(mktemp --suffix=.dump)"
err="$(mktemp)"
cleanup() {
  rm -f "$tmp" "$err"
}
trap cleanup EXIT

if ! "$PG_DUMP" -Fc --dbname "$dump_url" --file "$tmp" 2>"$err"; then
  redact_file "$err" >&2
  echo "error: pg_dump failed. The connection string was not printed." >&2
  exit 1
fi

if ! "$AWS_CLI" s3 cp "$tmp" "s3://${S3_BUCKET}/${key}" 2>"$err"; then
  redact_file "$err" >&2
  echo "error: upload failed. The connection string was not printed." >&2
  exit 1
fi

echo "uploaded s3://${S3_BUCKET}/${key}"
