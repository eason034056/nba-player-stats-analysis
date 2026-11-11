#!/bin/sh
# Pull the GHCR image and start compose on the host. Run from a checkout of this repo.
# Does not print secret values.
set -eu

tag="${1:?image tag required}"
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)

"$root/deploy/pull-ssm-env.sh"

if [ -f /etc/sportslab/ghcr.env ]; then
  python3 - <<'PY'
import os
import subprocess

path = "/etc/sportslab/ghcr.env"
values = {}
with open(path, encoding="utf-8") as handle:
    for line in handle:
        if not line.strip() or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.rstrip("\n")
user = values.get("GHCR_PULL_USER", "")
token = values.get("GHCR_PULL_TOKEN", "")
if not user or not token:
    raise SystemExit(0)
subprocess.run(
    ["docker", "login", "ghcr.io", "-u", user, "--password-stdin"],
    input=token.encode("utf-8"),
    stdout=subprocess.DEVNULL,
    check=True,
)
PY
fi

if [ -f /etc/sportslab/caddy.env ]; then
  set -a
  # shellcheck disable=SC1091
  . /etc/sportslab/caddy.env
  set +a
fi

if [ -z "${BACKEND_IMAGE:-}" ]; then
  export BACKEND_IMAGE="ghcr.io/eason034056/nba-player-stats-analysis/backend:${tag}"
fi
cd "$root"
docker compose -f deploy/docker-compose.prod.yml pull
docker compose -f deploy/docker-compose.prod.yml up -d --remove-orphans

i=0
while [ "$i" -lt 30 ]; do
  if curl -fsS http://127.0.0.1/api/health >/dev/null; then
    echo "healthy"
    exit 0
  fi
  i=$((i + 1))
  sleep 2
done
echo "health check failed" >&2
exit 1
