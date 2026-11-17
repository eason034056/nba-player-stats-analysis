"""SPO-126 QA: recorded ESPN team names, LA collisions, provider signatures.

Every name comes from ``tests/fixtures/espn/team_directory.json`` (the
recorded ESPN team directory from SPO-97). No hand-typed API body.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
import os
import pkgutil
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.daily_analysis import TEAM_CODE_ALIASES, canonical_team_code
from app.services.odds_provider import OddsProvider, QuotaUsage

_DIRECTORY = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "espn"
    / "team_directory.json"
)
_NAME_FIELDS = ("abbreviation", "shortDisplayName", "displayName", "name")
_NBA_CODES = frozenset(TEAM_CODE_ALIASES.values())


def _directory(league: str) -> list[dict[str, Any]]:
    rows = json.loads(_DIRECTORY.read_text(encoding="utf-8"))
    return [row for row in rows if row.get("league") == league]


class TestRecordedNbaDirectory:
    def test_every_nba_spelling_resolves_to_one_code(self):
        teams = _directory("nba")
        assert len(teams) == 30
        resolved: dict[str, str] = {}
        for team in teams:
            codes = {canonical_team_code(team[field]) for field in _NAME_FIELDS}
            assert len(codes) == 1, (team["displayName"], codes)
            code = codes.pop()
            assert code in _NBA_CODES, (team["displayName"], code)
            resolved[team["displayName"]] = code
        assert sorted(resolved.values()) == sorted(_NBA_CODES)
        assert resolved["LA Clippers"] == "LAC"
        assert resolved["Los Angeles Lakers"] == "LAL"

    @pytest.mark.parametrize(
        "spelling, code",
        [
            ("NY", "NYK"),
            ("GS", "GSW"),
            ("SA", "SAS"),
            ("NO", "NOP"),
            ("UTAH", "UTA"),
            ("WSH", "WAS"),
            ("Utah Jazz", "UTA"),
            ("LAClippers", "LAC"),
            ("la-lakers", "LAL"),
        ],
    )
    def test_compact_forms_still_resolve(self, spelling: str, code: str):
        assert canonical_team_code(spelling) == code

    @pytest.mark.parametrize("bare", ["LA", "L.A.", "Los Angeles"])
    def test_bare_city_is_not_guessed(self, bare: str):
        assert canonical_team_code(bare) not in {"LAC", "LAL"}


class TestLaCollisions:
    def test_g_league_affiliates_do_not_borrow_the_parent_code(self):
        affiliates = {
            team["displayName"]
            for team in _directory("nba-development")
            if team["displayName"] in {"San Diego Clippers", "Coachella Valley Lakers"}
        }
        assert affiliates == {"San Diego Clippers", "Coachella Valley Lakers"}
        for name in affiliates:
            assert canonical_team_code(name) not in _NBA_CODES, name

    def test_wnba_full_names_never_land_on_an_nba_code(self):
        for team in _directory("wnba"):
            assert canonical_team_code(team["displayName"]) not in _NBA_CODES, (
                team["displayName"]
            )

    def test_recorded_sparks_stay_wnba(self):
        sparks = next(
            team for team in _directory("wnba") if team["shortDisplayName"] == "Sparks"
        )
        assert canonical_team_code(sparks["displayName"], league="wnba") == "LAS"
        assert canonical_team_code(sparks["displayName"]) not in {"LAC", "LAL"}
        assert canonical_team_code("LA Sparks") not in {"LAC", "LAL"}

    def test_unknown_league_still_raises(self):
        with pytest.raises(ValueError):
            canonical_team_code("LA Clippers", league="nfl")


def _all_app_service_providers() -> list[type]:
    import app.services as services

    for module in pkgutil.iter_modules(services.__path__):
        try:
            importlib.import_module(f"app.services.{module.name}")
        except Exception:  # optional deps (Postgres, RAG) may be absent
            continue
    found: list[type] = []
    pending = list(OddsProvider.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        if cls.__module__.startswith("app."):
            found.append(cls)
    return found


class TestProviderSignatures:
    @pytest.mark.parametrize(
        "method",
        ["get_events", "get_event_odds", "list_events", "get_event_props", "rate_status"],
    )
    def test_concrete_providers_accept_the_abstract_parameters(self, method: str):
        abstract = inspect.signature(getattr(OddsProvider, method))
        providers = [cls for cls in _all_app_service_providers() if not inspect.isabstract(cls)]
        assert providers, "no concrete OddsProvider in app.services"
        for cls in providers:
            impl = getattr(cls, method)
            assert inspect.iscoroutinefunction(impl), (cls.__qualname__, method)
            params = inspect.signature(impl).parameters
            for name, param in abstract.parameters.items():
                assert name in params, (cls.__qualname__, method, name)
                assert params[name].kind == param.kind, (cls.__qualname__, name)

    def test_the_odds_api_provider_still_constructs(self):
        from app.services.odds_theoddsapi import TheOddsAPIProvider

        provider = TheOddsAPIProvider()
        assert isinstance(provider, OddsProvider)


class TestQuotaUsageValue:
    def test_frozen_defaults_and_derived_values(self):
        empty = QuotaUsage()
        assert (empty.remaining, empty.used, empty.last) == (None, None, None)
        assert empty.total is None
        assert empty.remaining_ratio is None
        assert QuotaUsage(remaining=0, used=0).remaining_ratio is None
        usage = QuotaUsage(remaining=900, used=100, last=1)
        with pytest.raises(dataclasses.FrozenInstanceError):
            usage.remaining = 1  # type: ignore[misc]
        assert usage == QuotaUsage(remaining=900, used=100, last=1)
        assert hash(usage) == hash(QuotaUsage(remaining=900, used=100, last=1))
        assert dataclasses.replace(usage, remaining=899).remaining == 899
        assert usage.remaining_ratio == 0.9
