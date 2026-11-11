"""SPO-132: DSN masking, DATABASE_REQUIRED, SSL passthrough, and shell scripts.

The shell tests invoke the scripts with fake pg_dump / pg_restore / psql / aws
binaries. They do not open a database and they do not call AWS.
"""

from __future__ import annotations

import logging
import stat
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from app.dsn import mask_database_url, redact_secrets
from app.services.db import SCHEMA_SQL, DatabaseService
from app.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
MIGRATE = ROOT / "scripts" / "db_migrate_to_rds.sh"
SYNC = ROOT / "scripts" / "sync_raw_to_s3.sh"
DUMP = ROOT / "scripts" / "pg_dump_to_s3.sh"
UPDATE_IP = ROOT / "scripts" / "aws_update_my_ip.sh"

SECRET = "super-secret-pw"
LOCAL_URL = f"postgresql://mig_user:{SECRET}@local-db:5432/novig_nba"
RDS_URL = f"postgresql://mig_user:{SECRET}@rds-db:5432/novig_nba"
SSL_URL = (
    "postgresql://sportslab_app:pw@db.example:5432/novig_nba"
    "?sslmode=verify-full&sslrootcert=/app/certs/global-bundle.pem"
)


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run(script: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    merged = {"PATH": "/usr/bin:/bin", "HOME": "/tmp"}
    merged.update(env)
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        env=merged,
        check=False,
    )


class _Conn:
    def __init__(self) -> None:
        self.execute_calls: list[tuple] = []

    async def execute(self, query: str, *args: object) -> str:
        self.execute_calls.append((query, *args))
        return "OK"


class _Pool:
    def __init__(self, connection: _Conn) -> None:
        self.connection = connection
        self.closed = False

    @asynccontextmanager
    async def acquire(self):
        yield self.connection

    async def close(self) -> None:
        self.closed = True


class TestMaskDatabaseUrl:
    def test_replaces_password_and_keeps_the_rest(self) -> None:
        masked = mask_database_url(
            "postgresql://novig:novig@localhost:5432/novig_nba"
        )
        assert masked == "postgresql://novig:***@localhost:5432/novig_nba"
        assert "novig:***" in masked

    def test_keeps_ssl_query(self) -> None:
        masked = mask_database_url(SSL_URL)
        assert masked == (
            "postgresql://sportslab_app:***@db.example:5432/novig_nba"
            "?sslmode=verify-full&sslrootcert=/app/certs/global-bundle.pem"
        )
        assert "sslmode=verify-full" in masked
        assert "sslrootcert=/app/certs/global-bundle.pem" in masked
        assert "pw" not in masked.split("://", 1)[1].split("@", 1)[0]

    def test_percent_encoded_password_is_not_kept(self) -> None:
        masked = mask_database_url("postgresql://user:p%40ss%3Aword@host/db")
        assert masked == "postgresql://user:***@host/db"
        assert "p%40ss" not in masked
        assert "p@ss" not in masked

    def test_no_password_is_unchanged(self) -> None:
        url = "postgresql://novig@localhost:5432/novig_nba"
        assert mask_database_url(url) == url

    def test_redis_without_password_is_unchanged(self) -> None:
        url = "redis://localhost:6379"
        assert mask_database_url(url) == url

    def test_ipv6_host_keeps_brackets(self) -> None:
        masked = mask_database_url("postgresql://user:secret@[2001:db8::1]:5432/db")
        assert masked == "postgresql://user:***@[2001:db8::1]:5432/db"

    def test_empty(self) -> None:
        assert mask_database_url(None) == ""
        assert mask_database_url("") == ""

    def test_redact_url_inside_a_sentence(self) -> None:
        text = f"connect failed for {LOCAL_URL} (timeout)."
        masked = redact_secrets(text)
        assert SECRET not in masked
        assert "postgresql://mig_user:***@local-db:5432/novig_nba" in masked

    def test_redact_known_secret_outside_a_url(self) -> None:
        masked = redact_secrets(
            "authentication failed for super-secret-pw",
            (SECRET,),
        )
        assert SECRET not in masked
        assert "***" in masked

    def test_keyword_password(self) -> None:
        masked = redact_secrets("host=localhost password=super-secret-pw dbname=novig")
        assert "password=***" in masked
        assert SECRET not in masked

    def test_colon_in_password(self) -> None:
        masked = mask_database_url("postgresql://user:p:ss@host:5432/db")
        assert masked == "postgresql://user:***@host:5432/db"
        assert "p:ss" not in masked

    def test_postgres_asyncpg_scheme(self) -> None:
        masked = mask_database_url("postgres+asyncpg://user:secret@host:5432/db")
        assert masked == "postgres+asyncpg://user:***@host:5432/db"
        assert "secret" not in masked

    def test_query_string_password_only(self) -> None:
        masked = mask_database_url(
            "postgresql://user@host:5432/db?password=supersecret&sslmode=require"
        )
        assert "supersecret" not in masked
        assert "password=***" in masked
        assert "sslmode=require" in masked

    def test_unencoded_slash_in_password_is_masked(self) -> None:
        masked = mask_database_url("postgresql://user:p/ss@host:5432/db")
        assert "p/ss" not in masked
        assert "***" in masked

    def test_userinfo_and_query_password_are_both_masked(self) -> None:
        masked = mask_database_url(
            "postgresql://user:secret1@host:5432/db?password=secret2&sslmode=require"
        )
        assert "secret1" not in masked
        assert "secret2" not in masked
        assert "password=***" in masked
        assert "sslmode=require" in masked


class TestDatabaseRequired:
    def test_default_is_false(self) -> None:
        assert Settings.model_fields["database_required"].default is False

    def test_env_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_REQUIRED", "true")
        created = Settings(_env_file=None)
        assert created.database_required is True


class TestInit:
    @pytest.mark.asyncio
    async def test_ssl_dsn_is_passed_through_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.services.db as db_module

        captured: dict = {}
        connection = _Conn()

        async def mock_create_pool(**kwargs: object) -> _Pool:
            captured.update(kwargs)
            return _Pool(connection)

        monkeypatch.setattr(db_module.settings, "database_url", SSL_URL)
        monkeypatch.setattr(db_module.asyncpg, "create_pool", mock_create_pool)

        service = DatabaseService()
        await service.init()

        assert captured["dsn"] == SSL_URL
        assert "sslmode=verify-full" in captured["dsn"]
        assert "sslrootcert=/app/certs/global-bundle.pem" in captured["dsn"]
        assert captured["min_size"] == 2
        assert captured["max_size"] == 10
        assert connection.execute_calls[0][0] == SCHEMA_SQL

    @pytest.mark.asyncio
    async def test_init_failure_log_has_no_password(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import app.services.db as db_module

        dsn = f"postgresql://sportslab_app:{SECRET}@db.example:5432/novig_nba"
        monkeypatch.setattr(db_module.settings, "database_url", dsn)
        monkeypatch.setattr(db_module.settings, "database_required", False)

        async def mock_create_pool(**kwargs: object) -> _Pool:
            raise ConnectionRefusedError(f"authentication failed for {SECRET}")

        monkeypatch.setattr(db_module.asyncpg, "create_pool", mock_create_pool)
        service = DatabaseService()
        with caplog.at_level(logging.ERROR):
            await service.init()

        assert service.is_connected is False
        assert SECRET not in caplog.text
        assert "***" in caplog.text
        captured = capsys.readouterr()
        assert SECRET not in captured.out
        assert SECRET not in captured.err


class TestLifespan:
    @pytest.mark.asyncio
    async def test_raises_when_database_required_and_init_swallows(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import app.main as main_mod
        from fastapi import FastAPI

        monkeypatch.setattr(main_mod, "setup_logging", lambda: None)
        monkeypatch.setattr(main_mod.settings, "database_required", True)
        monkeypatch.setattr(
            main_mod.settings,
            "database_url",
            f"postgresql://sportslab_app:{SECRET}@db.example:5432/novig_nba",
        )

        async def init_swallows() -> None:
            main_mod.db_service._pool = None

        monkeypatch.setattr(main_mod.db_service, "init", init_swallows)

        with pytest.raises(RuntimeError, match="DATABASE_REQUIRED") as raised:
            async with main_mod.lifespan(FastAPI()):
                pass

        assert SECRET not in str(raised.value)
        captured = capsys.readouterr()
        assert SECRET not in captured.out
        assert "***" in captured.out

    @pytest.mark.asyncio
    async def test_raises_and_redacts_when_init_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.main as main_mod
        from fastapi import FastAPI

        monkeypatch.setattr(main_mod, "setup_logging", lambda: None)
        monkeypatch.setattr(main_mod.settings, "database_required", True)
        monkeypatch.setattr(main_mod.settings, "database_url", LOCAL_URL)

        async def init_raises() -> None:
            raise RuntimeError(f"connect {LOCAL_URL} failed")

        monkeypatch.setattr(main_mod.db_service, "init", init_raises)

        with pytest.raises(RuntimeError, match="DATABASE_REQUIRED") as raised:
            async with main_mod.lifespan(FastAPI()):
                pass

        assert SECRET not in str(raised.value)
        assert raised.value.__cause__ is None

    @pytest.mark.asyncio
    async def test_optional_database_keeps_booting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.main as main_mod
        from fastapi import FastAPI

        monkeypatch.setattr(main_mod, "setup_logging", lambda: None)
        monkeypatch.setattr(main_mod.settings, "database_required", False)
        monkeypatch.setattr(main_mod.settings, "database_url", LOCAL_URL)

        async def init_swallows() -> None:
            main_mod.db_service._pool = None

        async def close() -> None:
            return None

        monkeypatch.setattr(main_mod.db_service, "init", init_swallows)
        monkeypatch.setattr(main_mod.db_service, "close", close)
        monkeypatch.setattr(main_mod.cache_service, "close", close)
        monkeypatch.setattr(main_mod.scheduler_service, "start", lambda: None)
        monkeypatch.setattr(main_mod.scheduler_service, "stop", lambda: None)
        monkeypatch.setattr(main_mod.scheduler_service, "get_next_run_time", lambda: "n/a")

        async with main_mod.lifespan(FastAPI()):
            assert main_mod.db_service.is_connected is False


def _client_bin(tmp_path: Path, *, restore_version: str) -> dict[str, str]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _write_executable(
        bindir / "pg_restore",
        f"""#!/bin/sh
if [ "$1" = "--version" ]; then
  echo "pg_restore (PostgreSQL) {restore_version}"
  exit 0
fi
exit 0
""",
    )
    _write_executable(
        bindir / "pg_dump",
        f"""#!/bin/sh
printf called >> "{bindir / "dump-called"}"
printf '%s\\n' "$@" > "{bindir / "pg_dump.argv"}"
prev=""
for arg in "$@"; do
  if [ "$prev" = "--file" ]; then
    printf 'PGDMP' > "$arg"
  fi
  prev="$arg"
done
exit 0
""",
    )
    _write_executable(
        bindir / "psql",
        r"""#!/bin/sh
printf '%s\n' "$@" >> "$0.argv"
url="$1"
shift
case "$url" in
  *://*) ;;
  *) url="${PGHOST:-}" ;;
esac
sql=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-c" ]; then
    sql="$arg"
  fi
  prev="$arg"
done
case "$url" in
  *local-db*) side=local ;;
  *) side=rds ;;
esac
case "$sql" in
  *last_value*)
    if [ "$side" = local ]; then echo "${FAKE_LOCAL_SEQ:-9}"; else echo "${FAKE_RDS_SEQ:-9}"; fi
    ;;
  *sequencename*) echo player_projections_id_seq ;;
  *information_schema.tables*) echo player_projections ;;
  *quote_ident*) echo '"player_projections"' ;;
  *information_schema.columns*) echo t ;;
  *'count(*)'*)
    if [ "$side" = local ]; then echo "${FAKE_LOCAL_COUNT:-4}"; else echo "${FAKE_RDS_COUNT:-4}"; fi
    ;;
  *'max(id)'*)
    if [ "$side" = local ]; then echo "${FAKE_LOCAL_MAX:-9}"; else echo "${FAKE_RDS_MAX:-9}"; fi
    ;;
  *)
    echo "unexpected sql" >&2
    exit 1
    ;;
esac
""",
    )
    return {
        "PG_CLIENT": "host",
        "PG_DUMP": str(bindir / "pg_dump"),
        "PG_RESTORE": str(bindir / "pg_restore"),
        "PSQL": str(bindir / "psql"),
        "LOCAL_DATABASE_URL": LOCAL_URL,
        "RDS_DATABASE_URL": RDS_URL,
        "_BIN": str(bindir),
    }


class TestMigrateScript:
    def test_help(self) -> None:
        result = _run(MIGRATE, {}, "--help")
        assert result.returncode == 0
        assert "LOCAL_DATABASE_URL" in result.stdout
        assert "transaction_timeout" in result.stdout

    def test_missing_env_is_a_dry_run(self) -> None:
        result = _run(MIGRATE, {})
        assert result.returncode == 2
        assert "Dry run" in result.stderr
        assert "LOCAL_DATABASE_URL" in result.stderr
        combined = result.stdout + result.stderr
        assert "postgresql://" not in combined

    def test_refuses_pg_restore_17_without_printing_the_url(self, tmp_path: Path) -> None:
        env = _client_bin(tmp_path, restore_version="17.11")
        bindir = env.pop("_BIN")
        result = _run(MIGRATE, env)
        assert result.returncode == 3
        assert "transaction_timeout" in result.stderr
        assert SECRET not in result.stdout + result.stderr
        assert not (Path(bindir) / "dump-called").exists()

    def test_mismatch_exits_nonzero_and_hides_the_password(self, tmp_path: Path) -> None:
        env = _client_bin(tmp_path, restore_version="16.4")
        env.pop("_BIN")
        env["FAKE_RDS_MAX"] = "8"
        result = _run(MIGRATE, env)
        assert result.returncode == 1
        assert "MISMATCH" in result.stdout
        assert "player_projections|count|4|4|OK" in result.stdout
        assert "player_projections|max_id|9|8|MISMATCH" in result.stdout
        assert "player_projections_id_seq|last_value|9|9|OK" in result.stdout
        assert SECRET not in result.stdout + result.stderr

    def test_match_exits_zero(self, tmp_path: Path) -> None:
        env = _client_bin(tmp_path, restore_version="16.4")
        bindir = Path(env.pop("_BIN"))
        result = _run(MIGRATE, env)
        assert result.returncode == 0, result.stderr
        assert "MISMATCH" not in result.stdout
        assert "ok:" in result.stdout
        assert SECRET not in result.stdout + result.stderr
        argv = Path(str(env["PSQL"]) + ".argv").read_text()
        dump_argv = (bindir / "pg_dump.argv").read_text()
        assert SECRET not in argv
        assert "postgresql://" not in argv
        assert SECRET not in dump_argv
        assert "--dbname" not in dump_argv

    def test_dump_stderr_is_redacted(self, tmp_path: Path) -> None:
        env = _client_bin(tmp_path, restore_version="16.4")
        bindir = Path(env.pop("_BIN"))
        _write_executable(
            bindir / "pg_dump",
            f"""#!/bin/sh
echo "failed {LOCAL_URL}" >&2
exit 1
""",
        )
        result = _run(MIGRATE, env)
        assert result.returncode == 1
        assert SECRET not in result.stdout + result.stderr
        assert "***" in result.stderr


class TestSyncScript:
    def test_missing_env_does_not_call_aws(self, tmp_path: Path) -> None:
        marker = tmp_path / "aws-called"
        aws = tmp_path / "aws"
        _write_executable(aws, f"#!/bin/sh\ntouch {marker}\nexit 0\n")
        result = _run(SYNC, {"AWS_CLI": str(aws)})
        assert result.returncode == 2
        assert "Dry run" in result.stderr
        assert "S3_BUCKET" in result.stderr
        assert not marker.exists()

    def test_sync_prefixes_and_no_delete(self, tmp_path: Path) -> None:
        cache = tmp_path / "cache"
        archive = tmp_path / "archive"
        samples = tmp_path / "samples"
        for directory in (cache, archive, samples):
            directory.mkdir()
        log = tmp_path / "aws-log"
        aws = tmp_path / "aws"
        _write_executable(
            aws,
            f"""#!/bin/sh
printf '%s\\n' "$@" >> "{log}"
echo '---' >> "{log}"
exit 0
""",
        )
        env = {
            "AWS_CLI": str(aws),
            "S3_BUCKET": "example-bucket",
            "AWS_ACCESS_KEY_ID": "EXAMPLE",
            "AWS_SECRET_ACCESS_KEY": "EXAMPLE",
            "AWS_REGION": "us-east-2",
            "BDL_CACHE_DIR": str(cache),
            "BDL_ARCHIVE_DIR": str(archive),
            "BDL_SAMPLES_DIR": str(samples),
        }
        result = _run(SYNC, env)
        assert result.returncode == 0, result.stderr
        text = log.read_text()
        assert "--delete" not in text
        assert f"{cache}" in text and "s3://example-bucket/bdl-raw/" in text
        assert f"{archive}" in text and "s3://example-bucket/bdl-archive/" in text
        assert f"{samples}" in text and "s3://example-bucket/bdl-samples/" in text
        assert "*.pid" in text
        assert text.splitlines().count("sync") == 3


class TestDumpScript:
    def test_missing_env_does_not_dump(self, tmp_path: Path) -> None:
        marker = tmp_path / "dump-called"
        pg_dump = tmp_path / "pg_dump"
        _write_executable(pg_dump, f"#!/bin/sh\ntouch {marker}\nexit 0\n")
        result = _run(DUMP, {"PG_DUMP": str(pg_dump)})
        assert result.returncode == 2
        assert "Dry run" in result.stderr
        assert not marker.exists()
        assert "postgresql://" not in result.stdout + result.stderr

    def test_uploads_dated_dump_without_printing_the_url(self, tmp_path: Path) -> None:
        log = tmp_path / "aws-log"
        copied = tmp_path / "copied"
        pg_dump = tmp_path / "pg_dump"
        aws = tmp_path / "aws"
        _write_executable(
            pg_dump,
            """#!/bin/sh
found=0
prev=""
for arg in "$@"; do
  if [ "$arg" = "-Fc" ]; then
    found=1
  fi
  if [ "$prev" = "--file" ]; then
    printf 'PGDMP-FAKE' > "$arg"
  fi
  prev="$arg"
done
if [ "$found" -ne 1 ]; then
  echo "missing -Fc" >&2
  exit 1
fi
exit 0
""",
        )
        _write_executable(
            aws,
            f"""#!/bin/sh
printf '%s\\n' "$@" > "{log}"
prev=""
src=""
for arg in "$@"; do
  if [ "$prev" = "cp" ]; then
    src="$arg"
  fi
  prev="$arg"
done
cp "$src" "{copied}"
exit 0
""",
        )
        env = {
            "PG_DUMP": str(pg_dump),
            "AWS_CLI": str(aws),
            "S3_BUCKET": "example-bucket",
            "AWS_ACCESS_KEY_ID": "EXAMPLE",
            "AWS_SECRET_ACCESS_KEY": "EXAMPLE",
            "AWS_REGION": "us-east-2",
            "RDS_DATABASE_URL": RDS_URL,
            "DUMP_DATE": "2026-11-11",
        }
        result = _run(DUMP, env)
        assert result.returncode == 0, result.stderr
        assert "s3://example-bucket/pg-dumps/2026-11-11.dump" in result.stdout
        assert SECRET not in result.stdout + result.stderr
        assert "--delete" not in log.read_text()
        assert "s3://example-bucket/pg-dumps/2026-11-11.dump" in log.read_text()
        assert copied.read_text() == "PGDMP-FAKE"
        help_text = _run(DUMP, {}, "--help")
        assert help_text.returncode == 0
        assert "90 days" in help_text.stdout

    def test_dump_does_not_put_the_dsn_on_pg_dump_argv(self, tmp_path: Path) -> None:
        argv_log = tmp_path / "pg-dump-argv"
        pg_dump = tmp_path / "pg_dump"
        aws = tmp_path / "aws"
        _write_executable(
            pg_dump,
            f"""#!/bin/sh
printf '%s\n' "$0" "$@" > "{argv_log}"
prev=""
for arg in "$@"; do
  if [ "$prev" = "--file" ]; then
    printf 'PGDMP-FAKE' > "$arg"
  fi
  prev="$arg"
done
exit 0
""",
        )
        _write_executable(aws, "#!/bin/sh\nexit 0\n")
        env = {
            "PG_DUMP": str(pg_dump),
            "AWS_CLI": str(aws),
            "S3_BUCKET": "example-bucket",
            "AWS_ACCESS_KEY_ID": "EXAMPLE",
            "AWS_SECRET_ACCESS_KEY": "EXAMPLE",
            "AWS_REGION": "us-east-2",
            "RDS_DATABASE_URL": RDS_URL,
            "DUMP_DATE": "2026-11-11",
        }
        result = _run(DUMP, env)
        assert result.returncode == 0, result.stderr
        argv = argv_log.read_text()
        assert SECRET not in argv
        assert RDS_URL not in argv

    def test_dump_mktemp_is_bsd_portable(self, tmp_path: Path) -> None:
        """macOS mktemp is BSD and rejects GNU --suffix."""
        bindir = tmp_path / "bin"
        bindir.mkdir()
        mktemp = bindir / "mktemp"
        _write_executable(
            mktemp,
            f"""#!/bin/sh
for arg in "$@"; do
  case "$arg" in
    --suffix*|-*suffix*)
      echo "mktemp: illegal option -- -" >&2
      exit 1
      ;;
  esac
done
dir="{tmp_path}/tmp"
mkdir -p "$dir"
# BSD-style: mktemp [template] or mktemp with no args.
if [ "$#" -eq 0 ]; then
  out="$dir/tmpfile.$$"
  : > "$out"
  printf '%s\n' "$out"
  exit 0
fi
out="$dir/portable.$$"
: > "$out"
printf '%s\n' "$out"
exit 0
""",
        )
        pg_dump = bindir / "pg_dump"
        aws = bindir / "aws"
        _write_executable(
            pg_dump,
            """#!/bin/sh
prev=""
for arg in "$@"; do
  if [ "$prev" = "--file" ]; then
    printf 'PGDMP-FAKE' > "$arg"
  fi
  prev="$arg"
done
exit 0
""",
        )
        _write_executable(aws, "#!/bin/sh\nexit 0\n")
        env = {
            "PATH": f"{bindir}:/usr/bin:/bin",
            "PG_DUMP": str(pg_dump),
            "AWS_CLI": str(aws),
            "S3_BUCKET": "example-bucket",
            "AWS_ACCESS_KEY_ID": "EXAMPLE",
            "AWS_SECRET_ACCESS_KEY": "EXAMPLE",
            "AWS_REGION": "us-east-2",
            "RDS_DATABASE_URL": RDS_URL,
            "DUMP_DATE": "2026-11-11",
            "TMPDIR": str(tmp_path / "tmpdir"),
        }
        (tmp_path / "tmpdir").mkdir()
        result = _run(DUMP, env)
        assert result.returncode == 0, result.stderr
        assert "illegal option" not in result.stderr


def _fake_docker(path: Path, log: Path, sslmark: Path) -> None:
    _write_executable(
        path,
        f"""#!/bin/sh
printf '%s\\n' "$@" >> "{log}"
echo '---' >> "{log}"
joined="$*"
case "$joined" in
  *--version*)
    echo "pg_restore (PostgreSQL) 16.4"
    exit 0
    ;;
esac
if [ "$1" = "cp" ]; then
  if [ -f "$2" ]; then
    exit 0
  fi
  printf 'PGDMP' > "$3"
  exit 0
fi
case "$joined" in
  *pg_dump*) exit 0 ;;
  *pg_restore*) exit 0 ;;
esac
case "$joined" in
  *psql*)
    sql=""
    prev=""
    for arg in "$@"; do
      if [ "$prev" = "-c" ]; then
        sql="$arg"
      fi
      prev="$arg"
    done
    case "$PSQL_TARGET" in
      *sslmode=require*) printf seen >> "{sslmark}" ;;
    esac
    case "$PSQL_TARGET" in
      *local-db*) side=local ;;
      *) side=rds ;;
    esac
    case "$sql" in
      *last_value*) echo 9 ;;
      *sequencename*) echo player_projections_id_seq ;;
      *information_schema.tables*) echo player_projections ;;
      *quote_ident*) echo '"player_projections"' ;;
      *information_schema.columns*) echo t ;;
      *'count(*)'*) echo 4 ;;
      *'max(id)'*) echo 9 ;;
      *) echo "unexpected sql" >&2; exit 1 ;;
    esac
    ;;
  *) exit 0 ;;
esac
""",
    )


class TestDockerMigrate:
    def test_docker_exec_hides_password_and_requires_ssl(self, tmp_path: Path) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        log = tmp_path / "docker-log"
        sslmark = tmp_path / "sslmark"
        _fake_docker(bindir / "docker", log, sslmark)
        env = {
            "PATH": f"{bindir}:/usr/bin:/bin",
            "PG_CLIENT": "docker-exec",
            "LOCAL_DATABASE_URL": LOCAL_URL,
            "RDS_DATABASE_URL": RDS_URL,
        }
        result = _run(MIGRATE, env)
        assert result.returncode == 0, result.stderr
        text = log.read_text()
        assert "no-vig-nba-postgres" in text
        assert "pg_dump" in text
        assert "pg_restore" in text
        assert SECRET not in text
        assert SECRET not in result.stdout + result.stderr
        assert sslmark.read_text().startswith("seen")
        assert "ok:" in result.stdout

    def test_local_container_flag(self, tmp_path: Path) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        log = tmp_path / "docker-log"
        sslmark = tmp_path / "sslmark"
        _fake_docker(bindir / "docker", log, sslmark)
        env = {
            "PATH": f"{bindir}:/usr/bin:/bin",
            "PG_CLIENT": "docker-exec",
            "LOCAL_DATABASE_URL": LOCAL_URL,
            "RDS_DATABASE_URL": RDS_URL,
        }
        result = _run(MIGRATE, env, "--local-container", "pg-on-the-mac")
        assert result.returncode == 0, result.stderr
        assert "pg-on-the-mac" in log.read_text()
        assert SECRET not in log.read_text()

    def test_docker_run_uses_postgres_16_image(self, tmp_path: Path) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        log = tmp_path / "docker-log"
        sslmark = tmp_path / "sslmark"
        _fake_docker(bindir / "docker", log, sslmark)
        env = {
            "PATH": f"{bindir}:/usr/bin:/bin",
            "PG_CLIENT": "docker-run",
            "LOCAL_DATABASE_URL": LOCAL_URL,
            "RDS_DATABASE_URL": RDS_URL,
        }
        result = _run(MIGRATE, env, "--pg-client", "docker-run")
        assert result.returncode == 0, result.stderr
        text = log.read_text()
        assert "postgres:16" in text
        assert "container:no-vig-nba-postgres" in text
        assert SECRET not in text
        assert SECRET not in result.stdout + result.stderr


class TestUpdateMyIp:
    def test_rewrites_mac_home_and_does_not_apply(self, tmp_path: Path) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        tf_dir = tmp_path / "infra"
        tf_dir.mkdir()
        example = tf_dir / "terraform.tfvars.example"
        example.write_text(
            "\n".join(
                [
                    'region = "us-east-2"',
                    "allowed_cidrs = [",
                    '  "184.193.214.44/32", # box',
                    '  "203.0.113.10/32", # mac-home',
                    "]",
                    "",
                ]
            )
        )
        curl = bindir / "curl"
        terraform = bindir / "terraform"
        marker = tmp_path / "terraform-called"
        _write_executable(curl, "#!/bin/sh\necho 198.51.100.20\n")
        _write_executable(terraform, f"#!/bin/sh\ntouch {marker}\nexit 0\n")
        env = {
            "PATH": f"{bindir}:/usr/bin:/bin",
            "CURL": str(curl),
            "TERRAFORM": str(terraform),
            "TF_DIR": str(tf_dir),
        }
        result = _run(UPDATE_IP, env)
        assert result.returncode == 0, result.stderr
        assert "198.51.100.20" in result.stdout
        assert "184.193.214.44/32" in result.stdout
        assert "No AWS call was made" in result.stdout
        assert not marker.exists()
        written = (tf_dir / "terraform.tfvars").read_text()
        assert '184.193.214.44/32", # box' in written
        assert '198.51.100.20/32", # mac-home' in written
        assert "203.0.113.10/32" not in written

    def test_apply_runs_terraform_with_both_cidrs(self, tmp_path: Path) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        tf_dir = tmp_path / "infra"
        tf_dir.mkdir()
        (tf_dir / "terraform.tfvars").write_text(
            '  "203.0.113.10/32", # mac-home\n  "184.193.214.44/32", # box\n'
        )
        log = tmp_path / "tf-log"
        _write_executable(bindir / "curl", "#!/bin/sh\necho 198.51.100.21\n")
        _write_executable(
            bindir / "terraform",
            f"""#!/bin/sh
printf '%s\\n' "$@" > "{log}"
exit 0
""",
        )
        env = {
            "PATH": f"{bindir}:/usr/bin:/bin",
            "CURL": str(bindir / "curl"),
            "TERRAFORM": str(bindir / "terraform"),
            "TF_DIR": str(tf_dir),
        }
        result = _run(UPDATE_IP, env, "--apply")
        assert result.returncode == 0, result.stderr
        text = log.read_text()
        assert "apply" in text
        assert "184.193.214.44/32" in text
        assert "198.51.100.21/32" in text
        assert "203.0.113.10" not in (tf_dir / "terraform.tfvars").read_text()
