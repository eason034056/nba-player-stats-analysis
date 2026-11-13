#!/bin/sh
# Copy SSM SecureStrings under /sportslab/prod/ into an env file.
# Parameter values are never written to stdout or stderr.
set -eu

prefix="${SSM_PREFIX:-/sportslab/prod/}"
dest="${SPORTSLAB_ENV_FILE:-/etc/sportslab/backend.env}"
ghcr_dest="${SPORTSLAB_GHCR_ENV_FILE:-/etc/sportslab/ghcr.env}"
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-2}}"
aws_cli="${AWS_CLI:-aws}"

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
umask 077

SSM_PREFIX="$prefix" \
AWS_REGION="$region" \
AWS_CLI="$aws_cli" \
SPORTSLAB_ENV_FILE="$dest" \
SPORTSLAB_GHCR_ENV_FILE="$ghcr_dest" \
python3 - <<'PY'
import json
import os
import stat
import subprocess
import sys

prefix = os.environ["SSM_PREFIX"]
region = os.environ["AWS_REGION"]
aws = os.environ.get("AWS_CLI", "aws")
dest = os.environ["SPORTSLAB_ENV_FILE"]
ghcr_dest = os.environ["SPORTSLAB_GHCR_ENV_FILE"]
ghcr_keys = {"GHCR_PULL_USER", "GHCR_PULL_TOKEN"}

params = []
token = None
while True:
    cmd = [
        aws,
        "ssm",
        "get-parameters-by-path",
        "--path",
        prefix,
        "--recursive",
        "--with-decryption",
        "--region",
        region,
        "--output",
        "json",
    ]
    if token:
        cmd.extend(["--next-token", token])
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        sys.stderr.write(
            f"ssm get-parameters-by-path failed (exit {proc.returncode})\n"
        )
        sys.exit(proc.returncode or 1)
    try:
        payload = json.loads(proc.stdout.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        sys.stderr.write("ssm get-parameters-by-path returned invalid json\n")
        sys.exit(1)
    params.extend(payload.get("Parameters") or [])
    token = payload.get("NextToken") or None
    if not token:
        break

app_lines = []
ghcr_lines = []
for item in params:
    name = str(item.get("Name") or "")
    key = name.rstrip("/").split("/")[-1]
    if not key or not key.replace("_", "A").isalnum() or key[0].isdigit():
        sys.stderr.write(f"rejected parameter name {name}\n")
        sys.exit(1)
    value = item.get("Value")
    if not isinstance(value, str) or "\n" in value or "\x00" in value:
        sys.stderr.write(f"rejected parameter name {name}\n")
        sys.exit(1)
    line = f"{key}={value}\n"
    if key in ghcr_keys:
        ghcr_lines.append(line)
    else:
        app_lines.append(line)

if not app_lines:
    sys.stderr.write(f"no parameters under {prefix}\n")
    sys.exit(1)


def write_private(path, lines):
    parent = os.path.dirname(path)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    os.chmod(parent, 0o700)
    tmp_path = path + ".tmp"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.writelines(lines)
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, path)
    os.chmod(path, 0o600)
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode != 0o600:
        sys.stderr.write(f"env file mode is {oct(mode)}, expected 0600\n")
        sys.exit(1)


write_private(dest, app_lines)
if ghcr_lines:
    write_private(ghcr_dest, ghcr_lines)
elif os.path.exists(ghcr_dest):
    os.remove(ghcr_dest)
PY
