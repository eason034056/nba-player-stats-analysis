"""QA checks for the SPO-138j review on PR 109.

A password that contains ``#``, ``/``, or ``?`` must not reach stderr.
A NULL tip is midnight America/New_York, with no extra hour offset.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg
import pytest

from app.ml.asof import prediction_instant
from app.ml.build_dataset import main, metadata_path

MIGRATIONS = Path(__file__).resolve().parents[1] / "app" / "migrations"
FILES = ("002_bdl_core.sql", "004_read_layer.sql")
_PIECE = "LongSecretPart"


@pytest.mark.parametrize("separator", ["#", "/", "?"])
def test_cli_hides_a_password_piece_before_a_separator(
    separator: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    password = f"{_PIECE}{separator}rest"
    monkeypatch.setenv(
        "ML_DATABASE_URL",
        f"postgresql://u:{password}@127.0.0.1:1/db",
    )
    code = main(
        [
            "--dsn-env",
            "ML_DATABASE_URL",
            "--seasons",
            "2015:2015",
            "--out",
            str(tmp_path / "x.parquet"),
        ]
    )
    assert code == 1
    blob = capsys.readouterr().out + capsys.readouterr().err
    assert _PIECE not in blob
    assert password not in blob
    assert "postgresql://" not in blob


def test_null_tip_is_midnight_new_york_with_no_extra_offset() -> None:
    winter = prediction_instant(date(2026, 1, 15), None, hours_before_tip=3)
    assert winter.tip_fallback is True
    assert winter.as_of == datetime(2026, 1, 15, 5, 0, tzinfo=UTC)
    assert prediction_instant(date(2026, 1, 15), None, hours_before_tip=5).as_of == winter.as_of

    summer = prediction_instant(date(2026, 7, 15), None)
    assert summer.as_of == datetime(2026, 7, 15, 4, 0, tzinfo=UTC)

    tip = datetime(2026, 1, 16, 3, 0, tzinfo=UTC)
    known = prediction_instant(date(2026, 1, 15), tip)
    assert known.tip_fallback is False
    assert known.as_of == tip - timedelta(hours=3)


@pytest.mark.asyncio
async def test_export_files_and_stdout_omit_the_dsn(
    scratch_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conn = await asyncpg.connect(scratch_dsn, timeout=5)
    try:
        async with conn.transaction():
            for name in FILES:
                await conn.execute((MIGRATIONS / name).read_text(encoding="utf-8"))
    finally:
        await conn.close()

    monkeypatch.setenv("ML_DATABASE_URL", scratch_dsn)
    out = tmp_path / "player_games.parquet"
    with ThreadPoolExecutor(max_workers=1) as pool:
        code = pool.submit(
            main,
            ["--dsn-env", "ML_DATABASE_URL", "--seasons", "2015:2015", "--out", str(out)],
        ).result()
    captured = capsys.readouterr()
    assert code == 0, captured.err
    db_name = urlsplit(scratch_dsn).path.rsplit("/", 1)[-1]
    blob = captured.out + captured.err + metadata_path(out).read_text(encoding="utf-8")
    assert "postgresql://" not in blob
    assert db_name not in blob
    raw = out.read_bytes()
    assert b"postgresql://" not in raw
    assert db_name.encode() not in raw
