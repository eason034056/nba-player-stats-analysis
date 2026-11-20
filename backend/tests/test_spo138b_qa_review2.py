"""Remote netloc, PGHOST, and host query parameters are not migrated."""

from __future__ import annotations

import inspect

import asyncpg
import pytest

from tests import conftest as migration_conftest


def _fixture_body(func):
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


def _run_fixture_without_connecting(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    called: list[str] = []

    async def fake_connect(dsn: str, *args: object, **kwargs: object) -> None:
        called.append(dsn)
        raise AssertionError(f"must not connect to a remote DSN: {dsn}")

    monkeypatch.setattr(asyncpg, "connect", fake_connect)
    try:
        _fixture_body(migration_conftest.apply_shipped_migrations)()
    except (pytest.skip.Exception, pytest.fail.Exception):
        pass
    return called


def test_remote_netloc_is_refused_even_when_host_query_says_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_TEST_DB", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://novig:novig@prod.example.rds.amazonaws.com:5432/novig_nba?host=localhost")
    assert _run_fixture_without_connecting(monkeypatch) == []


def test_remote_netloc_is_refused_even_when_host_query_is_a_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_TEST_DB", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://novig:novig@prod.example.rds.amazonaws.com:5432/novig_nba?host=/var/run/postgresql")
    assert _run_fixture_without_connecting(monkeypatch) == []


def test_pghost_is_consulted_when_the_url_has_no_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_TEST_DB", raising=False)
    monkeypatch.setenv("PGHOST", "prod.example.rds.amazonaws.com")
    monkeypatch.setenv("DATABASE_URL", "postgresql:///novig_nba")
    assert _run_fixture_without_connecting(monkeypatch) == []


def test_duplicate_host_query_params_follow_asyncpg_last_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    monkeypatch.delenv("ALLOW_REMOTE_TEST_DB", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://novig:novig@/novig_nba?host=localhost&host=prod.example.rds.amazonaws.com")
    assert _run_fixture_without_connecting(monkeypatch) == []
