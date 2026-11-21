"""QA review of SPO-138j: secrets in CLI errors, the NULL-tip T rule, and outputs.

The CLI must never print any part of the DSN password, including a password
that urlsplit cannot parse. A NULL tip means T is 00:00 America/New_York on
games.date (the same rule as the 005 ``game_as_of`` sketch), not that time
minus another three hours. The Parquet and metadata never carry the DSN.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import asyncpg
import pytest

from app.ml.asof import prediction_instant
from app.ml.build_dataset import main, metadata_path

MIGRATIONS = Path(__file__).resolve().parents[1] / "app" / "migrations"


@pytest.mark.parametrize("separator", ["#", "/", "?"])
def test_cli_never_prints_part_of_a_password_with_an_unencoded_separator(
    separator: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    head = "QaHiddenHead9137"
    tail = "QaHiddenTail4410"
    dsn = f"postgresql://ml_user:{head}{separator}{tail}@127.0.0.1:1/nba"
    monkeypatch.setenv("ML_DATABASE_URL", dsn)
    code = main(
        ["--dsn-env", "ML_DATABASE_URL", "--seasons", "2015:2015", "--out", str(tmp_path / "x.parquet")]
    )
    assert code == 1
    captured = capsys.readouterr()
    blob = captured.out + captured.err
    assert head not in blob
    assert tail not in blob
    assert "postgresql://" not in blob


def test_null_tip_t_is_new_york_midnight_on_the_game_date() -> None:
    winter = prediction_instant(date(2026, 1, 15), None)
    assert winter.tip_fallback is True
    assert winter.as_of == datetime(2026, 1, 15, 5, 0, tzinfo=UTC)

    summer = prediction_instant(date(2026, 7, 15), None, hours_before_tip=6)
    assert summer.tip_fallback is True
    assert summer.as_of == datetime(2026, 7, 15, 4, 0, tzinfo=UTC)

    known = prediction_instant(date(2026, 1, 15), datetime(2026, 1, 16, 0, 30, tzinfo=UTC))
    assert known.as_of == datetime(2026, 1, 15, 21, 30, tzinfo=UTC)


@pytest.mark.asyncio
async def test_export_files_do_not_contain_the_dsn(
    scratch_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    conn = await asyncpg.connect(scratch_dsn, timeout=5)
    try:
        async with conn.transaction():
            for name in ("002_bdl_core.sql", "004_read_layer.sql"):
                await conn.execute((MIGRATIONS / name).read_text(encoding="utf-8"))
    finally:
        await conn.close()

    monkeypatch.setenv("QA_ML_DSN", scratch_dsn)
    out = tmp_path / "empty.parquet"
    import asyncio

    code = await asyncio.to_thread(
        main, ["--dsn-env", "QA_ML_DSN", "--seasons", "2015:2015", "--out", str(out)]
    )
    assert code == 0
    captured = capsys.readouterr()
    meta_text = metadata_path(out).read_text(encoding="utf-8")
    parquet_bytes = out.read_bytes()
    for blob in (captured.out + captured.err, meta_text):
        assert scratch_dsn not in blob
        assert "://" not in blob
    assert scratch_dsn.encode() not in parquet_bytes
    meta = json.loads(meta_text)
    assert meta["row_count"] == 0
    assert not any("dsn" in key.lower() for key in meta)
