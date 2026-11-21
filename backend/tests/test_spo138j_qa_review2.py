"""QA review 2 of SPO-138j: a decoded or short password piece.

asyncpg percent-decodes the userinfo before it rejects a raw ``#``. The
decoded text, and a piece shorter than four characters, must not be printed.
An unreadable DSN becomes a fixed message.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ml.build_dataset import main


@pytest.mark.parametrize(
    ("password", "leaked", "tail"),
    [
        pytest.param("Long%40Secret#xyz1", "Long@Secret", "xyz1", id="encoded-at"),
        pytest.param("LongSecret%2F99#xyz1", "LongSecret/99", "xyz1", id="encoded-slash"),
        pytest.param("Ab1#LongTail99", "Ab1", "LongTail99", id="short-piece"),
    ],
)
def test_cli_never_prints_a_decoded_or_short_password_piece(
    password: str,
    leaked: str,
    tail: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    dsn = f"postgresql://u:{password}@127.0.0.1:1/db"
    monkeypatch.setenv("ML_DATABASE_URL", dsn)
    code = main(
        ["--dsn-env", "ML_DATABASE_URL", "--seasons", "2015:2015", "--out", str(tmp_path / "x.parquet")]
    )
    assert code == 1
    captured = capsys.readouterr()
    blob = captured.out + captured.err
    assert leaked not in blob
    assert tail not in blob
    assert password not in blob
    assert "postgresql://" not in blob
    assert "invalid literal" not in blob
    assert "percent-encode every special character in the password" in blob
