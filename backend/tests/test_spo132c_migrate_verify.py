"""SPO-132c: --verify-only against a real Postgres 16 server.

The test creates two scratch databases, compares them with the migrate
script, then changes one row count. It skips when psql is missing or the
server is not reachable. CI installs the client and provides Postgres.
"""

from __future__ import annotations

import os
import re
import subprocess
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
        assert "second_table|count|2|1|MISMATCH" in result.stdout
        _assert_no_secrets(combined, [admin, source, target], password)
    finally:
        for name in created:
            _psql(psql, admin, f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
