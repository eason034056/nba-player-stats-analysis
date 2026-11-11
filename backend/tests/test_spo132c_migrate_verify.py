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
CREATE SEQUENCE extra_seq START WITH 5;
SELECT nextval('extra_seq');
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
        assert "extra_seq|last_value|5|5|OK" in matched.stdout
        assert "Game Log_id_seq|last_value|2|2|OK" in matched.stdout
        assert "ok:" in matched.stdout
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


def _verify(source: str, target: str) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "PG_CLIENT": "host",
        "LOCAL_DATABASE_URL": source,
        "RDS_DATABASE_URL": target,
    }
    return subprocess.run(
        ["bash", str(MIGRATE), "--verify-only"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
