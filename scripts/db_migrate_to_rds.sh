#!/usr/bin/env bash
# Dump the local database and restore it onto RDS, then compare public tables.
# Connection URLs are read from the environment and are never printed.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  LOCAL_DATABASE_URL=... RDS_DATABASE_URL=... ./scripts/db_migrate_to_rds.sh
  ./scripts/db_migrate_to_rds.sh --pg-client docker-exec --local-container no-vig-nba-postgres

Dumps the local database with pg_dump -Fc --no-owner --no-privileges and
restores it with pg_restore --no-owner --no-privileges --exit-on-error.
The RDS database should be empty. This script does not pass --clean.
If RDS_DATABASE_URL has no sslmode, restore and the RDS checks use
sslmode=require. An existing sslmode (including verify-full) is kept.

Then, for every table in schema public, compares row count and max(id)
(when an id column exists). For every sequence in schema public, compares
last_value. Prints name|metric|local|rds|status and exits 1 on any mismatch.

pg_restore must be major version 16. A v17 client emits SET transaction_timeout,
which PostgreSQL 16 rejects. Set ALLOW_PG_RESTORE_MISMATCH=1 to warn and
continue anyway.

Client mode (PG_CLIENT, or --pg-client):
  docker-exec   default. pg_dump inside the local Postgres container.
                Container name: LOCAL_PG_CONTAINER or --local-container.
                Default no-vig-nba-postgres (docker-compose.yml container_name).
  docker-run    fallback. throwaway `docker run --rm postgres:16` for
                pg_dump and pg_restore, so the client major version is 16.
                Dump joins the database container's network. Restore uses
                the image's own network so it can reach RDS.
  host          use PG_DUMP, PG_RESTORE, and PSQL on the host.

Required environment:
  LOCAL_DATABASE_URL    source DSN (not printed)
  RDS_DATABASE_URL      destination DSN (not printed)

Optional:
  LOCAL_PG_CONTAINER   default no-vig-nba-postgres
  PG_DOCKER_IMAGE      default postgres:16 (docker-run only)
  PG_DUMP, PG_RESTORE, PSQL   host-mode binaries
  DUMP_PATH            keep the custom-format dump at this path
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

# Copy a libpq URL into PGHOST/PGUSER/PGPASSWORD/PGDATABASE/PGSSLMODE.
# Callers then run pg_dump, pg_restore, or psql with no URL argument, so the
# password is not on the process command line. Do not prefix the command with
# PGPASSWORD=...; that prefix is also visible in the process list.
export_libpq() {
  local url="$1"
  local rest userinfo user pass after host port hostport pathquery db query
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
    if [[ "$after_bracket" == :*/* || "$after_bracket" == :* ]]; then
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
  PGHOST="$host"
  PGPORT="$port"
  PGUSER="$(urldecode "$user")"
  PGPASSWORD="$(urldecode "$pass")"
  PGDATABASE="$db"
  export PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE
  if [[ -n "$sslmode" ]]; then
    PGSSLMODE="$sslmode"
    export PGSSLMODE
  else
    unset PGSSLMODE
  fi
  if [[ -n "$sslrootcert" ]]; then
    PGSSLROOTCERT="$(urldecode "$sslrootcert")"
    export PGSSLROOTCERT
  else
    unset PGSSLROOTCERT
  fi
}

# Add sslmode=require when the URL has none. Never print the result.
with_sslmode_require() {
  local url="$1"
  if printf '%s' "$url" | grep -q 'sslmode='; then
    printf '%s' "$url"
  elif printf '%s' "$url" | grep -q '?'; then
    printf '%s&sslmode=require' "$url"
  else
    printf '%s?sslmode=require' "$url"
  fi
}

LOCAL_PG_CONTAINER="${LOCAL_PG_CONTAINER:-no-vig-nba-postgres}"
PG_DOCKER_IMAGE="${PG_DOCKER_IMAGE:-postgres:16}"
PG_CLIENT="${PG_CLIENT:-docker-exec}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --local-container)
      if [[ $# -lt 2 ]]; then
        echo "error: --local-container needs a container name." >&2
        exit 2
      fi
      LOCAL_PG_CONTAINER="$2"
      shift 2
      ;;
    --pg-client)
      if [[ $# -lt 2 ]]; then
        echo "error: --pg-client needs host, docker-exec, or docker-run." >&2
        exit 2
      fi
      PG_CLIENT="$2"
      shift 2
      ;;
    *)
      echo "error: unknown argument." >&2
      usage >&2
      exit 2
      ;;
  esac
done

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

case "$PG_CLIENT" in
  host|docker-exec|docker-run) ;;
  *)
    echo "error: PG_CLIENT must be host, docker-exec, or docker-run." >&2
    exit 2
    ;;
esac

PG_DUMP="${PG_DUMP:-pg_dump}"
PG_RESTORE="${PG_RESTORE:-pg_restore}"
PSQL="${PSQL:-psql}"

if [[ "$PG_CLIENT" == "host" ]]; then
  if [[ ! -x "$PG_RESTORE" ]] && ! command -v "$PG_RESTORE" >/dev/null 2>&1; then
    echo "error: pg_restore not found ($PG_RESTORE)." >&2
    exit 127
  fi
elif ! command -v docker >/dev/null 2>&1; then
  echo "error: docker not found. Install Docker, or set PG_CLIENT=host." >&2
  exit 127
fi

client_version_line() {
  case "$PG_CLIENT" in
    host) "$PG_RESTORE" --version 2>&1 || true ;;
    docker-exec) docker exec "$LOCAL_PG_CONTAINER" pg_restore --version 2>&1 || true ;;
    docker-run) docker run --rm "$PG_DOCKER_IMAGE" pg_restore --version 2>&1 || true ;;
  esac
}

version_line="$(client_version_line)"
major="$(printf '%s\n' "$version_line" | sed -n 's/.* \([0-9]\{1,\}\)\.[0-9].*/\1/p' | head -n 1)"
if [[ "$major" != "16" ]]; then
  echo "warning: pg_restore major version is ${major:-unknown}, not 16. PostgreSQL 17 emits SET transaction_timeout, which PostgreSQL 16 rejects." >&2
  if [[ "${ALLOW_PG_RESTORE_MISMATCH:-}" != "1" ]]; then
    echo "error: refusing to restore. Use the Postgres 16 container (docker-exec or docker-run), or set ALLOW_PG_RESTORE_MISMATCH=1 to continue anyway." >&2
    exit 3
  fi
  echo "warning: ALLOW_PG_RESTORE_MISMATCH=1 set; continuing with pg_restore ${major:-unknown}." >&2
fi

export PSQLRC=/dev/null
export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-15}"
umask 077

local_url="$LOCAL_DATABASE_URL"
rds_url="$(with_sslmode_require "$RDS_DATABASE_URL")"

tmp_files=()
dump_file=""
# Invoked by the EXIT trap. shellcheck does not see that call.
# shellcheck disable=SC2317
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
  local out status
  set +e
  case "$PG_CLIENT" in
    host)
      export_libpq "$url"
      out="$("$PSQL" "$@" 2>"$err")"
      status=$?
      ;;
    docker-exec)
      export PSQL_TARGET="$url"
      out="$(docker exec -e PSQL_TARGET -i "$LOCAL_PG_CONTAINER" sh -c 'exec psql "$PSQL_TARGET" "$@"' psql "$@" 2>"$err")"
      status=$?
      ;;
    docker-run)
      export PSQL_TARGET="$url"
      if [[ "$url" == "$local_url" ]]; then
        out="$(docker run --rm --network "container:${LOCAL_PG_CONTAINER}" -e PSQL_TARGET -i "$PG_DOCKER_IMAGE" sh -c 'exec psql "$PSQL_TARGET" "$@"' psql "$@" 2>"$err")"
      else
        out="$(docker run --rm -e PSQL_TARGET -i "$PG_DOCKER_IMAGE" sh -c 'exec psql "$PSQL_TARGET" "$@"' psql "$@" 2>"$err")"
      fi
      status=$?
      ;;
  esac
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
  # BSD mktemp (macOS) only substitutes X characters at the end of the template.
  dump_file="$(mktemp "${TMPDIR:-/tmp}/sportslab-migrate.XXXXXX")"
fi

dump_err="$(mktemp)"
tmp_files+=("$dump_err")
dump_base="$(basename "$dump_file")"
dump_dir="$(dirname "$dump_file")"
container_dump="/tmp/sportslab-migrate.dump"

dump_ok=0
case "$PG_CLIENT" in
  host)
    export_libpq "$local_url"
    if "$PG_DUMP" -Fc --no-owner --no-privileges --file "$dump_file" 2>"$dump_err"; then
      dump_ok=1
    fi
    ;;
  docker-exec)
    if docker exec -e LOCAL_DATABASE_URL "$LOCAL_PG_CONTAINER" \
      sh -c 'pg_dump -Fc --no-owner --no-privileges --dbname "$LOCAL_DATABASE_URL" --file /tmp/sportslab-migrate.dump' \
      2>"$dump_err" \
      && docker cp "${LOCAL_PG_CONTAINER}:${container_dump}" "$dump_file" 2>>"$dump_err"; then
      docker exec "$LOCAL_PG_CONTAINER" rm -f "$container_dump" 2>>"$dump_err" || true
      dump_ok=1
    fi
    ;;
  docker-run)
    if docker run --rm --network "container:${LOCAL_PG_CONTAINER}" -e LOCAL_DATABASE_URL \
      -v "${dump_dir}:/dump" "$PG_DOCKER_IMAGE" \
      sh -c "pg_dump -Fc --no-owner --no-privileges --dbname \"\$LOCAL_DATABASE_URL\" --file /dump/${dump_base}" \
      2>"$dump_err"; then
      dump_ok=1
    fi
    ;;
esac
if [[ "$dump_ok" -ne 1 ]]; then
  redact_file "$dump_err" >&2
  echo "error: pg_dump failed. The connection string was not printed." >&2
  exit 1
fi

export RDS_RESTORE_URL="$rds_url"
restore_ok=0
case "$PG_CLIENT" in
  host)
    export_libpq "$rds_url"
    if "$PG_RESTORE" --no-owner --no-privileges --exit-on-error "$dump_file" 2>"$dump_err"; then
      restore_ok=1
    fi
    ;;
  docker-exec)
    if docker cp "$dump_file" "${LOCAL_PG_CONTAINER}:${container_dump}" 2>"$dump_err" \
      && docker exec -e RDS_RESTORE_URL "$LOCAL_PG_CONTAINER" \
        sh -c 'pg_restore --no-owner --no-privileges --exit-on-error --dbname "$RDS_RESTORE_URL" /tmp/sportslab-migrate.dump' \
        2>>"$dump_err"; then
      docker exec "$LOCAL_PG_CONTAINER" rm -f "$container_dump" 2>>"$dump_err" || true
      restore_ok=1
    fi
    ;;
  docker-run)
    if docker run --rm -e RDS_RESTORE_URL -v "${dump_dir}:/dump:ro" "$PG_DOCKER_IMAGE" \
      sh -c "pg_restore --no-owner --no-privileges --exit-on-error --dbname \"\$RDS_RESTORE_URL\" /dump/${dump_base}" \
      2>"$dump_err"; then
      restore_ok=1
    fi
    ;;
esac
if [[ "$restore_ok" -ne 1 ]]; then
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

local_tables="$(list_tables "$local_url")"
rds_tables="$(list_tables "$rds_url")"
all_tables="$(printf '%s\n%s\n' "$local_tables" "$rds_tables" | sed '/^$/d' | sort -u)"

echo "name|metric|local|rds|status"

while IFS= read -r table; do
  [[ -z "$table" ]] && continue
  local_count="MISSING"
  rds_count="MISSING"
  local_ident=""
  rds_ident=""
  if contains_line "$local_tables" "$table"; then
    local_ident="$(run_psql "$local_url" -v ON_ERROR_STOP=1 -v tbl="$table" -A -t -c "SELECT quote_ident(:'tbl')")"
    local_count="$(run_psql "$local_url" -v ON_ERROR_STOP=1 -A -t -c "SELECT count(*) FROM public.${local_ident}")"
  fi
  if contains_line "$rds_tables" "$table"; then
    rds_ident="$(run_psql "$rds_url" -v ON_ERROR_STOP=1 -v tbl="$table" -A -t -c "SELECT quote_ident(:'tbl')")"
    rds_count="$(run_psql "$rds_url" -v ON_ERROR_STOP=1 -A -t -c "SELECT count(*) FROM public.${rds_ident}")"
  fi
  report "$table" "count" "$local_count" "$rds_count"

  if [[ "$local_count" == "MISSING" || "$rds_count" == "MISSING" ]]; then
    report "$table" "max_id" "$local_count" "$rds_count"
    continue
  fi

  local_has="$(run_psql "$local_url" -v ON_ERROR_STOP=1 -v tbl="$table" -A -t -c "SELECT CASE WHEN EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :'tbl' AND column_name = 'id') THEN 't' ELSE 'f' END")"
  rds_has="$(run_psql "$rds_url" -v ON_ERROR_STOP=1 -v tbl="$table" -A -t -c "SELECT CASE WHEN EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :'tbl' AND column_name = 'id') THEN 't' ELSE 'f' END")"
  if [[ "$local_has" != "t" && "$rds_has" != "t" ]]; then
    continue
  fi
  local_max="n/a"
  rds_max="n/a"
  if [[ "$local_has" == "t" ]]; then
    local_max="$(run_psql "$local_url" -v ON_ERROR_STOP=1 -A -t -c "SELECT COALESCE(max(id)::text, '') FROM public.${local_ident}")"
  fi
  if [[ "$rds_has" == "t" ]]; then
    rds_max="$(run_psql "$rds_url" -v ON_ERROR_STOP=1 -A -t -c "SELECT COALESCE(max(id)::text, '') FROM public.${rds_ident}")"
  fi
  report "$table" "max_id" "$local_max" "$rds_max"
done <<EOF
$all_tables
EOF

local_seqs="$(list_sequences "$local_url")"
rds_seqs="$(list_sequences "$rds_url")"
all_seqs="$(printf '%s\n%s\n' "$local_seqs" "$rds_seqs" | sed '/^$/d' | sort -u)"

while IFS= read -r seq; do
  [[ -z "$seq" ]] && continue
  local_value="MISSING"
  rds_value="MISSING"
  if contains_line "$local_seqs" "$seq"; then
    local_value="$(run_psql "$local_url" -v ON_ERROR_STOP=1 -v seq="$seq" -A -t -c "SELECT COALESCE(last_value::text, '') FROM pg_sequences WHERE schemaname = 'public' AND sequencename = :'seq'")"
  fi
  if contains_line "$rds_seqs" "$seq"; then
    rds_value="$(run_psql "$rds_url" -v ON_ERROR_STOP=1 -v seq="$seq" -A -t -c "SELECT COALESCE(last_value::text, '') FROM pg_sequences WHERE schemaname = 'public' AND sequencename = :'seq'")"
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
