"""SPO-132c: --verify-only against a real Postgres 16 server.

The test creates two scratch databases, compares them with the migrate
script, then changes one row count. It skips when psql is missing or the
server is not reachable. CI installs the client and provides Postgres.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from shutil import which
from urllib.parse import urlsplit, urlunsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATE = ROOT / "scripts" / "db_migrate_to_rds.sh"
_CI_URL = "postgresql://novig:novig@localhost:5432/novig_nba"
_DB_NAME = re.compile(r"^spo132c_(src|dst)_[0-9a-f]{8}$")
_SCHEMA = """
CREATE TABLE "Game Log" (
  id serial PRIMARY KEY,
  points integer NOT NULL
);
INSERT INTO "Game Log" (points) VALUES (10), (12);
CREATE TABLE "MixedCase" (
  id serial PRIMARY KEY,
  v integer NOT NULL
);
INSERT INTO "MixedCase" (v) VALUES (1), (2);
CREATE TABLE "Weird""Quote" (
  id serial PRIMARY KEY,
  v integer NOT NULL
);
INSERT INTO "Weird""Quote" (v) VALUES (9);
CREATE SEQUENCE extra_seq START WITH 5;
SELECT nextval('extra_seq');
CREATE SEQUENCE "odd's_seq" START WITH 7;
SELECT nextval(pg_catalog.quote_ident('odd''s_seq'));
CREATE SCHEMA other;
CREATE TABLE other.hidden (id serial PRIMARY KEY, v integer NOT NULL);
INSERT INTO other.hidden (v) VALUES (1), (2), (3);
"""
_DELETE_ONE = 'DELETE FROM "Game Log" WHERE id = (SELECT min(id) FROM "Game Log");'


def _admin_url() -> str:
    raw = os.environ.get("DATABASE_URL", "").strip() or _CI_URL
    if raw.startswith("postgresql+asyncpg://"):
        return "postgresql://" + raw[len("postgresql+asyncpg://") :]
    if raw.startswith("postgres+asyncpg://"):
        return "postgresql://" + raw[len("postgres+asyncpg://") :]
    if raw.startswith("postgres://"):
        return "postgresql://" + raw[len("postgres://") :]
    return raw


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    query = parts.query
    if "sslmode=" not in query:
        query = f"{query}&sslmode=disable" if query else "sslmode=disable"
    return urlunsplit((parts.scheme, parts.netloc, f"/{database}", query, ""))


def _redact(text: str, secrets: list[str]) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "***")
    return re.sub(r"[a-zA-Z][a-zA-Z0-9+.-]*://\S+", "<url>", redacted)


def _psql(psql: str, url: str, sql: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [psql, url, "-v", "ON_ERROR_STOP=1", "-A", "-t"],
        input=sql,
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "PGCONNECT_TIMEOUT": "5",
        },
    )


def _assert_no_secrets(text: str, urls: list[str], password: str) -> None:
    leaked: list[str] = []
    for url in urls:
        if url and url in text:
            leaked.append("url")
    if "postgresql://" in text or "postgres://" in text:
        leaked.append("url-scheme")
    if password and password in text:
        leaked.append("password")
    assert not leaked, _redact(text, [*urls, password])


def test_verify_only_matches_then_reports_a_count_mismatch() -> None:
    psql = _which_psql()
    admin = _admin_url()
    probe = _psql(psql, admin, "SELECT 1")
    if probe.returncode != 0:
        pytest.skip("Postgres is not reachable; migrate verify was not run")

    password = urlsplit(admin).password or ""
    suffix = os.urandom(4).hex()
    names = [f"spo132c_src_{suffix}", f"spo132c_dst_{suffix}"]
    created: list[str] = []
    try:
        for name in names:
            if _DB_NAME.fullmatch(name) is None:
                raise AssertionError("scratch database name is not a safe identifier")
            created_db = _psql(psql, admin, f"CREATE DATABASE {name}")
            if created_db.returncode != 0:
                raise AssertionError(_redact(created_db.stderr, [admin, password]))
            created.append(name)
            loaded = _psql(psql, _with_database(admin, name), _SCHEMA)
            if loaded.returncode != 0:
                raise AssertionError(_redact(loaded.stderr, [admin, password]))

        source = _with_database(admin, names[0])
        target = _with_database(admin, names[1])
        matched = _verify(source, target)
        combined = matched.stdout + matched.stderr
        assert matched.returncode == 0, _redact(combined, [source, target, password])
        assert "MISMATCH" not in matched.stdout
        assert "Game Log|count|2|2|OK" in matched.stdout
        assert "Game Log|max_id|2|2|OK" in matched.stdout
        assert "MixedCase|count|2|2|OK" in matched.stdout
        assert "MixedCase|max_id|2|2|OK" in matched.stdout
        assert 'Weird"Quote|count|1|1|OK' in matched.stdout
        assert 'Weird"Quote|max_id|1|1|OK' in matched.stdout
        assert "extra_seq|last_value|5|5|OK" in matched.stdout
        assert "Game Log_id_seq|last_value|2|2|OK" in matched.stdout
        assert "odd's_seq|last_value|7|7|OK" in matched.stdout
        assert "ok:" in matched.stdout
        assert "hidden" not in matched.stdout
        _assert_no_secrets(combined, [admin, source, target], password)

        deleted = _psql(psql, target, _DELETE_ONE)
        if deleted.returncode != 0:
            raise AssertionError(_redact(deleted.stderr, [target, password]))
        mismatched = _verify(source, target)
        mismatched_text = mismatched.stdout + mismatched.stderr
        assert mismatched.returncode != 0, _redact(mismatched_text, [source, target, password])
        assert "Game Log|count|2|1|MISMATCH" in mismatched.stdout
        _assert_no_secrets(mismatched_text, [admin, source, target], password)
    finally:
        for name in created:
            _psql(psql, admin, f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


def _which_psql() -> str:
    found = which("psql")
    if found is None:
        pytest.skip("psql is not installed; migrate verify was not run")
    return found


def _verify(
    source: str,
    target: str,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PG_CLIENT": "host",
        "LOCAL_DATABASE_URL": source,
        "RDS_DATABASE_URL": target,
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(MIGRATE), "--verify-only"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_verify_only_connection_failure_is_not_reported_as_a_match() -> None:
    _which_psql()
    source = "postgresql://novig:novig@127.0.0.1:1/spo132c_src?sslmode=disable"
    target = "postgresql://novig:novig@127.0.0.1:1/spo132c_dst?sslmode=disable"
    result = _verify(source, target)
    combined = result.stdout + result.stderr
    assert result.returncode != 0, _redact(combined, [source, target], "novig")
    assert "ok:" not in combined
    _assert_no_secrets(combined, [source, target], "novig")


_DOCKER_STDIN_SHIM = r"""#!/usr/bin/env python3
import os
import subprocess
import sys
import threading


def main(argv: list[str]) -> int:
    if not argv or argv[0] != "exec":
        sys.stderr.write("unsupported docker command\n")
        return 2
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
        if a in ("-e", "--env"):
            i += 1
            if i >= len(args):
                return 2
            spec = args[i]
            if "=" in spec:
                key, value = spec.split("=", 1)
                env[key] = value
            i += 1
            continue
        if a.startswith("-"):
            sys.stderr.write("unsupported docker flag\n")
            return 2
        break
    if i >= len(args):
        return 2
    i += 1
    cmd = args[i:]
    if not cmd:
        return 2
    if not interactive:
        return subprocess.run(cmd, env=env).returncode
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=sys.stdout.fileno(),
        stderr=sys.stderr.fileno(),
        env=env,
    )

    def copy_in() -> None:
        try:
            assert proc.stdin is not None
            while True:
                chunk = os.read(0, 65536)
                if not chunk:
                    proc.stdin.close()
                    return
                proc.stdin.write(chunk)
                proc.stdin.flush()
        except (BrokenPipeError, OSError):
            try:
                if proc.stdin:
                    proc.stdin.close()
            except OSError:
                pass

    threading.Thread(target=copy_in, daemon=True).start()
    return proc.wait()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
"""


def test_verify_only_docker_exec_reports_a_mismatch_on_the_second_table(
    tmp_path: Path,
) -> None:
    """Default docker-exec must compare every public table.

    docker exec -i copies the caller's stdin. If run_psql uses -i for
    -c queries inside the table-name loop, later tables are skipped and
    a mismatch can exit 0.
    """
    psql = _which_psql()
    admin = _admin_url()
    probe = _psql(psql, admin, "SELECT 1")
    if probe.returncode != 0:
        pytest.skip("Postgres is not reachable; migrate verify was not run")

    password = urlsplit(admin).password or ""
    suffix = os.urandom(4).hex()
    names = [f"spo132c_src_{suffix}", f"spo132c_dst_{suffix}"]
    created: list[str] = []
    docker = tmp_path / "docker"
    docker.write_text(_DOCKER_STDIN_SHIM)
    docker.chmod(0o755)
    two_tables = """
CREATE TABLE first_table (id serial PRIMARY KEY, v integer NOT NULL);
INSERT INTO first_table (v) VALUES (1);
CREATE TABLE second_table (id serial PRIMARY KEY, v integer NOT NULL);
INSERT INTO second_table (v) VALUES (1), (2);
CREATE SEQUENCE extra_seq START WITH 4;
SELECT nextval('extra_seq');
"""
    try:
        for name in names:
            if _DB_NAME.fullmatch(name) is None:
                raise AssertionError("scratch database name is not a safe identifier")
            created_db = _psql(psql, admin, f"CREATE DATABASE {name}")
            if created_db.returncode != 0:
                raise AssertionError(_redact(created_db.stderr, [admin, password]))
            created.append(name)
            loaded = _psql(psql, _with_database(admin, name), two_tables)
            if loaded.returncode != 0:
                raise AssertionError(_redact(loaded.stderr, [admin, password]))

        source = _with_database(admin, names[0])
        target = _with_database(admin, names[1])
        deleted = _psql(
            psql,
            target,
            "DELETE FROM second_table WHERE id = (SELECT max(id) FROM second_table);",
        )
        if deleted.returncode != 0:
            raise AssertionError(_redact(deleted.stderr, [target, password]))
        result = _verify(
            source,
            target,
            extra_env={
                "PATH": f"{tmp_path}:{os.environ.get('PATH', '')}",
                "PG_CLIENT": "docker-exec",
                "LOCAL_PG_CONTAINER": "fake-pg",
                "PSQL": psql,
            },
        )
        combined = result.stdout + result.stderr
        assert result.returncode != 0, _redact(combined, [source, target, password])
        assert "first_table|count|1|1|OK" in result.stdout
        assert "second_table|count|2|1|MISMATCH" in result.stdout
        assert "extra_seq|last_value|4|4|OK" in result.stdout
        _assert_no_secrets(combined, [admin, source, target], password)
    finally:
        for name in created:
            _psql(psql, admin, f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


_DOCKER_SCHEMA = """
CREATE TABLE alpha_table (id serial PRIMARY KEY, v integer NOT NULL);
INSERT INTO alpha_table (v) VALUES (1);
CREATE TABLE beta_table (id serial PRIMARY KEY, v integer NOT NULL);
INSERT INTO beta_table (v) VALUES (1), (2);
CREATE TABLE gamma_table (id serial PRIMARY KEY, v integer NOT NULL);
INSERT INTO gamma_table (v) VALUES (7);
CREATE SEQUENCE extra_seq START WITH 5;
SELECT nextval('extra_seq');
"""


def _docker_ready() -> bool:
    if which("docker") is None:
        return False
    probe = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.returncode == 0


def _wait_postgres(container: str) -> None:
    for _ in range(40):
        ready = subprocess.run(
            [
                "docker",
                "exec",
                container,
                "pg_isready",
                "-h",
                "127.0.0.1",
                "-p",
                "5432",
                "-U",
                "novig",
                "-d",
                "novig",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if ready.returncode == 0:
            return
        time.sleep(0.5)
    raise AssertionError(f"{container} did not become ready")


def _docker_psql(container: str, sql: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "psql",
            "-U",
            "novig",
            "-d",
            "novig",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input=sql,
        capture_output=True,
        text=True,
        check=False,
    )


def test_verify_only_real_docker_exec_compares_every_table() -> None:
    """docker exec into Postgres 16 must compare every public table.

    Host mode is covered separately and does not skip when docker is
    missing. This case skips only when the docker client cannot run.
    """
    if not _docker_ready():
        pytest.skip(
            "docker is not available; docker-exec verify against Postgres was not run"
        )

    password = "spo132d-docker-pw"
    suffix = os.urandom(3).hex()
    network = f"spo132d{suffix}"
    source_name = f"spo132dsrc{suffix}"
    target_name = f"spo132ddst{suffix}"
    created: list[str] = []
    network_created = False
    try:
        made = subprocess.run(
            ["docker", "network", "create", network],
            capture_output=True,
            text=True,
            check=False,
        )
        if made.returncode != 0:
            raise AssertionError(made.stderr.strip() or "docker network create failed")
        network_created = True
        for name in (source_name, target_name):
            started = subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    name,
                    "--network",
                    network,
                    "-e",
                    "POSTGRES_USER=novig",
                    "-e",
                    f"POSTGRES_PASSWORD={password}",
                    "-e",
                    "POSTGRES_DB=novig",
                    "postgres:16",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if started.returncode != 0:
                detail = started.stderr.replace(password, "***")
                raise AssertionError(detail.strip() or "docker run failed")
            created.append(name)
        for name in created:
            _wait_postgres(name)
            loaded = _docker_psql(name, _DOCKER_SCHEMA)
            if loaded.returncode != 0:
                raise AssertionError(loaded.stderr.replace(password, "***"))

        source = f"postgresql://novig:{password}@127.0.0.1:5432/novig?sslmode=disable"
        target = (
            f"postgresql://novig:{password}@{target_name}:5432/novig?sslmode=disable"
        )
        matched = _verify(
            source,
            target,
            extra_env={
                "PG_CLIENT": "docker-exec",
                "LOCAL_PG_CONTAINER": source_name,
            },
        )
        combined = matched.stdout + matched.stderr
        assert matched.returncode == 0, _redact(combined, [source, target], password)
        assert "MISMATCH" not in matched.stdout
        assert "alpha_table|count|1|1|OK" in matched.stdout
        assert "beta_table|count|2|2|OK" in matched.stdout
        assert "gamma_table|count|1|1|OK" in matched.stdout
        assert "extra_seq|last_value|5|5|OK" in matched.stdout
        assert "ok:" in matched.stdout
        _assert_no_secrets(combined, [source, target], password)

        deleted = _docker_psql(
            target_name,
            "DELETE FROM beta_table WHERE id = (SELECT max(id) FROM beta_table);",
        )
        if deleted.returncode != 0:
            raise AssertionError(deleted.stderr.replace(password, "***"))
        mismatched = _verify(
            source,
            target,
            extra_env={
                "PG_CLIENT": "docker-exec",
                "LOCAL_PG_CONTAINER": source_name,
            },
        )
        mismatched_text = mismatched.stdout + mismatched.stderr
        assert mismatched.returncode != 0, _redact(
            mismatched_text, [source, target], password
        )
        assert "alpha_table|count|1|1|OK" in mismatched.stdout
        assert "beta_table|count|2|1|MISMATCH" in mismatched.stdout
        assert "gamma_table|count|1|1|OK" in mismatched.stdout
        assert "extra_seq|last_value|5|5|OK" in mismatched.stdout
        _assert_no_secrets(mismatched_text, [source, target], password)
    finally:
        if created:
            subprocess.run(
                ["docker", "rm", "-f", *created],
                capture_output=True,
                check=False,
            )
        if network_created:
            subprocess.run(
                ["docker", "network", "rm", network],
                capture_output=True,
                check=False,
            )


_DOCKER_TCP_READY_SHIM = r"""#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path


def _targets_tcp(argv: list[str]) -> bool:
    for index, arg in enumerate(argv):
        if arg == "-h" and index + 1 < len(argv) and argv[index + 1] == "127.0.0.1":
            return True
        if arg.startswith("-h") and arg[2:] == "127.0.0.1":
            return True
    return False


def main(argv: list[str]) -> int:
    state_path = Path(os.environ["SPO132F_STATE"])
    ready_on = int(os.environ["SPO132F_TCP_READY_ON"])
    state = json.loads(state_path.read_text())
    if "pg_isready" not in argv:
        sys.stderr.write("unsupported docker command\n")
        return 2
    if _targets_tcp(argv):
        state["tcp_calls"] = int(state.get("tcp_calls", 0)) + 1
        state["tcp_ready"] = state["tcp_calls"] >= ready_on
        state_path.write_text(json.dumps(state))
        return 0 if state["tcp_ready"] else 1
    state["socket_calls"] = int(state.get("socket_calls", 0)) + 1
    state_path.write_text(json.dumps(state))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
"""


def _install_tcp_ready_shim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    ready_on: int,
) -> Path:
    docker = tmp_path / "docker"
    docker.write_text(_DOCKER_TCP_READY_SHIM)
    docker.chmod(0o755)
    state = tmp_path / "pg-ready.json"
    state.write_text(
        json.dumps({"tcp_calls": 0, "socket_calls": 0, "tcp_ready": False})
    )
    monkeypatch.setenv("SPO132F_STATE", str(state))
    monkeypatch.setenv("SPO132F_TCP_READY_ON", str(ready_on))
    monkeypatch.setenv(
        "PATH",
        f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
    )
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    return state


def test_wait_postgres_does_not_return_until_tcp_is_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Socket pg_isready is already ready. Return only after TCP is ready."""
    state_path = _install_tcp_ready_shim(tmp_path, monkeypatch, ready_on=3)
    _wait_postgres("pg-tcp")
    state = json.loads(state_path.read_text())
    assert state["tcp_ready"] is True
    assert state["tcp_calls"] == 3


def test_wait_postgres_raises_when_tcp_never_becomes_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ready Unix socket does not cancel the timeout while TCP stays down."""
    state_path = _install_tcp_ready_shim(tmp_path, monkeypatch, ready_on=10_000)
    with pytest.raises(AssertionError, match="pg-tcp did not become ready"):
        _wait_postgres("pg-tcp")
    state = json.loads(state_path.read_text())
    assert state["tcp_ready"] is False
    assert state["tcp_calls"] == 40
