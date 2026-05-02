import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.csv_downloader import CSVDownloaderService


# ---------------------------------------------------------------------------
# _get_csv_save_path
# ---------------------------------------------------------------------------

class TestGetCsvSavePath:
    def test_returns_env_path_when_set(self, monkeypatch, tmp_path):
        env_file = tmp_path / "custom.csv"
        monkeypatch.setenv("CSV_DATA_PATH", str(env_file))

        from app.services.csv_downloader import _get_csv_save_path
        result = _get_csv_save_path()
        assert result == env_file

    def test_returns_local_path_when_no_env_and_no_docker(self, monkeypatch):
        monkeypatch.delenv("CSV_DATA_PATH", raising=False)
        # Ensure /app/data does not exist (it shouldn't on local dev machines)
        docker_parent = Path("/app/data")
        if docker_parent.exists():
            pytest.skip("/app/data exists on this machine")

        from app.services.csv_downloader import _get_csv_save_path
        result = _get_csv_save_path()
        assert str(result).endswith("nba_player_game_logs.csv")


# ---------------------------------------------------------------------------
# CSVDownloaderService.__init__
# ---------------------------------------------------------------------------

class TestCSVDownloaderServiceInit:
    def test_default_values(self):
        svc = CSVDownloaderService()
        assert "raw.githubusercontent.com" in svc.url
        assert svc.save_path is not None

    def test_custom_values(self, tmp_path):
        url = "https://example.com/file.csv"
        save = tmp_path / "out.csv"
        svc = CSVDownloaderService(url=url, save_path=save)
        assert svc.url == url
        assert svc.save_path == save


# ---------------------------------------------------------------------------
# CSVDownloaderService.download – success path
# ---------------------------------------------------------------------------

class TestDownloadSuccess:
    @pytest.mark.asyncio
    async def test_download_writes_file_and_reloads_cache(self, tmp_path, monkeypatch):
        save_path = tmp_path / "data" / "file.csv"
        svc = CSVDownloaderService(url="https://example.com/f.csv", save_path=save_path)

        csv_content = "col1,col2\na,b\n"

        # Build a fake httpx response
        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.text = csv_content

        fake_client = AsyncMock()
        fake_client.get = AsyncMock(return_value=fake_response)
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: fake_client)

        reload_mock = AsyncMock()
        monkeypatch.setattr(svc, "_reload_csv_cache", reload_mock)

        result = await svc.download()

        assert result is True
        assert save_path.exists()
        assert save_path.read_text(encoding="utf-8") == csv_content
        reload_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_download_creates_parent_directories(self, tmp_path, monkeypatch):
        save_path = tmp_path / "a" / "b" / "c" / "file.csv"
        svc = CSVDownloaderService(url="https://x.com/f.csv", save_path=save_path)

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.text = "data"

        fake_client = AsyncMock()
        fake_client.get = AsyncMock(return_value=fake_response)
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: fake_client)
        monkeypatch.setattr(svc, "_reload_csv_cache", AsyncMock())

        result = await svc.download()
        assert result is True
        assert save_path.parent.exists()


# ---------------------------------------------------------------------------
# CSVDownloaderService.download – failure paths
# ---------------------------------------------------------------------------

class TestDownloadFailure:
    @pytest.mark.asyncio
    async def test_http_status_error_returns_false(self, tmp_path, monkeypatch):
        save_path = tmp_path / "file.csv"
        svc = CSVDownloaderService(url="https://example.com/f.csv", save_path=save_path)

        fake_response = MagicMock()
        fake_response.status_code = 404

        def raise_status():
            raise httpx.HTTPStatusError(
                "Not Found",
                request=MagicMock(),
                response=fake_response,
            )

        fake_response.raise_for_status = raise_status

        fake_client = AsyncMock()
        fake_client.get = AsyncMock(return_value=fake_response)
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: fake_client)

        result = await svc.download()
        assert result is False
        assert not save_path.exists()

    @pytest.mark.asyncio
    async def test_network_request_error_returns_false(self, tmp_path, monkeypatch):
        save_path = tmp_path / "file.csv"
        svc = CSVDownloaderService(url="https://example.com/f.csv", save_path=save_path)

        fake_client = AsyncMock()
        fake_client.get = AsyncMock(
            side_effect=httpx.RequestError("Connection refused", request=MagicMock())
        )
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: fake_client)

        result = await svc.download()
        assert result is False

    @pytest.mark.asyncio
    async def test_generic_exception_returns_false(self, tmp_path, monkeypatch):
        save_path = tmp_path / "file.csv"
        svc = CSVDownloaderService(url="https://example.com/f.csv", save_path=save_path)

        fake_client = AsyncMock()
        fake_client.get = AsyncMock(side_effect=RuntimeError("Unexpected"))
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=False)

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: fake_client)

        result = await svc.download()
        assert result is False


# ---------------------------------------------------------------------------
# CSVDownloaderService.get_last_modified
# ---------------------------------------------------------------------------

class TestGetLastModified:
    def test_returns_none_when_file_missing(self, tmp_path):
        svc = CSVDownloaderService(save_path=tmp_path / "no_such_file.csv")
        assert svc.get_last_modified() is None

    def test_returns_iso_string_when_file_exists(self, tmp_path):
        csv_file = tmp_path / "file.csv"
        csv_file.write_text("a,b\n1,2\n")
        svc = CSVDownloaderService(save_path=csv_file)
        result = svc.get_last_modified()
        assert result is not None
        assert "T" in result  # ISO format contains T separator


# ---------------------------------------------------------------------------
# CSVDownloaderService._reload_csv_cache
# ---------------------------------------------------------------------------

class TestReloadCsvCache:
    @pytest.mark.asyncio
    async def test_reload_calls_csv_service_reload_and_clears_redis(self, monkeypatch):
        svc = CSVDownloaderService()

        mock_csv_module = MagicMock()
        mock_csv_module.csv_player_service.reload = MagicMock()

        mock_cache_module = MagicMock()
        mock_cache_module.cache_service.clear_daily_picks_cache = AsyncMock(return_value=3)

        real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def fake_import(name, *args, **kwargs):
            if name == "app.services.csv_player_history":
                return mock_csv_module
            if name == "app.services.cache":
                return mock_cache_module
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            await svc._reload_csv_cache()

        mock_csv_module.csv_player_service.reload.assert_called_once()
        mock_cache_module.cache_service.clear_daily_picks_cache.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reload_handles_csv_reload_failure_gracefully(self, monkeypatch):
        svc = CSVDownloaderService()

        real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def fake_import(name, *args, **kwargs):
            if name == "app.services.csv_player_history":
                raise ImportError("no module")
            if name == "app.services.cache":
                mock_cache = MagicMock()
                mock_cache.cache_service.clear_daily_picks_cache = AsyncMock(return_value=0)
                return mock_cache
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            # Should not raise
            await svc._reload_csv_cache()

    @pytest.mark.asyncio
    async def test_reload_handles_redis_clear_failure_gracefully(self, monkeypatch):
        svc = CSVDownloaderService()

        mock_csv_module = MagicMock()
        mock_csv_module.csv_player_service.reload = MagicMock()

        real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def fake_import(name, *args, **kwargs):
            if name == "app.services.csv_player_history":
                return mock_csv_module
            if name == "app.services.cache":
                raise ImportError("no redis")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            # Should not raise
            await svc._reload_csv_cache()

    @pytest.mark.asyncio
    async def test_reload_reports_zero_deleted_cache_entries(self, monkeypatch):
        svc = CSVDownloaderService()

        mock_csv_module = MagicMock()
        mock_csv_module.csv_player_service.reload = MagicMock()

        mock_cache_module = MagicMock()
        mock_cache_module.cache_service.clear_daily_picks_cache = AsyncMock(return_value=0)

        real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def fake_import(name, *args, **kwargs):
            if name == "app.services.csv_player_history":
                return mock_csv_module
            if name == "app.services.cache":
                return mock_cache_module
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
            await svc._reload_csv_cache()

        mock_cache_module.cache_service.clear_daily_picks_cache.assert_awaited_once()
