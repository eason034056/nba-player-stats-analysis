"""QA: migrate --verify-only compares every table in every client mode.

Runs the real scripts/db_migrate_to_rds.sh against a real Postgres. The
docker-exec and docker-run modes go through a stand-in `docker` that
copies the caller's stdin into the child the way `docker exec -i` /
`docker run -i` do, so a loop whose name list sits on stdin loses names.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from tests.test_spo132c_migrate_verify import (
    _admin_url,
    _assert_no_secrets,
    _psql,
    _redact,
    _verify,
    _which_psql,
    _with_database,
)

_DB_NAME = re.compile(r"^spo132dqa_(src|dst)_[0-9a-f]{8}$")

_SCHEMA = """
CREATE TABLE alpha_table (id serial PRIMARY KEY, v integer NOT NULL);
INSERT INTO alpha_table (v) VALUES (1);
CREATE TABLE beta_table (id serial PRIMARY KEY, v integer NOT NULL);
INSERT INTO beta_table (v) VALUES (1), (2);
CREATE TABLE "-c" (id serial PRIMARY KEY, v integer NOT NULL);
INSERT INTO "-c" (v) VALUES (3);
CREATE TABLE zeta_last (id serial PRIMARY KEY, v integer NOT NULL);
INSERT INTO zeta_last (v) VALUES (1), (2), (3);
CREATE SEQUENCE extra_seq START WITH 5;
SELECT nextval('extra_seq');
"""

_EXPECTED_OK = [
    "-c|count|1|1|OK",
    "alpha_table|count|1|1|OK",
    "beta_table|count|2|2|OK",
    "beta_table|max_id|2|2|OK",
    "zeta_last|count|3|3|OK",
    "zeta_last|max_id|3|3|OK",
    "extra_seq|last_value|5|5|OK",
]

# Copies stdin into the child like docker -i: it reads to EOF whether or
# not the child reads. Supports the exec and run shapes the script uses.
_DOCKER_SHIM = r"""#!/usr/bin/env python3
import os
import subprocess
import sys
import threading


def main(argv):
    if not argv or argv[0] not in ("exec", "run"):
        sys.stderr.write("unsupported docker command\n")
        return 2
    run = argv[0] == "run"
    args = argv[1:]
    env = os.environ.copy()
    interactive = False
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-i", "--interactive"):
            interactive = True
            i += 1
            continue
        if a == "--rm":
            i += 1
            continue
        if a in ("-e", "--env", "--network", "-v"):
            if a in ("-e", "--env"):
                spec = args[i + 1]
                if "=" in spec:
                    k, v = spec.split("=", 1)
                    env[k] = v
            i += 2
            continue
        if a.startswith("-"):
            sys.stderr.write("unsupported docker flag " + a + "\n")
            return 2
        break
    i += 1  # container name (exec) or image (run)
    cmd = args[i:]
    if not cmd:
        return 2
    if not interactive:
        return subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL).returncode
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, env=env)

    def copy_in():
        try:
            while True:
                chunk = os.read(0, 65536)
                if not chunk:
                    break
                try:
                    proc.stdin.write(chunk)
                    proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

    threading.Thread(target=copy_in, daemon=True).start()
    return proc.wait()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
"""

# Host-mode psql wrapper that fails one chosen query on the target DB.
_FAILING_PSQL = r"""#!/usr/bin/env bash
if [[ "${PGDATABASE:-}" == "$QA_FAIL_DB" ]]; then
  for a in "$@"; do
    if [[ "$a" == *"$QA_FAIL_MATCH"* ]]; then
      echo "psql: error: QA injected failure" >&2
      exit 2
    fi
  done
fi
exec "$QA_REAL_PSQL" "$@"
"""


class _Pair:
    def __init__(self, psql: str, admin: str, names: list[str]) -> None:
        self.psql = psql
        self.admin = admin
        self.password = urlsplit(admin).password or ""
        self.names = names
        self.source = _with_database(admin, names[0])
        self.target = _with_database(admin, names[1])

    def on_target(self, sql: str) -> None:
        done = _psql(self.psql, self.target, sql)
        if done.returncode != 0:
            raise AssertionError(_redact(done.stderr, [self.target, self.password]))


def _make_pair(schema: str) -> Iterator[_Pair]:
    psql = _which_psql()
    admin = _admin_url()
    if _psql(psql, admin, "SELECT 1").returncode != 0:
        pytest.skip("Postgres is not reachable; migrate verify was not run")
    suffix = os.urandom(4).hex()
    names = [f"spo132dqa_src_{suffix}", f"spo132dqa_dst_{suffix}"]
    created: list[str] = []
    password = urlsplit(admin).password or ""
    try:
        for name in names:
            if _DB_NAME.fullmatch(name) is None:
                raise AssertionError("scratch database name is not a safe identifier")
            made = _psql(psql, admin, f"CREATE DATABASE {name}")
            if made.returncode != 0:
                raise AssertionError(_redact(made.stderr, [admin, password]))
            created.append(name)
            if schema:
                loaded = _psql(psql, _with_database(admin, name), schema)
                if loaded.returncode != 0:
                    raise AssertionError(_redact(loaded.stderr, [admin, password]))
        yield _Pair(psql, admin, names)
    finally:
        for name in created:
            _psql(psql, admin, f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


@pytest.fixture
def pair() -> Iterator[_Pair]:
    yield from _make_pair(_SCHEMA)


@pytest.fixture
def empty_pair() -> Iterator[_Pair]:
    yield from _make_pair("")


def _mode_env(mode: str, tmp_path: Path, psql: str) -> dict[str, str]:
    if mode == "host":
        return {"PG_CLIENT": "host", "PSQL": psql}
    docker = tmp_path / "docker"
    docker.write_text(_DOCKER_SHIM)
    docker.chmod(0o755)
    # sh -c 'exec psql ...' inside the stand-in resolves psql on PATH.
    psql_dir = str(Path(psql).parent)
    return {
        "PATH": f"{tmp_path}:{psql_dir}:{os.environ.get('PATH', '')}",
        "PG_CLIENT": mode,
        "LOCAL_PG_CONTAINER": "fake-pg",
    }


_MODES = ["host", "docker-exec", "docker-run"]


def _run(
    pair: _Pair, env: dict[str, str]
) -> tuple[subprocess.CompletedProcess[str], str]:
    result = _verify(pair.source, pair.target, extra_env=env)
    combined = result.stdout + result.stderr
    _assert_no_secrets(combined, [pair.admin, pair.source, pair.target], pair.password)
    return result, _redact(combined, [pair.source, pair.target, pair.password])


@pytest.mark.parametrize("mode", _MODES)
def test_matching_databases_report_every_table(
    mode: str, pair: _Pair, tmp_path: Path
) -> None:
    result, shown = _run(pair, _mode_env(mode, tmp_path, pair.psql))
    assert result.returncode == 0, shown
    for line in _EXPECTED_OK:
        assert line in result.stdout, shown
    assert "MISMATCH" not in result.stdout
    assert "ok:" in result.stdout


@pytest.mark.parametrize("mode", _MODES)
def test_count_mismatch_in_the_last_table_fails(
    mode: str, pair: _Pair, tmp_path: Path
) -> None:
    pair.on_target("DELETE FROM zeta_last WHERE id = 1;")
    result, shown = _run(pair, _mode_env(mode, tmp_path, pair.psql))
    assert result.returncode == 1, shown
    assert "zeta_last|count|3|2|MISMATCH" in result.stdout, shown
    assert "alpha_table|count|1|1|OK" in result.stdout, shown
    assert "ok:" not in result.stdout


@pytest.mark.parametrize("mode", _MODES)
def test_max_id_only_mismatch_fails(mode: str, pair: _Pair, tmp_path: Path) -> None:
    # Same row count, different max(id).
    pair.on_target(
        "DELETE FROM beta_table WHERE id = 2; INSERT INTO beta_table (id, v) VALUES (9, 2);"
    )
    result, shown = _run(pair, _mode_env(mode, tmp_path, pair.psql))
    assert result.returncode == 1, shown
    assert "beta_table|count|2|2|OK" in result.stdout, shown
    assert "beta_table|max_id|2|9|MISMATCH" in result.stdout, shown
    assert "zeta_last|count|3|3|OK" in result.stdout, shown
    assert "ok:" not in result.stdout


@pytest.mark.parametrize("mode", _MODES)
def test_sequence_mismatch_fails(mode: str, pair: _Pair, tmp_path: Path) -> None:
    pair.on_target("SELECT setval('extra_seq', 42);")
    result, shown = _run(pair, _mode_env(mode, tmp_path, pair.psql))
    assert result.returncode == 1, shown
    assert "extra_seq|last_value|5|42|MISMATCH" in result.stdout, shown
    assert "zeta_last|count|3|3|OK" in result.stdout, shown
    assert "ok:" not in result.stdout


@pytest.mark.parametrize("mode", _MODES)
def test_table_missing_on_target_fails(mode: str, pair: _Pair, tmp_path: Path) -> None:
    pair.on_target("DROP TABLE zeta_last;")
    result, shown = _run(pair, _mode_env(mode, tmp_path, pair.psql))
    assert result.returncode == 1, shown
    assert "zeta_last|count|3|MISSING|MISMATCH" in result.stdout, shown
    assert "ok:" not in result.stdout


@pytest.mark.parametrize(
    "match",
    [
        "information_schema.tables",  # table listing on the target
        "FROM public.zeta_last",  # count/max on the last table
        "pg_sequences WHERE schemaname = 'public' ORDER BY",  # sequence listing
    ],
)
def test_a_failing_query_on_the_target_is_not_reported_as_a_match(
    match: str, pair: _Pair, tmp_path: Path
) -> None:
    wrapper = tmp_path / "psql"
    wrapper.write_text(_FAILING_PSQL)
    wrapper.chmod(0o755)
    env = {
        "PG_CLIENT": "host",
        "PSQL": str(wrapper),
        "QA_REAL_PSQL": pair.psql,
        "QA_FAIL_DB": pair.names[1],
        "QA_FAIL_MATCH": match,
    }
    result, shown = _run(pair, env)
    assert result.returncode != 0, shown
    assert "ok:" not in result.stdout, shown
    assert "QA injected failure" in result.stderr, shown


@pytest.mark.xfail(
    strict=True,
    reason="should-fix: zero public tables on both sides still prints ok and exits 0",
)
def test_empty_public_schema_on_both_sides_is_not_ok(
    empty_pair: _Pair, tmp_path: Path
) -> None:
    result, shown = _run(empty_pair, _mode_env("host", tmp_path, empty_pair.psql))
    assert result.returncode != 0, shown
    assert "ok:" not in result.stdout
