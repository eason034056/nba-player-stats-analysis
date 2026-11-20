"""The session migration fixture refuses a remote DATABASE_URL."""

from __future__ import annotations

import inspect
from urllib.parse import urlsplit

import asyncpg
import pytest

from tests import conftest as migration_conftest


def _fixture_body(func):
    """Return the underlying function of a pytest fixture, for a direct call."""
    seen: set[int] = set()
    current = func
    while id(current) not in seen:
        seen.add(id(current))
        wrapped = getattr(current, "__wrapped__", None)
        if wrapped is not None:
            current = wrapped
            continue
        getter = getattr(current, "_get_wrapped_function", None)
        if callable(getter):
            current = getter()
            continue
        break
    if not inspect.isfunction(current):
        raise AssertionError(f"could not unwrap fixture body from {func!r}")
    return current


def test_session_fixture_does_not_upgrade_a_remote_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_TEST_DB", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://novig:novig@prod.example.rds.amazonaws.com:5432/novig_nba",
    )
    called: list[str] = []

    async def fake_connect(dsn: str, *args: object, **kwargs: object) -> None:
        called.append(dsn)
        raise AssertionError(f"must not connect to a remote DSN: {dsn}")

    monkeypatch.setattr(asyncpg, "connect", fake_connect)
    try:
        _fixture_body(migration_conftest.apply_shipped_migrations)()
    except pytest.skip.Exception:
        pass
    assert called == []


def test_remote_refusal_names_the_host_and_not_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """The refusal a developer reads names the host and leaves the URL out."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_TEST_DB", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://novig:pw-must-not-leak@prod.example.rds.amazonaws.com:5432/novig_nba",
    )

    with pytest.raises(pytest.skip.Exception) as raised:
        _fixture_body(migration_conftest.apply_shipped_migrations)()

    message = str(raised.value)
    assert "prod.example.rds.amazonaws.com" in message
    assert "postgresql://" not in message
    assert "pw-must-not-leak" not in message


def test_session_fixture_still_upgrades_a_localhost_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """localhost is a local host, so the fixture opens a connection."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_TEST_DB", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://novig:novig@localhost:5432/novig_nba",
    )
    called: list[str] = []

    async def fake_connect(dsn: str, *args: object, **kwargs: object) -> None:
        called.append(dsn)
        raise OSError("stop before a real connection")

    monkeypatch.setattr(asyncpg, "connect", fake_connect)
    with pytest.raises(OSError, match="stop before a real connection"):
        _fixture_body(migration_conftest.apply_shipped_migrations)()

    assert [urlsplit(dsn).hostname for dsn in called] == ["localhost"]


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://novig:novig@127.0.0.1:5432/novig_nba",
        "postgresql://novig:novig@[::1]:5432/novig_nba",
        "postgresql://novig:novig@postgres:5432/novig_nba",
        "postgresql:///novig_nba",
        "postgresql://novig:novig@localhost,127.0.0.1:5432/novig_nba",
    ],
)
def test_session_fixture_allows_the_other_local_targets(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_TEST_DB", raising=False)
    monkeypatch.setenv("DATABASE_URL", url)
    called: list[str] = []

    async def fake_connect(dsn: str, *args: object, **kwargs: object) -> None:
        called.append(dsn)
        raise OSError("stop before a real connection")

    monkeypatch.setattr(asyncpg, "connect", fake_connect)
    with pytest.raises(OSError, match="stop before a real connection"):
        _fixture_body(migration_conftest.apply_shipped_migrations)()
    assert called


def test_allow_remote_test_db_permits_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    monkeypatch.setenv("ALLOW_REMOTE_TEST_DB", "1")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://novig:novig@prod.example.rds.amazonaws.com:5432/novig_nba",
    )
    called: list[str] = []

    async def fake_connect(dsn: str, *args: object, **kwargs: object) -> None:
        called.append(urlsplit(dsn).hostname or "")
        raise OSError("stop before a real connection")

    monkeypatch.setattr(asyncpg, "connect", fake_connect)
    with pytest.raises(OSError, match="stop before a real connection"):
        _fixture_body(migration_conftest.apply_shipped_migrations)()
    assert called == ["prod.example.rds.amazonaws.com"]


def test_ci_fails_the_session_for_a_remote_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mistyped CI DATABASE_URL fails the session instead of skipping every test."""
    monkeypatch.setenv("CI", "true")
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_TEST_DB", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://novig:novig@prod.example.rds.amazonaws.com:5432/novig_nba",
    )

    with pytest.raises(pytest.fail.Exception) as raised:
        _fixture_body(migration_conftest.apply_shipped_migrations)()

    message = str(raised.value)
    assert "prod.example.rds.amazonaws.com" in message
    assert "postgresql://" not in message


def test_without_ci_a_remote_host_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_TEST_DB", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://novig:novig@prod.example.rds.amazonaws.com:5432/novig_nba",
    )

    with pytest.raises(pytest.skip.Exception) as raised:
        _fixture_body(migration_conftest.apply_shipped_migrations)()

    message = str(raised.value)
    assert "prod.example.rds.amazonaws.com" in message
    assert "postgresql://" not in message


def test_ci_workflow_database_url_passes_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """The workflow URL is a localhost netloc with no host= parameter."""
    from pathlib import Path

    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    url = ""
    for line in workflow.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("DATABASE_URL:"):
            url = stripped.split(":", 1)[1].strip()
            break
    parts = urlsplit(url)
    assert parts.hostname == "localhost"
    assert "host=" not in parts.query
    assert "hostaddr=" not in parts.query

    monkeypatch.setenv("CI", "true")
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_TEST_DB", raising=False)
    monkeypatch.setenv("DATABASE_URL", url)
    called: list[str] = []

    async def fake_connect(dsn: str, *args: object, **kwargs: object) -> None:
        called.append(urlsplit(dsn).hostname or "")
        raise OSError("stop before a real connection")

    monkeypatch.setattr(asyncpg, "connect", fake_connect)
    with pytest.raises(OSError, match="stop before a real connection"):
        _fixture_body(migration_conftest.apply_shipped_migrations)()
    assert called == ["localhost"]
