#!/usr/bin/env bash
# Dump the local database and restore it onto RDS, then compare public tables.
# Connection URLs are read from the environment and are never printed.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  LOCAL_DATABASE_URL=... RDS_DATABASE_URL=... ./scripts/db_migrate_to_rds.sh

Dumps the local database with pg_dump -Fc --no-owner --no-privileges and
restores it with pg_restore --no-owner --no-privileges --exit-on-error.
The RDS database should be empty. This script does not pass --clean.

Then, for every table in schema public, compares row count and max(id)
(when an id column exists). For every sequence in schema public, compares
last_value. Prints name|metric|local|rds|status and exits 1 on any mismatch.

pg_restore must be major version 16. A v17 client emits SET transaction_timeout,
which PostgreSQL 16 rejects. Set ALLOW_PG_RESTORE_MISMATCH=1 to warn and
continue anyway.

Required environment:
  LOCAL_DATABASE_URL    source DSN (not printed)
  RDS_DATABASE_URL      destination DSN (not printed)

Optional:
  PG_DUMP        pg_dump binary (default pg_dump)
  PG_RESTORE     pg_restore binary (default pg_restore)
  PSQL           psql binary (default psql)
  DUMP_PATH      keep the custom-format dump at this path (default: a temp file)
  ALLOW_PG_RESTORE_MISMATCH=1   warn instead of refusing a non-16 pg_restore

If a required variable is missing, this script prints this help and exits
without dumping or restoring.
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

if [[ -z "${LOCAL_DATABASE_URL:-}" || -z "${RDS_DATABASE_URL:-}" ]]; then
  echo "error: LOCAL_DATABASE_URL and RDS_DATABASE_URL are required." >&2
  echo "Dry run: no dump or restore was started." >&2
  usage >&2
  exit 2
fi

if [[ "$LOCAL_DATABASE_URL" == "$RDS_DATABASE_URL" ]]; then
  echo "error: LOCAL_DATABASE_URL and RDS_DATABASE_URL are the same. Refusing to restore a database onto itself." >&2
  exit 2
fi

PG_DUMP="${PG_DUMP:-pg_dump}"
PG_RESTORE="${PG_RESTORE:-pg_restore}"
PSQL="${PSQL:-psql}"

if [[ ! -x "$PG_RESTORE" ]] && ! command -v "$PG_RESTORE" >/dev/null 2>&1; then
  echo "error: pg_restore not found ($PG_RESTORE)." >&2
  exit 127
fi

version_line="$("$PG_RESTORE" --version 2>&1 || true)"
major="$(printf '%s\n' "$version_line" | sed -n 's/.* \([0-9]\{1,\}\)\.[0-9].*/\1/p' | head -n 1)"
if [[ "$major" != "16" ]]; then
  echo "warning: pg_restore major version is ${major:-unknown}, not 16. PostgreSQL 17 emits SET transaction_timeout, which PostgreSQL 16 rejects." >&2
  if [[ "${ALLOW_PG_RESTORE_MISMATCH:-}" != "1" ]]; then
    echo "error: refusing to restore. Install PostgreSQL 16 client tools, or set ALLOW_PG_RESTORE_MISMATCH=1 to continue anyway." >&2
    exit 3
  fi
  echo "warning: ALLOW_PG_RESTORE_MISMATCH=1 set; continuing with pg_restore ${major:-unknown}." >&2
fi

export PSQLRC=/dev/null
export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-15}"
umask 077

tmp_files=()
dump_file=""
cleanup() {
  local f
  for f in ${tmp_files[@]+"${tmp_files[@]}"}; do
    rm -f "$f"
  done
  if [[ -z "${DUMP_PATH:-}" && -n "$dump_file" ]]; then
    rm -f "$dump_file"
  fi
}
trap cleanup EXIT

run_psql() {
  local url="$1"
  shift
  local err
  err="$(mktemp)"
  tmp_files+=("$err")
  local out
  set +e
  out="$("$PSQL" "$url" "$@" 2>"$err")"
  local status=$?
  set -e
  if [[ "$status" -ne 0 ]]; then
    redact_file "$err" >&2
    return "$status"
  fi
  printf '%s\n' "$out"
}

if [[ -n "${DUMP_PATH:-}" ]]; then
  dump_file="$DUMP_PATH"
else
  dump_file="$(mktemp --suffix=.dump)"
fi

dump_err="$(mktemp)"
tmp_files+=("$dump_err")
if ! "$PG_DUMP" -Fc --no-owner --no-privileges --dbname "$LOCAL_DATABASE_URL" --file "$dump_file" 2>"$dump_err"; then
  redact_file "$dump_err" >&2
  echo "error: pg_dump failed. The connection string was not printed." >&2
  exit 1
fi

if ! "$PG_RESTORE" --no-owner --no-privileges --exit-on-error --dbname "$RDS_DATABASE_URL" "$dump_file" 2>"$dump_err"; then
  redact_file "$dump_err" >&2
  echo "error: pg_restore failed. The connection string was not printed." >&2
  exit 1
fi

list_tables() {
  run_psql "$1" -v ON_ERROR_STOP=1 -A -t -c \
    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name"
}

list_sequences() {
  run_psql "$1" -v ON_ERROR_STOP=1 -A -t -c \
    "SELECT sequencename FROM pg_sequences WHERE schemaname = 'public' ORDER BY sequencename"
}

contains_line() {
  local haystack="$1"
  local needle="$2"
  printf '%s\n' "$haystack" | grep -Fxq -- "$needle"
}

mismatch=0
report() {
  local name="$1"
  local metric="$2"
  local local_value="$3"
  local rds_value="$4"
  local status="OK"
  if [[ "$local_value" != "$rds_value" ]]; then
    status="MISMATCH"
    mismatch=1
  fi
  printf '%s|%s|%s|%s|%s\n' "$name" "$metric" "$local_value" "$rds_value" "$status"
}

local_tables="$(list_tables "$LOCAL_DATABASE_URL")"
rds_tables="$(list_tables "$RDS_DATABASE_URL")"
all_tables="$(printf '%s\n%s\n' "$local_tables" "$rds_tables" | sed '/^$/d' | sort -u)"

echo "name|metric|local|rds|status"

while IFS= read -r table; do
  [[ -z "$table" ]] && continue
  local_count="MISSING"
  rds_count="MISSING"
  local_ident=""
  rds_ident=""
  if contains_line "$local_tables" "$table"; then
    local_ident="$(run_psql "$LOCAL_DATABASE_URL" -v ON_ERROR_STOP=1 -v tbl="$table" -A -t -c "SELECT quote_ident(:'tbl')")"
    local_count="$(run_psql "$LOCAL_DATABASE_URL" -v ON_ERROR_STOP=1 -A -t -c "SELECT count(*) FROM public.${local_ident}")"
  fi
  if contains_line "$rds_tables" "$table"; then
    rds_ident="$(run_psql "$RDS_DATABASE_URL" -v ON_ERROR_STOP=1 -v tbl="$table" -A -t -c "SELECT quote_ident(:'tbl')")"
    rds_count="$(run_psql "$RDS_DATABASE_URL" -v ON_ERROR_STOP=1 -A -t -c "SELECT count(*) FROM public.${rds_ident}")"
  fi
  report "$table" "count" "$local_count" "$rds_count"

  if [[ "$local_count" == "MISSING" || "$rds_count" == "MISSING" ]]; then
    report "$table" "max_id" "$local_count" "$rds_count"
    continue
  fi

  local_has="$(run_psql "$LOCAL_DATABASE_URL" -v ON_ERROR_STOP=1 -v tbl="$table" -A -t -c "SELECT CASE WHEN EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :'tbl' AND column_name = 'id') THEN 't' ELSE 'f' END")"
  rds_has="$(run_psql "$RDS_DATABASE_URL" -v ON_ERROR_STOP=1 -v tbl="$table" -A -t -c "SELECT CASE WHEN EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :'tbl' AND column_name = 'id') THEN 't' ELSE 'f' END")"
  if [[ "$local_has" != "t" && "$rds_has" != "t" ]]; then
    continue
  fi
  local_max="n/a"
  rds_max="n/a"
  if [[ "$local_has" == "t" ]]; then
    local_max="$(run_psql "$LOCAL_DATABASE_URL" -v ON_ERROR_STOP=1 -A -t -c "SELECT COALESCE(max(id)::text, '') FROM public.${local_ident}")"
  fi
  if [[ "$rds_has" == "t" ]]; then
    rds_max="$(run_psql "$RDS_DATABASE_URL" -v ON_ERROR_STOP=1 -A -t -c "SELECT COALESCE(max(id)::text, '') FROM public.${rds_ident}")"
  fi
  report "$table" "max_id" "$local_max" "$rds_max"
done <<EOF
$all_tables
EOF

local_seqs="$(list_sequences "$LOCAL_DATABASE_URL")"
rds_seqs="$(list_sequences "$RDS_DATABASE_URL")"
all_seqs="$(printf '%s\n%s\n' "$local_seqs" "$rds_seqs" | sed '/^$/d' | sort -u)"

while IFS= read -r seq; do
  [[ -z "$seq" ]] && continue
  local_value="MISSING"
  rds_value="MISSING"
  if contains_line "$local_seqs" "$seq"; then
    local_value="$(run_psql "$LOCAL_DATABASE_URL" -v ON_ERROR_STOP=1 -v seq="$seq" -A -t -c "SELECT COALESCE(last_value::text, '') FROM pg_sequences WHERE schemaname = 'public' AND sequencename = :'seq'")"
  fi
  if contains_line "$rds_seqs" "$seq"; then
    rds_value="$(run_psql "$RDS_DATABASE_URL" -v ON_ERROR_STOP=1 -v seq="$seq" -A -t -c "SELECT COALESCE(last_value::text, '') FROM pg_sequences WHERE schemaname = 'public' AND sequencename = :'seq'")"
  fi
  report "$seq" "last_value" "$local_value" "$rds_value"
done <<EOF
$all_seqs
EOF

if [[ "$mismatch" -ne 0 ]]; then
  echo "error: at least one public table or sequence does not match." >&2
  exit 1
fi

echo "ok: public table counts, max(id), and sequence last_value match."
exit 0
