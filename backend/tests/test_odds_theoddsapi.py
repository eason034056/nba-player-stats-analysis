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
