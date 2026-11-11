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

# Percent-decode without putting the value on another program's argv.
urldecode() {
  local raw="$1" out="" hex char
  while [[ "$raw" == *%* ]]; do
    out="${out}${raw%%\%*}"
    raw="${raw#*%}"
    hex="${raw:0:2}"
    raw="${raw:2}"
    if [[ ! "$hex" =~ ^[0-9A-Fa-f][0-9A-Fa-f]$ ]]; then
      printf '%s' "${out}%${hex}${raw}"
      return 0
    fi
    printf -v char '%b' "\\x${hex}"
    out="${out}${char}"
  done
  printf '%s' "${out}${raw}"
}

# Put the DSN into libpq's environment, then pg_dump is started with no URL
# argument. PGPASSWORD=... on the same line would still show up in ps.
export_libpq() {
  local url="$1"
  local rest userinfo user pass after host port pathquery db query
  local pair key value sslmode="" sslrootcert=""
  rest="${url#*://}"
  userinfo="${rest%%@*}"
  after="${rest#*@}"
  if [[ "$userinfo" == *:* ]]; then
    user="${userinfo%%:*}"
    pass="${userinfo#*:}"
  else
    user="$userinfo"
    pass=""
  fi
  if [[ "$after" == \[* ]]; then
    host="${after#\[}"
    host="${host%%\]*}"
    local after_bracket="${after#*\]}"
    if [[ "$after_bracket" == :* ]]; then
      port="${after_bracket#:}"
      port="${port%%/*}"
    else
      port="5432"
    fi
    if [[ "$after" == */* ]]; then
      pathquery="${after#*/}"
    else
      pathquery=""
    fi
  else
    local hostport
    if [[ "$after" == */* ]]; then
      hostport="${after%%/*}"
      pathquery="${after#*/}"
    else
      hostport="$after"
      pathquery=""
    fi
    if [[ "$hostport" == *:* ]]; then
      host="${hostport%%:*}"
      port="${hostport##*:}"
    else
      host="$hostport"
      port="5432"
    fi
  fi
  db="${pathquery%%\?*}"
  if [[ "$pathquery" == *\?* ]]; then
    query="${pathquery#*\?}"
  else
    query=""
  fi
  if [[ -n "$query" ]]; then
    local IFS='&'
    # shellcheck disable=SC2086
    set -- $query
    IFS=' '
    for pair in "$@"; do
      key="${pair%%=*}"
      value="${pair#*=}"
      case "$key" in
        sslmode) sslmode="$(urldecode "$value")" ;;
        sslrootcert) sslrootcert="$(urldecode "$value")" ;;
      esac
    done
  fi
  export PGHOST="$host"
  export PGPORT="$port"
  export PGUSER="$(urldecode "$user")"
  export PGPASSWORD="$(urldecode "$pass")"
  export PGDATABASE="$db"
  if [[ -n "$sslmode" ]]; then
    export PGSSLMODE="$sslmode"
  else
    unset PGSSLMODE
  fi
  if [[ -n "$sslrootcert" ]]; then
    export PGSSLROOTCERT="$(urldecode "$sslrootcert")"
  else
    unset PGSSLROOTCERT
  fi
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

# BSD mktemp (macOS) only substitutes X characters at the end of the template.
tmp="$(mktemp "${TMPDIR:-/tmp}/sportslab-pgdump.XXXXXX")"
err="$(mktemp "${TMPDIR:-/tmp}/sportslab-pgdump-err.XXXXXX")"
# Invoked by the EXIT trap. shellcheck does not see that call.
# shellcheck disable=SC2317
cleanup() {
  rm -f "$tmp" "$err"
}
trap cleanup EXIT

export_libpq "$dump_url"
if ! "$PG_DUMP" -Fc --file "$tmp" 2>"$err"; then
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
