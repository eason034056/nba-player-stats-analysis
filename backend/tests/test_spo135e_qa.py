"""SPO-135e QA: /reads parity, startup window, and recorded-name folds.

Questionable and raw Doubtful on /reads both keep a blend. A
malformed snapshot leaves the blend. Startup does not refill a
malformed key outside the slate window. The recorded player_points
capture lists C.J. McCollum; punctuation folds to a CJ McCollum
injury row. The recorded injury page lists Jaren Jackson Jr. Out;
the stem does not match.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import pytest

from app.services.nba_injuries import (
    normalize_bdl_injuries,
    team_id_to_code_from_standings,
)
from tests.test_spo121_bulk_reads import _points_rows
from tests.test_spo131_bdl_injuries import INJURY_PAGE, STANDINGS
from tests.test_spo135c_bdl_injury_status import _entry
from tests.test_spo135e_event_reads_injuries import (
    _by_player,
    _Csv,
    _fresh,
    _install,
    _relabel,
)
from tests.test_spo135e_injury_name_match import _renamed
from tests.test_spo135e_injury_restart import _body, _spy
from tests.test_spo135e_injury_restart import _install as _startup_install


def _recorded_jaren_jr() -> dict:
    """The recorded injury page row, not a renamed copy."""
    mapping = team_id_to_code_from_standings(STANDINGS)
    entries = normalize_bdl_injuries(
        INJURY_PAGE["data"],
        mapping,
        fetched_at="2026-11-11T18:00:00+00:00",
    )
    for row in entries:
        if row["player"] == "Jaren Jackson Jr.":
            return row
    raise AssertionError("recorded page has no Jaren Jackson Jr. row")


def test_reads_questionable_and_raw_doubtful_keep_the_same_blend(
    monkeypatch,
) -> None:
    """Parity with daily picks: Questionable and raw Doubtful keep a number."""
    questionable = _entry("Questionable")
    doubtful = _entry("Questionable", raw="Doubtful")
    event_id, rows = _points_rows()
    posted = sorted({row["player_name"] for row in rows})
    sources = [name for name in posted if name != "Dyson Daniels"]
    assert len(sources) >= 2
    rows = _relabel(rows, sources[0], questionable["player"])
    rows = _relabel(rows, sources[1], doubtful["player"])
    _install(
        monkeypatch,
        rows,
        injury_body=_fresh([questionable, doubtful]),
    )

    from app.services.event_reads import get_event_reads

    payload = asyncio.run(
        get_event_reads(event_id, market="player_points", csv_service=_Csv())
    )
    q_rows = _by_player(payload, questionable["player"])
    d_rows = _by_player(payload, doubtful["player"])
    assert all(item.combined_probability is not None for item in q_rows)
    assert all(0.0 < item.combined_probability < 1.0 for item in q_rows)
    assert all(item.combined_probability is not None for item in d_rows)
    assert all(0.0 < item.combined_probability < 1.0 for item in d_rows)


def test_malformed_snapshot_warns_once_and_reads_keep_a_blend(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    out = _entry("Out")
    event_id, rows = _points_rows()
    posted = sorted({row["player_name"] for row in rows})
    source = next(name for name in posted if name != "Dyson Daniels")
    rows = _relabel(rows, source, out["player"])
    _install(
        monkeypatch,
        rows,
        injury_body={
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "entries": "nope",
        },
    )

    from app.services.event_reads import get_event_reads

    with caplog.at_level(logging.WARNING):
        payload = asyncio.run(
            get_event_reads(event_id, market="player_points", csv_service=_Csv())
        )
    warnings = [
        record
        for record in caplog.records
        if record.levelno >= logging.WARNING and "malformed" in record.getMessage()
    ]
    assert len(warnings) == 1
    assert "http" not in warnings[0].getMessage().lower()
    assert all(
        item.combined_probability is not None
        for item in _by_player(payload, out["player"])
    )


def test_startup_does_not_refill_a_malformed_key_outside_the_window(
    monkeypatch,
) -> None:
    calls = _spy(monkeypatch)
    _startup_install(monkeypatch, inside=False, raw=_body(stale=False, entries="nope"))
    from app.services.scheduler import SchedulerService

    asyncio.run(SchedulerService()._fill_nba_injuries_if_missing())
    assert calls == []


def test_recorded_odds_cj_mccollum_matches_a_cj_injury_row(monkeypatch) -> None:
    """The recorded player_points capture lists C.J. McCollum.

    Only the injury row's player field is set to CJ McCollum. Periods
    fold, so the posted description is blocked. Dyson Daniels stays open.
    """
    out = _renamed(_entry("Out"), "CJ McCollum")
    event_id, rows = _points_rows()
    posted = {row["player_name"] for row in rows}
    assert "C.J. McCollum" in posted
    assert "Dyson Daniels" in posted
    _install(monkeypatch, rows, injury_body=_fresh([out]))

    from app.services.event_reads import get_event_reads

    payload = asyncio.run(
        get_event_reads(event_id, market="player_points", csv_service=_Csv())
    )
    blocked = _by_player(payload, "C.J. McCollum")
    open_rows = _by_player(payload, "Dyson Daniels")
    assert {item.combined_probability for item in blocked} == {None}
    assert all(item.combined_probability is not None for item in open_rows)


def test_recorded_jaren_jr_out_does_not_block_the_stem_on_reads(
    monkeypatch,
) -> None:
    """The injury page lists Jaren Jackson Jr. Out. The stem stays open."""
    jaren = _recorded_jaren_jr()
    assert jaren["status"] == "Out"
    event_id, rows = _points_rows()
    posted = sorted({row["player_name"] for row in rows})
    sources = [name for name in posted if name != "Dyson Daniels"]
    assert len(sources) >= 2
    rows = _relabel(rows, sources[0], "Jaren Jackson")
    rows = _relabel(rows, sources[1], "Jaren Jackson Jr.")
    _install(monkeypatch, rows, injury_body=_fresh([jaren]))

    from app.services.event_reads import get_event_reads

    payload = asyncio.run(
        get_event_reads(event_id, market="player_points", csv_service=_Csv())
    )
    stem = _by_player(payload, "Jaren Jackson")
    junior = _by_player(payload, "Jaren Jackson Jr.")
    assert all(item.combined_probability is not None for item in stem)
    assert {item.combined_probability for item in junior} == {None}
