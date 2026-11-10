"""The walk-forward defense rank uses 1 for the defense that allowed the most."""

from __future__ import annotations

from datetime import datetime, timedelta

from evaluation.defense_ranks import DefenseRankIndex


def _game(when: datetime, opponent: str, points: float, position: str = "PG") -> dict:
    return {
        "game_date": when,
        "minutes": 30,
        "opponent": opponent,
        "pos": position,
        "points": points,
    }


def _cache() -> dict:
    start = datetime(2025, 1, 1)
    logs = []
    for offset in range(20):
        when = start + timedelta(days=offset)
        logs.append(_game(when, "A", 30))
        logs.append(_game(when, "B", 10))
    # Same slate as the query date. It must not move the rank.
    logs.append(_game(datetime(2025, 1, 21), "A", 80))
    return {"player": logs}


def test_rank_1_is_the_defense_that_allowed_more_before_the_date():
    index = DefenseRankIndex.from_cache(
        _cache(),
        ["points"],
        {"points": lambda game: game.get("points")},
    )
    query = datetime(2025, 1, 21)
    assert index.rank(query, "A", "points", "PG") == 1
    assert index.rank(query, "B", "points", "PG") == 2
    # No games are strictly before the first date.
    assert index.rank(datetime(2025, 1, 1), "A", "points", "PG") is None
    # The 80-point game on the 21st is visible only on the next date.
    assert index.rank(datetime(2025, 1, 22), "A", "points", "PG") == 1


def test_position_rank_is_preferred_when_its_sample_is_large_enough():
    start = datetime(2025, 1, 1)
    logs = []
    for offset in range(20):
        when = start + timedelta(days=offset)
        # Overall, A allows more. Against PGs, B allows more.
        logs.append(_game(when, "A", 30, "SG"))
        logs.append(_game(when, "B", 10, "SG"))
        if offset < 8:
            logs.append(_game(when, "A", 5, "PG"))
            logs.append(_game(when, "B", 40, "PG"))
    index = DefenseRankIndex.from_cache(
        {"player": logs},
        ["points"],
        {"points": lambda game: game.get("points")},
    )
    query = datetime(2025, 1, 21)
    assert index.rank(query, "B", "points", "PG") == 1
    assert index.rank(query, "A", "points", "SG") == 1
