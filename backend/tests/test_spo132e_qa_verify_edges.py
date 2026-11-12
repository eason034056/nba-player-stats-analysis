"""QA: migrate --verify-only edge cases found reviewing SPO-132e."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.test_spo132d_qa_verify_modes import (
    _MODES,
    _make_pair,
    _mode_env,
    _Pair,
    _run,
)

_UUID_PK = """
CREATE TABLE uuid_rows (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), v integer NOT NULL);
INSERT INTO uuid_rows (v) VALUES (1), (2);
"""


@pytest.fixture
def uuid_pair() -> Iterator[_Pair]:
    yield from _make_pair(_UUID_PK)


@pytest.mark.parametrize("mode", _MODES)
def test_uuid_id_table_never_reports_ok_after_a_query_error(
    mode: str, uuid_pair: _Pair, tmp_path: Path
) -> None:
    # Postgres 16 has no max(uuid). Today the max(id) query errors out.
    # Whatever the script does about that, it must not print ok.
    result, shown = _run(uuid_pair, _mode_env(mode, tmp_path, uuid_pair.psql))
    assert "uuid_rows|count|2|2|OK" in result.stdout, shown
    if result.returncode != 0:
        assert "ok:" not in result.stdout


@pytest.mark.xfail(
    strict=True,
    reason="nit: a table whose id is a uuid cannot be verified (max(uuid) does not exist)",
)
def test_uuid_id_table_with_zero_sequences_verifies(
    uuid_pair: _Pair, tmp_path: Path
) -> None:
    result, shown = _run(uuid_pair, _mode_env("host", tmp_path, uuid_pair.psql))
    assert result.returncode == 0, shown
    assert "ok:" in result.stdout
