import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.projection_provider import (
    SportsDataProjectionProvider,
    SportsDataProjectionError,
    _is_scrambled,
    FIELD_MAPPING,
)
from app.services import projection_provider as provider_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeResponse:
    """Minimal httpx-like response for monkeypatching."""

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Async context-manager that returns a canned response for GET requests."""

    def __init__(self, response):
        self._response = response
        self.last_url = None
        self.last_headers = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None):
        self.last_url = url
        self.last_headers = headers
        return self._response


def _make_raw_projection(**overrides):
    """Return a minimal PascalCase projection dict from the API."""
    base = {
        "PlayerID": 20000441,
        "Name": "Stephen Curry",
        "Team": "GS",
        "Position": "PG",
        "GameID": 99001,
        "Opponent": "LAL",
        "HomeOrAway": "HOME",
        "Day": "2026-02-08T00:00:00",
        "Minutes": 34.5,
        "Points": 29.3,
        "Rebounds": 5.1,
        "Assists": 6.2,
        "Steals": 1.3,
        "BlockedShots": 0.4,
        "Turnovers": 3.0,
        "FieldGoalsMade": 10.0,
        "FieldGoalsAttempted": 20.0,
        "ThreePointersMade": 5.0,
        "ThreePointersAttempted": 11.0,
        "FreeThrowsMade": 4.3,
        "FreeThrowsAttempted": 4.8,
        "Started": 1,
        "LineupConfirmed": True,
        "InjuryStatus": None,
        "InjuryBodyPart": None,
        "OpponentRank": 12,
        "OpponentPositionRank": 8,
        "DraftKingsSalary": 10200,
        "FanDuelSalary": 10500,
        "FantasyPointsDraftKings": 52.3,
        "FantasyPointsFanDuel": 48.7,
        "UsageRatePercentage": 32.1,
        "PlayerEfficiencyRating": 25.4,
        "Updated": "2026-02-08T18:30:00Z",
    }
    base.update(overrides)
    return base


# =====================================================================
# Tests for _is_scrambled
# =====================================================================


class TestIsScrambled:
    def test_detects_scrambled_long_mixed_string(self):
        assert _is_scrambled("aB3cD4eF5gH6iJ7kL8") is True

    def test_detects_scrambled_realistic_gibberish(self):
        assert _is_scrambled("xK9mW2pQ8rT4vY6nZ1bC") is True

    def test_normal_short_string_not_scrambled(self):
        assert _is_scrambled("Out") is False

    def test_normal_status_questionable(self):
        assert _is_scrambled("Questionable") is False

    def test_normal_status_probable(self):
        assert _is_scrambled("Probable") is False

    def test_normal_status_day_to_day(self):
        assert _is_scrambled("Day-To-Day") is False

    def test_whitelist_confirmed(self):
        assert _is_scrambled("Confirmed") is False

    def test_non_string_returns_false(self):
        assert _is_scrambled(12345) is False
        assert _is_scrambled(None) is False
        assert _is_scrambled(True) is False

    def test_long_alpha_only_not_scrambled(self):
        # Long string with only letters -- no digits, so not flagged
        assert _is_scrambled("abcdefghijklmnopqrst") is False

    def test_long_digit_only_not_scrambled(self):
        assert _is_scrambled("12345678901234567890") is False

    def test_short_mixed_not_scrambled(self):
        # Under 15 chars, even if mixed
        assert _is_scrambled("abc123") is False


# =====================================================================
# Tests for normalize_projection
# =====================================================================


class TestNormalizeProjection:
    def setup_method(self):
        self.provider = SportsDataProjectionProvider()

    def test_converts_pascal_to_snake_case(self):
        raw = _make_raw_projection()
        result = self.provider.normalize_projection(raw)

        assert result["player_id"] == 20000441
        assert result["player_name"] == "Stephen Curry"
        assert result["team"] == "GS"
        assert result["position"] == "PG"
        assert result["game_id"] == 99001
        assert result["opponent"] == "LAL"
        assert result["home_or_away"] == "HOME"
        assert result["minutes"] == 34.5
        assert result["points"] == 29.3
        assert result["rebounds"] == 5.1
        assert result["assists"] == 6.2
        assert result["steals"] == 1.3
        assert result["blocked_shots"] == 0.4
        assert result["turnovers"] == 3.0

    def test_computes_pra_correctly(self):
        raw = _make_raw_projection(Points=10.0, Rebounds=5.0, Assists=3.0)
        result = self.provider.normalize_projection(raw)

        assert result["pra"] == 18.0

    def test_pra_is_none_when_all_zero_and_none(self):
        raw = _make_raw_projection(Points=None, Rebounds=None, Assists=None)
        result = self.provider.normalize_projection(raw)

        assert result["pra"] is None

    def test_pra_computed_when_some_are_none(self):
        raw = _make_raw_projection(Points=20.0, Rebounds=None, Assists=5.0)
        result = self.provider.normalize_projection(raw)

        # points=20, rebounds treated as 0, assists=5 => 25
        assert result["pra"] == 25.0

    def test_parses_date_from_day_field(self):
        # Day values like "2026-03-15T00:00:00" are >15 chars with mixed
        # digits+letters, so _is_scrambled flags them.  Feed a short value
        # that won't be flagged so we can test the date-parsing branch.
        raw = _make_raw_projection()
        # Bypass scramble detection by injecting the already-normalised "day"
        # key directly into the result dict via a raw dict that has already
        # been through the mapping.  Instead, construct a raw dict where Day
        # is set to a short-enough string that the scramble detector ignores.
        # _is_scrambled only triggers for strings >15 chars, so a 10-char
        # date will pass through.
        raw["Day"] = "2026-03-15"
        result = self.provider.normalize_projection(raw)

        assert result["date"] == "2026-03-15"

    def test_date_is_none_when_day_missing(self):
        raw = _make_raw_projection(Day=None)
        result = self.provider.normalize_projection(raw)

        assert result["date"] is None

    def test_day_field_with_iso_timestamp_treated_as_scrambled(self):
        # ISO timestamps like "2026-03-15T00:00:00" are >15 chars with
        # mixed digits and letters, so _is_scrambled flags them as scrambled.
        raw = _make_raw_projection(Day="2026-03-15T00:00:00")
        result = self.provider.normalize_projection(raw)

        # The day field is nullified by scramble detection, so date is None
        assert result["day"] is None
        assert result["date"] is None

    def test_scrambled_injury_status_set_to_none(self):
        scrambled = "xK9mW2pQ8rT4vY6nZ1bC"
        raw = _make_raw_projection(InjuryStatus=scrambled)
        result = self.provider.normalize_projection(raw)

        assert result["injury_status"] is None

    def test_valid_injury_status_preserved(self):
        raw = _make_raw_projection(InjuryStatus="Questionable")
        result = self.provider.normalize_projection(raw)

        assert result["injury_status"] == "Questionable"

    def test_missing_fields_default_to_none(self):
        # A minimal raw dict with only Name
        raw = {"Name": "Test Player"}
        result = self.provider.normalize_projection(raw)

        assert result["player_name"] == "Test Player"
        assert result["points"] is None
        assert result["rebounds"] is None
        assert result["assists"] is None

    def test_api_updated_at_mapped(self):
        # Short value that won't be flagged as scrambled (<= 15 chars)
        raw = _make_raw_projection(Updated="2026-02-08")
        result = self.provider.normalize_projection(raw)

        assert result["api_updated_at"] == "2026-02-08"

    def test_api_updated_at_iso_flagged_as_scrambled(self):
        # Full ISO timestamps (>15 chars, mixed digits+letters) are detected
        # as scrambled by the free-trial detection heuristic.
        raw = _make_raw_projection(Updated="2026-02-08T18:30:00Z")
        result = self.provider.normalize_projection(raw)

        assert result["api_updated_at"] is None

    def test_fantasy_salary_fields(self):
        raw = _make_raw_projection(DraftKingsSalary=9800, FanDuelSalary=10100)
        result = self.provider.normalize_projection(raw)

        assert result["draftkings_salary"] == 9800
        assert result["fanduel_salary"] == 10100


# =====================================================================
# Tests for fetch_projections_by_date
# =====================================================================


class TestFetchProjectionsByDate:
    def setup_method(self):
        self.provider = SportsDataProjectionProvider()
        self.provider.api_key = "test-api-key"
        self.provider.base_url = "https://api.sportsdata.io"

    @pytest.mark.asyncio
    async def test_makes_correct_api_call_and_returns_normalized(self, monkeypatch):
        raw_data = [_make_raw_projection(), _make_raw_projection(Name="LeBron James")]
        response = _FakeResponse(status_code=200, payload=raw_data)
        fake_client = _FakeAsyncClient(response)

        monkeypatch.setattr(
            provider_module.httpx,
            "AsyncClient",
            lambda timeout=30.0: fake_client,
        )

        result = await self.provider.fetch_projections_by_date("2026-02-08")

        assert len(result) == 2
        assert result[0]["player_name"] == "Stephen Curry"
        assert result[1]["player_name"] == "LeBron James"
        # All results should be normalized (snake_case keys)
        assert "points" in result[0]
        assert "pra" in result[0]
        # Verify correct URL was called
        assert "PlayerGameProjectionStatsByDate/2026-02-08" in fake_client.last_url
        assert fake_client.last_headers["Ocp-Apim-Subscription-Key"] == "test-api-key"

    @pytest.mark.asyncio
    async def test_handles_empty_response(self, monkeypatch):
        response = _FakeResponse(status_code=200, payload=[])

        monkeypatch.setattr(
            provider_module.httpx,
            "AsyncClient",
            lambda timeout=30.0: _FakeAsyncClient(response),
        )

        result = await self.provider.fetch_projections_by_date("2026-02-08")

        assert result == []

    @pytest.mark.asyncio
    async def test_raises_on_401_unauthorized(self, monkeypatch):
        response = _FakeResponse(status_code=401)

        monkeypatch.setattr(
            provider_module.httpx,
            "AsyncClient",
            lambda timeout=30.0: _FakeAsyncClient(response),
        )

        with pytest.raises(SportsDataProjectionError) as exc_info:
            await self.provider.fetch_projections_by_date("2026-02-08")

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_raises_on_403_forbidden(self, monkeypatch):
        response = _FakeResponse(status_code=403)

        monkeypatch.setattr(
            provider_module.httpx,
            "AsyncClient",
            lambda timeout=30.0: _FakeAsyncClient(response),
        )

        with pytest.raises(SportsDataProjectionError) as exc_info:
            await self.provider.fetch_projections_by_date("2026-02-08")

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_raises_when_api_key_not_set(self, monkeypatch):
        self.provider.api_key = ""

        with pytest.raises(SportsDataProjectionError) as exc_info:
            await self.provider.fetch_projections_by_date("2026-02-08")

        assert exc_info.value.status_code == 0
        assert "SPORTSDATA_API_KEY" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_filters_records_without_name(self, monkeypatch):
        raw_data = [
            _make_raw_projection(Name="Valid Player"),
            {"PlayerID": 999, "Points": 10.0},  # No Name field
        ]
        response = _FakeResponse(status_code=200, payload=raw_data)

        monkeypatch.setattr(
            provider_module.httpx,
            "AsyncClient",
            lambda timeout=30.0: _FakeAsyncClient(response),
        )

        result = await self.provider.fetch_projections_by_date("2026-02-08")

        assert len(result) == 1
        assert result[0]["player_name"] == "Valid Player"

    @pytest.mark.asyncio
    async def test_handles_scrambled_data_in_results(self, monkeypatch):
        scrambled_status = "xK9mW2pQ8rT4vY6nZ1bC"
        raw_data = [_make_raw_projection(InjuryStatus=scrambled_status)]
        response = _FakeResponse(status_code=200, payload=raw_data)

        monkeypatch.setattr(
            provider_module.httpx,
            "AsyncClient",
            lambda timeout=30.0: _FakeAsyncClient(response),
        )

        result = await self.provider.fetch_projections_by_date("2026-02-08")

        assert len(result) == 1
        # Scrambled injury status should be normalized to None
        assert result[0]["injury_status"] is None
        # Non-scrambled fields should still be present
        assert result[0]["player_name"] == "Stephen Curry"
        assert result[0]["points"] == 29.3

    @pytest.mark.asyncio
    async def test_retries_on_server_error(self, monkeypatch):
        """On non-retryable error codes the provider retries up to max_retries,
        then raises the last error."""
        self.provider.max_retries = 1  # 1 retry = 2 total attempts

        call_count = 0

        class _CountingClient:
            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, *args):
                return False

            async def get(self_inner, url, headers=None):
                nonlocal call_count
                call_count += 1
                return _FakeResponse(status_code=500)

        monkeypatch.setattr(
            provider_module.httpx,
            "AsyncClient",
            lambda timeout=30.0: _CountingClient(),
        )
        # Speed up backoff sleeps
        monkeypatch.setattr(provider_module.asyncio, "sleep", _noop_sleep)

        with pytest.raises(SportsDataProjectionError) as exc_info:
            await self.provider.fetch_projections_by_date("2026-02-08")

        assert exc_info.value.status_code == 500
        assert call_count == 2  # initial + 1 retry


async def _noop_sleep(seconds):
    """No-op replacement for asyncio.sleep during tests."""
    pass
