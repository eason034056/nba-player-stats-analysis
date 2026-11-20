"""The image entrypoint migrates, then execs uvicorn. A failed migration stops first."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
SCRIPT = BACKEND / "docker-entrypoint.sh"
DOCKERFILE = BACKEND / "Dockerfile"
COMPOSE = REPO / "docker-compose.yml"


def _bindir(tmp_path: Path, marker: Path) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    python = bindir / "python"
    python.write_text(f"#!/bin/sh\nexec {sys.executable} \"$@\"\n", encoding="utf-8")
    uvicorn = bindir / "uvicorn"
    uvicorn.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    for path in (python, uvicorn):
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return bindir


def _run(bindir: Path, dsn: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    env["DATABASE_URL"] = dsn
    return subprocess.run(
        ["sh", str(SCRIPT), "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_dockerfile_entrypoint_runs_before_uvicorn() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert 'ENTRYPOINT ["/app/docker-entrypoint.sh"]' in text
    assert 'CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]' in text


def test_compose_backend_keeps_the_image_entrypoint() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    backend = text.split("\n  backend:", 1)[1].split("\n  redis:", 1)[0]
    assert "\n    command:" not in backend


def test_entrypoint_does_not_start_uvicorn_when_upgrade_fails(tmp_path: Path) -> None:
    marker = tmp_path / "uvicorn-started"
    password = "pw-must-not-leak"
    result = _run(
        _bindir(tmp_path, marker),
        f"postgresql://nba:{password}@127.0.0.1:1/nba_history",
    )
    assert result.returncode != 0
    assert not marker.exists()
    combined = result.stdout + result.stderr
    assert password not in combined
    assert "postgresql://" not in combined


def test_entrypoint_starts_uvicorn_after_upgrade(tmp_path: Path, scratch_dsn: str) -> None:
    marker = tmp_path / "uvicorn-started"
    result = _run(_bindir(tmp_path, marker), scratch_dsn)
    assert result.returncode == 0, result.stderr
    assert marker.exists()
    combined = result.stdout + result.stderr
    assert scratch_dsn not in combined
    password = urlsplit(scratch_dsn).password or ""
    if len(password) >= 4:
        assert password not in combined
    assert "applied 001" in result.stdout
    assert "applied 002" in result.stdout
