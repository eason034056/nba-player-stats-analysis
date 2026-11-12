"""SPO-135e: injury names match with the suffix kept.

The recorded injury page has no Gary Trent row and no Luka Doncic row.
Each row below is a normalized fixture entry with only ``player``
changed. Odds API outcomes and snapshot rows have no ``bdl_player_id``.
Picks and /reads therefore match on the name only.
"""

from __future__ import annotations

import asyncio

from app.models.schemas import DailyPick, PropRead
from app.services.nba_injuries import match_injury_entry
from tests.fixtures.odds_api import load_odds_fixture
from tests.test_spo121_bulk_reads import _FakeCache, _FakeDB, _points_rows
from tests.test_spo135c_bdl_injury_status import _entry, _named, _picks_for
from tests.test_spo135e_event_reads_injuries import _Csv, _fresh, _relabel


def _renamed(entry: dict, player: str) -> dict:
    """Fixture row. Only the stored player name changes."""
    row = dict(entry)
    row["player"] = player
    return row


def test_jr_out_does_not_block_the_name_without_the_suffix() -> None:
    """Gary Trent Jr. Out does not block Gary Trent, and the reverse."""
    base = _entry("Out")
    junior = _renamed(base, "Gary Trent Jr.")
    picks = _picks_for(["Gary Trent"], [junior])
    assert {row.injury_status for row in _named(picks, "Gary Trent")} == {None}
    assert all(row.combined_probability is not None for row in picks)

    senior = _renamed(base, "Gary Trent")
    picks = _picks_for(["Gary Trent Jr."], [senior])
    assert {row.injury_status for row in _named(picks, "Gary Trent Jr.")} == {None}
    assert all(row.combined_probability is not None for row in picks)
    assert match_injury_entry([junior], "Gary Trent") is None
    assert match_injury_entry([senior], "Gary Trent Jr.") is None


def test_accent_and_punctuation_match_and_block() -> None:
    """Case, accents, and punctuation fold. The suffix stays."""
    base = _entry("Out")
    accent = _renamed(base, "Luka Dončić")
    picks = _picks_for(["luka doncic"], [accent])
    assert {row.injury_status for row in _named(picks, "luka doncic")} == {"Out"}
    assert {row.combined_probability for row in picks} == {None}

    punctuated = _renamed(base, "Gary Trent, Jr.")
    picks = _picks_for(["gary trent jr"], [punctuated])
    assert {row.injury_status for row in _named(picks, "gary trent jr")} == {"Out"}
    assert {row.combined_probability for row in picks} == {None}
    assert match_injury_entry([punctuated], "Gary Trent Jr.") is punctuated
    assert match_injury_entry([accent], "Luka Doncic") is accent


def test_same_full_name_with_two_ids_is_not_guessed() -> None:
    """Two fixture rows, names set to one string, different ids, stay null."""
    left = _renamed(_entry("Out"), "Gary Trent Jr.")
    right = _renamed(_entry("Questionable"), "Gary Trent Jr.")
    assert left["bdl_player_id"] != right["bdl_player_id"]
    picks = _picks_for(["Gary Trent Jr."], [left, right])
    assert {row.injury_status for row in _named(picks, "Gary Trent Jr.")} == {None}
    assert all(row.combined_probability is not None for row in picks)
    assert match_injury_entry([left, right], "Gary Trent Jr.") is None


def test_bdl_id_still_wins_when_both_sides_have_it() -> None:
    """The id path stays for callers that actually have one. Picks do not."""
    junior = _renamed(_entry("Out"), "Gary Trent Jr.")
    senior = _renamed(_entry("Questionable"), "Gary Trent")
    assert (
        match_injury_entry([senior, junior], "someone else", junior["bdl_player_id"])
        is junior
    )


def test_pick_and_reads_rows_have_no_bdl_player_id() -> None:
    """Odds descriptions and snapshot rows are names. DailyPick has no id."""
    assert "bdl_player_id" not in DailyPick.model_fields
    assert "bdl_player_id" not in PropRead.model_fields
    event = load_odds_fixture("odds_api_event_odds__player_points.json")
    outcome_keys: set[str] = set()
    for book in event["bookmakers"]:
        for market in book.get("markets") or []:
            for outcome in market.get("outcomes") or []:
                outcome_keys.update(outcome.keys())
    assert "bdl_player_id" not in outcome_keys
    _event_id, rows = _points_rows()
    assert rows
    assert "bdl_player_id" not in rows[0]


def _reads_for(monkeypatch, rows, entries):
    cache = _FakeCache()
    cache.store["injuries:nba:latest"] = _fresh(entries)
    monkeypatch.setattr("app.services.event_reads.cache_service", cache)
    monkeypatch.setattr("app.services.cache.cache_service", cache)
    monkeypatch.setattr("app.services.event_reads.db_service", _FakeDB(rows))
    from app.services.event_reads import get_event_reads

    event_id = rows[0]["event_id"]
    return asyncio.run(
        get_event_reads(event_id, market="player_points", csv_service=_Csv())
    )


def test_reads_use_the_same_suffix_rule(monkeypatch) -> None:
    """/reads blocks gary trent jr and does not block Gary Trent."""
    junior = _renamed(_entry("Out"), "Gary Trent Jr.")
    _event_id, rows = _points_rows()
    posted = sorted({row["player_name"] for row in rows})
    source = posted[0]
    open_payload = _reads_for(monkeypatch, _relabel(rows, source, "Gary Trent"), [junior])
    open_rows = [item for item in open_payload.reads if item.player == "Gary Trent"]
    assert open_rows
    assert all(item.combined_probability is not None for item in open_rows)

    blocked_payload = _reads_for(
        monkeypatch, _relabel(rows, source, "gary trent jr"), [junior]
    )
    blocked = [item for item in blocked_payload.reads if item.player == "gary trent jr"]
    assert blocked
    assert {item.combined_probability for item in blocked} == {None}
