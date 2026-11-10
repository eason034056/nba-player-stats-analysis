"""SPO-112 Platt cutoff: what is fit, and which rows are allowed in.

The stored pair is PLATT_A / PLATT_B in ``pick_signal_constants``. The fit
compares ``row.date`` to the cutoff with ``<=`` / ``>``. Those dates are
``YYYY-MM-DD`` strings from ``strftime``, so the order is lexicographic.
The cutoff day is included in the fit and excluded from the holdout.
"""

from __future__ import annotations

import re

import numpy as np
import pytest

from evaluation.fit_combined_platt import DEFAULT_CUTOFF, fit_platt
from evaluation.walk_forward import DailyRow

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _row(date: str, adjustment: float, hit: int, *, proxy: str = "MED20", pick: str | None = "over") -> DailyRow:
    """One settled MED20 row. ``date`` is stored the way the replay stores it."""
    return DailyRow(
        "nba",
        proxy,
        date,
        "points",
        20.5,
        22.0 if hit else 10.0,
        20,
        32.0,
        0.70,
        0.25,
        hit,
        pick,
        0.70,
        hit,
        "proxy",
        None,
        None,
        None,
        "regular_season",
        0.60,
        adjustment,
    )


def _patch_replay(monkeypatch, rows: list[DailyRow]):
    """Make ``main`` replay ``rows`` and capture the sample it would write."""
    import evaluation.fit_combined_platt as fit
    import evaluation.walk_forward as walk_forward

    captured: dict = {}

    class _Historical:
        def _csv_for(self, league: str):
            assert league == "nba"
            return object()

    class _Replay:
        daily = rows

    def _load():
        return _Historical()

    def _replay(service, league, proxies, **kwargs):
        assert league == "nba"
        assert proxies == ["MED20"]
        assert kwargs.get("do_agent") is False
        assert kwargs.get("validate") == 0
        return _Replay()

    def _capture(intercept: float, slope: float, sample: dict) -> None:
        captured["intercept"] = intercept
        captured["slope"] = slope
        captured["sample"] = sample

    monkeypatch.setattr(walk_forward, "load_historical", _load)
    monkeypatch.setattr(walk_forward, "replay_league", _replay)
    monkeypatch.setattr(fit, "_write_constants", _capture)
    return captured


def test_default_cutoff_is_an_inclusive_string_compare(monkeypatch):
    """Rows after 2026-03-17 never reach fit_platt. The cutoff day does.

    ``2026-03-09`` is before the cutoff only because both strings are
    zero-padded. ``2026-03-17T12:00:00`` sorts after ``2026-03-17`` and is
    held out, which shows the comparison does not parse a datetime.
    """
    import evaluation.fit_combined_platt as fit

    train_mark = 0.01
    cutoff_mark = 0.11
    next_day_mark = 0.21
    later_mark = 0.31
    timestamp_mark = 0.41
    rows: list[DailyRow] = []
    for index in range(20):
        rows.append(_row("2025-11-09", train_mark, index % 2))
        rows.append(_row("2026-03-09", train_mark, index % 2))
    for index in range(20):
        rows.append(_row("2026-03-17", cutoff_mark, index % 2))
    for index in range(20):
        rows.append(_row("2026-03-18", next_day_mark, index % 2))
        rows.append(_row("2026-05-11", later_mark, index % 2))
    rows.append(_row("2026-03-17T12:00:00", timestamp_mark, 1))
    # These pass the date cut but fail the settled-pick filter.
    rows.append(_row("2026-01-01", 0.99, 1, proxy="L10"))
    rows.append(_row("2026-01-02", 0.99, 1, pick=None))
    rows.append(
        DailyRow(
            "nba", "MED20", "2026-01-03", "points", 20.5, 22.0, 20, 32.0,
            0.7, 0.25, 1, "over", 0.7, 1, "proxy", None, None, None,
            "regular_season", 0.6, None,
        )
    )

    seen: dict[str, list] = {"fit": [], "score": []}
    real_fit = fit.fit_platt
    real_score = fit._score

    def _spy_fit(adjustments, outcomes):
        seen["fit"].append([float(value) for value in adjustments])
        return real_fit(adjustments, outcomes)

    def _spy_score(adjustments, outcomes, intercept, slope):
        seen["score"].append([float(value) for value in adjustments])
        return real_score(adjustments, outcomes, intercept, slope)

    monkeypatch.setattr(fit, "fit_platt", _spy_fit)
    monkeypatch.setattr(fit, "_score", _spy_score)
    captured = _patch_replay(monkeypatch, rows)
    fit.main([])

    assert DEFAULT_CUTOFF == "2026-03-17"
    fitted = seen["fit"][0]
    assert cutoff_mark in fitted
    assert train_mark in fitted
    assert next_day_mark not in fitted
    assert later_mark not in fitted
    assert timestamp_mark not in fitted
    assert 0.99 not in fitted
    assert fitted.count(cutoff_mark) == 20
    assert captured["sample"]["cutoff"] == "2026-03-17"
    assert captured["sample"]["n"] == len(fitted)
    assert captured["sample"]["date_start"] == "2025-11-09"
    assert captured["sample"]["date_end"] == "2026-03-17"
    assert captured["sample"]["date_end"] <= captured["sample"]["cutoff"]
    # Holdout score is the second _score call. It is only post-cutoff rows.
    holdout_marks = set(seen["score"][1])
    assert holdout_marks <= {next_day_mark, later_mark, timestamp_mark}
    assert train_mark not in holdout_marks
    assert cutoff_mark not in holdout_marks
    assert captured["sample"]["holdout_n"] == len(seen["score"][1])


def test_stored_constants_match_the_default_cutoff_on_committed_data():
    """Refit NBA MED20 on the committed CSV. Do not rewrite the constants file."""
    import evaluation.fit_combined_platt as fit
    from evaluation.paths import bootstrap

    bootstrap()
    from app.services.pick_signal_constants import FIT_SAMPLE, PLATT_A, PLATT_B
    from evaluation.walk_forward import load_historical, replay_league

    historical = load_historical()
    service = historical._csv_for("nba")
    replay = replay_league(
        service,
        "nba",
        ["MED20"],
        players=None,
        do_agent=False,
        validate=0,
    )
    rows = [
        row
        for row in replay.daily
        if row.proxy == "MED20"
        and row.pick is not None
        and row.hit is not None
        and row.combined_adjustment is not None
    ]
    assert rows
    assert all(isinstance(row.date, str) and _DATE.fullmatch(row.date) for row in rows)
    rows.sort(key=lambda row: row.date)
    cutoff = DEFAULT_CUTOFF
    train = [row for row in rows if row.date <= cutoff]
    hold = [row for row in rows if row.date > cutoff]
    assert train and hold
    assert all(row.date <= cutoff for row in train)
    assert all(row.date > cutoff for row in hold)
    assert any(row.date == cutoff for row in train)
    assert not any(row.date == cutoff for row in hold)
    # String order, not a datetime parse: the cutoff day is the last train day
    # when the replay actually has a game that day.
    assert train[-1].date <= cutoff
    assert hold[0].date > cutoff

    adjustments = np.array([float(row.combined_adjustment) for row in train])
    outcomes = np.array([float(row.hit) for row in train])
    intercept, slope = fit_platt(adjustments, outcomes)
    assert f"{intercept:.8f}" == f"{PLATT_A:.8f}" == "0.28036258"
    assert f"{slope:.8f}" == f"{PLATT_B:.8f}" == "2.15982400"
    assert len(train) == FIT_SAMPLE["n"] == 34507
    assert train[0].date == FIT_SAMPLE["date_start"] == "2025-11-09"
    assert train[-1].date == FIT_SAMPLE["date_end"] == "2026-03-17"
    assert FIT_SAMPLE["cutoff"] == cutoff
    assert FIT_SAMPLE["market_prior"] == 0.5
    assert FIT_SAMPLE["game_types"] == "regular_season"
    assert len(hold) == 13751
    from evaluation.walk_forward import _history_types

    allowed = _history_types()
    assert allowed == {"regular_season"}
    assert all(row.game_type in allowed for row in rows)
    assert all(row.game_type not in {"playoffs", "play_in"} for row in rows)
    assert replay.postseason_daily
    assert all(row.game_type not in allowed for row in replay.postseason_daily)
