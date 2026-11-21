"""QA re-review of SPO-138j: the CLI never prints any decoded piece of the password.

The repo's DSN guidance says to percent-encode ``@``, ``:``, ``/`` and ``%``.
A password written that way can still carry a raw ``#`` or ``?``. asyncpg then
reads the decoded text before that separator as the port and puts it in the
error. A short first piece (under 4 characters) must not print either.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ml.build_dataset import main


@pytest.mark.parametrize(
    ("raw_password", "decoded_piece"),
    [
        ("Qa%40HiddenHead#QaHiddenTail", "Qa@HiddenHead"),
        ("QaHidden%2FHead?QaHiddenTail", "QaHidden/Head"),
        ("Qz7#QaHiddenTail4410", "Qz7"),
    ],
)
def test_cli_never_prints_a_decoded_or_short_password_piece(
    raw_password: str,
    decoded_piece: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ML_DATABASE_URL", f"postgresql://ml_user:{raw_password}@127.0.0.1:1/nba")
    code = main(
        ["--dsn-env", "ML_DATABASE_URL", "--seasons", "2015:2015", "--out", str(tmp_path / "x.parquet")]
    )
    assert code == 1
    captured = capsys.readouterr()
    blob = captured.out + captured.err
    assert decoded_piece not in blob
    assert "QaHiddenTail" not in blob
    assert "postgresql://" not in blob
