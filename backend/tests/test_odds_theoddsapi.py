import logging
import os
import sys

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import odds_theoddsapi as odds_module


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else []
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, _url, params=None):
        return self._response


@pytest.mark.asyncio
async def test_make_request_logs_remaining_quota(monkeypatch, caplog):
    response = _FakeResponse(
        status_code=200,
        payload=[{"id": "evt_1"}],
        headers={
            "x-requests-remaining": "499",
            "x-requests-used": "1",
            "x-requests-last": "1",
        },
    )

    monkeypatch.setattr(
        odds_module.httpx,
        "AsyncClient",
        lambda timeout=30.0: _FakeAsyncClient(response),
    )

    provider = odds_module.TheOddsAPIProvider()
    provider.base_url = "https://api.the-odds-api.com"
    provider.api_key = "test-key"

    caplog.set_level(logging.INFO, logger="app.services.odds_theoddsapi")

    data, usage = await provider._make_request(
        "/v4/sports/basketball_nba/events",
        {"regions": "us"},
    )

    assert data == [{"id": "evt_1"}]
    assert usage.remaining == 499
    assert "odds_api_quota" in caplog.text
    assert '"remaining": 499' in caplog.text
    assert '"used": 1' in caplog.text
    assert '"last": 1' in caplog.text


# ---------------------------------------------------------------------------
# Helpers for additional tests
# ---------------------------------------------------------------------------

def _patch_client(monkeypatch, response):
    """Patch httpx.AsyncClient to return *response* on every .get()."""
    monkeypatch.setattr(
        odds_module.httpx,
        "AsyncClient",
        lambda timeout=30.0: _FakeAsyncClient(response),
    )


def _make_provider():
    provider = odds_module.TheOddsAPIProvider()
    provider.base_url = "https://api.the-odds-api.com"
    provider.api_key = "test-key"
    return provider


# ---------------------------------------------------------------------------
# 1. get_events returns event list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_events_returns_event_list(monkeypatch):
    events_payload = [
        {"id": "e1", "home_team": "Lakers", "away_team": "Celtics"},
        {"id": "e2", "home_team": "Warriors", "away_team": "Nets"},
    ]
    response = _FakeResponse(status_code=200, payload=events_payload, headers={})
    _patch_client(monkeypatch, response)

    provider = _make_provider()
    result = await provider.get_events(sport="basketball_nba", regions="us")

    assert result == events_payload
    assert len(result) == 2


# ---------------------------------------------------------------------------
# 2. get_events with date filters passes correct params
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_events_with_date_filters(monkeypatch):
    from datetime import datetime

    captured_params = {}

    class _CapturingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None):
            captured_params.update(params or {})
            return _FakeResponse(status_code=200, payload=[], headers={})

    monkeypatch.setattr(
        odds_module.httpx,
        "AsyncClient",
        lambda timeout=30.0: _CapturingClient(),
    )

    provider = _make_provider()
    date_from = datetime(2026, 3, 1, 0, 0, 0)
    date_to = datetime(2026, 3, 2, 23, 59, 59)

    await provider.get_events(
        sport="basketball_nba",
        regions="us",
        date_from=date_from,
        date_to=date_to,
    )

    assert captured_params["commenceTimeFrom"] == "2026-03-01T00:00:00Z"
    assert captured_params["commenceTimeTo"] == "2026-03-02T23:59:59Z"


# ---------------------------------------------------------------------------
# 3. get_events returns empty list for non-list response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_events_non_list_response_returns_empty(monkeypatch):
    response = _FakeResponse(status_code=200, payload={"error": "unexpected"}, headers={})
    _patch_client(monkeypatch, response)

    provider = _make_provider()
    result = await provider.get_events()

    assert result == []


# ---------------------------------------------------------------------------
# 4. get_event_odds returns odds data
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_event_odds_returns_data(monkeypatch):
    odds_payload = {
        "id": "evt1",
        "bookmakers": [{"key": "draftkings", "markets": []}],
    }
    response = _FakeResponse(status_code=200, payload=odds_payload, headers={})
    _patch_client(monkeypatch, response)

    provider = _make_provider()
    result = await provider.get_event_odds(
        sport="basketball_nba",
        event_id="evt1",
        regions="us",
        markets="player_points",
    )

    assert result == odds_payload
    assert result["id"] == "evt1"


# ---------------------------------------------------------------------------
# 5. get_event_odds with bookmakers filter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_event_odds_with_bookmakers_filter(monkeypatch):
    captured_params = {}

    class _CapturingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None):
            captured_params.update(params or {})
            return _FakeResponse(status_code=200, payload={"id": "evt1", "bookmakers": []}, headers={})

    monkeypatch.setattr(
        odds_module.httpx,
        "AsyncClient",
        lambda timeout=30.0: _CapturingClient(),
    )

    provider = _make_provider()
    await provider.get_event_odds(
        event_id="evt1",
        bookmakers=["draftkings", "fanduel"],
    )

    assert captured_params["bookmakers"] == "draftkings,fanduel"


# ---------------------------------------------------------------------------
# 6. get_event_odds_with_usage returns data and usage tuple
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_event_odds_with_usage(monkeypatch):
    odds_payload = {"id": "evt1", "bookmakers": []}
    response = _FakeResponse(
        status_code=200,
        payload=odds_payload,
        headers={
            "x-requests-remaining": "400",
            "x-requests-used": "100",
            "x-requests-last": "2",
        },
    )
    _patch_client(monkeypatch, response)

    provider = _make_provider()
    data, usage = await provider.get_event_odds_with_usage(
        event_id="evt1",
        markets="player_points",
    )

    assert data == odds_payload
    assert usage is not None
    assert usage.remaining == 400
    assert usage.used == 100
    assert usage.last == 2


# ---------------------------------------------------------------------------
# 7. _make_request handles 401 error (no retry)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_make_request_401_no_retry(monkeypatch):
    call_count = 0

    class _CountingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None):
            nonlocal call_count
            call_count += 1
            return _FakeResponse(status_code=401, text="Unauthorized", headers={})

    monkeypatch.setattr(
        odds_module.httpx,
        "AsyncClient",
        lambda timeout=30.0: _CountingClient(),
    )

    provider = _make_provider()

    with pytest.raises(odds_module.OddsAPIError) as exc_info:
        await provider._make_request("/v4/test", {})

    assert exc_info.value.status_code == 401
    assert call_count == 1  # No retries for 401


# ---------------------------------------------------------------------------
# 8. _make_request handles 422 error (no retry)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_make_request_422_no_retry(monkeypatch):
    call_count = 0

    class _CountingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None):
            nonlocal call_count
            call_count += 1
            return _FakeResponse(status_code=422, text="Invalid params", headers={})

    monkeypatch.setattr(
        odds_module.httpx,
        "AsyncClient",
        lambda timeout=30.0: _CountingClient(),
    )

    provider = _make_provider()

    with pytest.raises(odds_module.OddsAPIError) as exc_info:
        await provider._make_request("/v4/test", {})

    assert exc_info.value.status_code == 422
    assert call_count == 1  # No retries for 422


# ---------------------------------------------------------------------------
# 9. _make_request handles 429 error (retries)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_make_request_429_retries(monkeypatch):
    call_count = 0

    class _RetryClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None):
            nonlocal call_count
            call_count += 1
            return _FakeResponse(status_code=429, text="Rate limited", headers={})

    monkeypatch.setattr(
        odds_module.httpx,
        "AsyncClient",
        lambda timeout=30.0: _RetryClient(),
    )

    provider = _make_provider()

    with pytest.raises(odds_module.OddsAPIError) as exc_info:
        await provider._make_request("/v4/test", {}, max_retries=3)

    assert exc_info.value.status_code == 429
    assert call_count == 3  # Should have retried 3 times


# ---------------------------------------------------------------------------
# 10. _make_request handles timeout (retries)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_make_request_timeout_retries(monkeypatch):
    import httpx

    call_count = 0

    class _TimeoutClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None):
            nonlocal call_count
            call_count += 1
            raise httpx.TimeoutException("Connection timed out")

    monkeypatch.setattr(
        odds_module.httpx,
        "AsyncClient",
        lambda timeout=30.0: _TimeoutClient(),
    )

    provider = _make_provider()

    with pytest.raises(odds_module.OddsAPIError) as exc_info:
        await provider._make_request("/v4/test", {}, max_retries=2)

    assert "timeout" in str(exc_info.value).lower()
    assert call_count == 2


# ---------------------------------------------------------------------------
# 11. _make_request handles request error (retries)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_make_request_request_error_retries(monkeypatch):
    import httpx

    call_count = 0

    class _ErrorClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None):
            nonlocal call_count
            call_count += 1
            raise httpx.RequestError("Connection refused")

    monkeypatch.setattr(
        odds_module.httpx,
        "AsyncClient",
        lambda timeout=30.0: _ErrorClient(),
    )

    provider = _make_provider()

    with pytest.raises(odds_module.OddsAPIError) as exc_info:
        await provider._make_request("/v4/test", {}, max_retries=3)

    assert "request error" in str(exc_info.value).lower()
    assert call_count == 3


# ---------------------------------------------------------------------------
# 12. _parse_header_int parses valid int
# ---------------------------------------------------------------------------

def test_parse_header_int_valid():
    assert odds_module.TheOddsAPIProvider._parse_header_int("123") == 123
    assert odds_module.TheOddsAPIProvider._parse_header_int("0") == 0
    assert odds_module.TheOddsAPIProvider._parse_header_int("999") == 999


# ---------------------------------------------------------------------------
# 13. _parse_header_int returns None for None/invalid
# ---------------------------------------------------------------------------

def test_parse_header_int_none():
    assert odds_module.TheOddsAPIProvider._parse_header_int(None) is None


def test_parse_header_int_invalid():
    assert odds_module.TheOddsAPIProvider._parse_header_int("abc") is None
    assert odds_module.TheOddsAPIProvider._parse_header_int("12.5") is None
    assert odds_module.TheOddsAPIProvider._parse_header_int("") is None
