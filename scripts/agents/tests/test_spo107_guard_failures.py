"""The production-rate guard must fail closed when the comparison disagrees.

These cases drive the real replay comparison, then the same exit
``backtest.py --guard-only`` uses. A dict handed to the recorder is not
enough: the mismatch has to be one the replay itself counts.
"""

from __future__ import annotations

import ast
import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

from evaluation.backtest import main
from evaluation.calibration_guard import (
    PRODUCTION_CHECK_ROWS,
    GuardResult,
    record_production_check,
    run_sample_guard,
)
from evaluation.paths import bootstrap
from evaluation.walk_forward import (
    LeagueReplay,
    replay_league,
    select_players,
)

bootstrap()

from app.services.csv_player_history import CSVPlayerHistoryService  # noqa: E402
from app.services.game_log_hygiene import (  # noqa: E402
    GAME_TYPE_CUP,
    GAME_TYPE_GLEAGUE,
    GAME_TYPE_PLAY_IN,
    GAME_TYPE_PLAYOFFS,
    GAME_TYPE_PRESEASON,
    GAME_TYPE_REGULAR,
    GAME_TYPE_SUMMER,
    GAME_TYPE_UNCLASSIFIED,
)

_ROOT = Path(__file__).resolve().parents[3]
_NBA_CSV = _ROOT / "data" / "nba_player_game_logs.csv"


class _Service:
    """Cache stand-in. ``replay_league`` only reads ``_cache`` on this path."""

    def __init__(self, cache: dict, league: str = "nba"):
        self._cache = cache
        self.league = league
        self._loaded = True


class _MedRow:
    """One MED20 pick, shaped the way ``summarize`` reads a daily row."""

    def __init__(self, prob: float, hit: int):
        self.proxy = "MED20"
        self.over_hit = hit
        self.actual = 11.0 if hit else 0.0
        self.line = 10.5
        self.p_over = prob
        self.pick = "over"
        self.hit = hit
        self.prob = prob
        self.price = None
        self.clv_prob = None
        self.clv_line = None


def _game(day: int, points: float, game_type: str, player: str = "Test Player") -> dict:
    return {
        "player_name": player,
        "game_date": datetime(2025, 11, 1) + timedelta(days=day),
        "minutes": 30.0,
        "points": points,
        "rebounds": 5.0,
        "assists": 4.0,
        "pra": points + 9.0,
        "team": "AAA",
        "season": "2025-2026",
        "game_type": game_type,
    }


def _logs() -> list[dict]:
    """Fourteen regular-season games and one playoff game inside that window."""
    regular = [_game(offset, 10.0, GAME_TYPE_REGULAR) for offset in range(14)]
    # Day 6 sits in the prior of every later target. 80 points changes
    # n_games and the over rate when the harness keeps the playoff game.
    return regular + [_game(6, 80.0, GAME_TYPE_PLAYOFFS)]


def _replay(logs: list[dict] | None = None, **kwargs):
    return replay_league(
        _Service({"Test Player": logs if logs is not None else _logs()}),
        kwargs.pop("league", "nba"),
        ["L10"],
        eval_start=datetime(2025, 11, 1),
        markets=[("player_points", "points")],
        threshold=0.65,
        min_games=10,
        do_agent=False,
        validate=kwargs.pop("validate", PRODUCTION_CHECK_ROWS),
        seed=kwargs.pop("seed", 7),
    )


def _guard_exit(validation: dict, league: str = "nba") -> tuple[int, GuardResult]:
    """Apply one league's validation the way the sample guard does, then exit."""
    result = GuardResult(ok=True, lines=["Calibration guard"])
    record_production_check(result, league, validation)
    return (0 if result.ok else 1), result


def test_widened_game_type_set_exits_nonzero(monkeypatch):
    """Keeping playoffs in history disagrees with get_player_stats."""
    from evaluation import walk_forward as wf

    monkeypatch.setattr(
        wf, "_history_types", lambda: CSVPlayerHistoryService._allowed_game_types(True, False)
    )
    replay = _replay()
    assert replay.validation["checked"] > 0
    assert replay.validation["mismatches"] > 0
    code, result = _guard_exit(replay.validation)
    assert code != 0
    monkeypatch.setattr("evaluation.backtest.run_sample_guard", lambda **kwargs: result)
    assert main(["--guard-only"]) != 0


def test_perturbed_probability_exits_nonzero(monkeypatch):
    """A rate that no longer matches get_player_stats fails the process."""
    from evaluation import walk_forward as wf

    real_rates = wf.empirical_rates

    def bumped(values, line):
        p_over, p_under, n_games = real_rates(values, line)
        return round(p_over + 0.01, 4), p_under, n_games

    monkeypatch.setattr(wf, "empirical_rates", bumped)
    replay = _replay()
    assert replay.validation["mismatches"] > 0
    code, result = _guard_exit(replay.validation)
    assert code != 0
    monkeypatch.setattr("evaluation.backtest.run_sample_guard", lambda **kwargs: result)
    assert main(["--guard-only"]) != 0


def test_missing_prior_row_exits_nonzero(monkeypatch):
    """Production seeing one fewer prior game than the replay is a mismatch."""
    real_stats = CSVPlayerHistoryService.get_player_stats

    def drop_one(self, *args, **kwargs):
        player = self._all_players[0]
        games = self._cache.get(player) or []
        if games:
            self._cache[player] = games[:-1]
        return real_stats(self, *args, **kwargs)

    monkeypatch.setattr(CSVPlayerHistoryService, "get_player_stats", drop_one)
    replay = _replay()
    assert replay.validation["checked"] > 0
    assert replay.validation["mismatches"] == replay.validation["checked"]
    code, result = _guard_exit(replay.validation)
    assert code != 0
    monkeypatch.setattr("evaluation.backtest.run_sample_guard", lambda **kwargs: result)
    assert main(["--guard-only"]) != 0


def test_extra_prior_row_exits_nonzero(monkeypatch):
    """Production seeing one extra prior game is a mismatch too."""
    real_stats = CSVPlayerHistoryService.get_player_stats

    def add_one(self, *args, **kwargs):
        player = self._all_players[0]
        games = list(self._cache.get(player) or [])
        if games:
            extra = dict(games[0])
            extra["points"] = 100.0
            extra["game_date"] = datetime(2020, 1, 1)
            extra["game_type"] = GAME_TYPE_REGULAR
            self._cache[player] = [extra, *games]
        return real_stats(self, *args, **kwargs)

    monkeypatch.setattr(CSVPlayerHistoryService, "get_player_stats", add_one)
    replay = _replay()
    assert replay.validation["mismatches"] > 0
    code, result = _guard_exit(replay.validation)
    assert code != 0
    monkeypatch.setattr("evaluation.backtest.run_sample_guard", lambda **kwargs: result)
    assert main(["--guard-only"]) != 0


def test_validation_rows_are_stable_for_a_seed_and_cover_the_cap(monkeypatch):
    """The 25-row draw is seed-stable. It is a reservoir, not a fresh shuffle."""
    from evaluation import walk_forward as wf

    captured: list[list[tuple]] = []
    real_validate = wf._validate

    def grab(league, cases):
        captured.append(
            [
                (case.player, case.metric, case.line, case.p_over, case.p_under, case.n_games)
                for case in cases
            ]
        )
        return real_validate(league, cases)

    monkeypatch.setattr(wf, "_validate", grab)
    cache = {}
    for index in range(4):
        name = f"Player {index:02d}"
        cache[name] = [
            _game(day, 10.0 + (day % 3), GAME_TYPE_REGULAR, player=name) for day in range(30)
        ]

    def once(seed: int) -> list[tuple]:
        captured.clear()
        replay_league(
            _Service(cache),
            "nba",
            ["L10"],
            eval_start=datetime(2025, 11, 1),
            markets=[("player_points", "points")],
            threshold=0.65,
            min_games=10,
            do_agent=False,
            validate=PRODUCTION_CHECK_ROWS,
            seed=seed,
        )
        return list(captured[0])

    first = once(7)
    second = once(7)
    other = once(11)
    assert len(first) == PRODUCTION_CHECK_ROWS
    assert first == second
    assert first != other
    assert PRODUCTION_CHECK_ROWS == 25


def test_player_sample_is_sorted_before_the_seeded_draw():
    names = ["m", "a", "z", "b"]
    assert select_players(names, 2, 7) == select_players(list(reversed(names)), 2, 7)
    assert select_players(names, 2, 7) == set(random.Random(7).sample(sorted(names), 2))


def test_zero_rows_in_one_league_fails_even_when_the_other_matches(monkeypatch):
    """A league that compared nothing must not ride the other league's pass."""
    seen: list[str] = []

    def fake_replay(service, league, proxies, **kwargs):
        seen.append(league)
        assert kwargs["validate"] == PRODUCTION_CHECK_ROWS
        assert kwargs["seed"] == 7
        replay = LeagueReplay(league=league)
        replay.daily = [_MedRow(0.60, 1 if index % 2 == 0 else 0) for index in range(40)]
        if league == "wnba":
            replay.validation = {"checked": 0, "mismatches": 0}
        else:
            replay.validation = {"checked": PRODUCTION_CHECK_ROWS, "mismatches": 0}
        return replay

    class _History:
        def _csv_for(self, league: str):
            return _Service({"Player": []}, league)

    monkeypatch.setattr("evaluation.walk_forward.load_historical", lambda: _History())
    monkeypatch.setattr("evaluation.walk_forward.replay_league", fake_replay)
    result = run_sample_guard(players=1, seed=7)
    assert seen == ["nba", "wnba"]
    assert result.ok is False
    assert "wnba production rate check sampled 0 rows" in result.failures
    assert any(
        "nba" in line and f"matched on {PRODUCTION_CHECK_ROWS}" in line
        for line in result.lines
    )
    monkeypatch.setattr("evaluation.backtest.run_sample_guard", lambda **kwargs: result)
    assert main(["--guard-only"]) != 0


def test_guard_only_exits_zero_when_the_sample_matches(monkeypatch):
    monkeypatch.setattr(
        "evaluation.backtest.run_sample_guard",
        lambda **kwargs: GuardResult(ok=True, lines=["ok"]),
    )
    assert main(["--guard-only"]) == 0


def test_blank_and_missing_game_type_follow_production_coalesce():
    """Blank and missing labels use ``_game_type_of``, not a second rule."""
    from evaluation.walk_forward import _game_type

    for raw in ("", None):
        game = {"game_type": raw}
        assert _game_type(game) == CSVPlayerHistoryService._game_type_of(game) == GAME_TYPE_REGULAR
    assert _game_type({}) == GAME_TYPE_REGULAR


def test_blank_csv_game_type_is_scored_as_regular_season(tmp_path, monkeypatch):
    """A shipped row with an empty GameType cell still counts as regular season."""
    with _NBA_CSV.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        template = next(
            row
            for row in reader
            if row.get("GameType") == GAME_TYPE_REGULAR and row.get("MIN") not in {"", "0", "0:00"}
        )
    rows = []
    for offset in range(12):
        row = dict(template)
        row["Player"] = "Blank Type"
        row["GameType"] = ""
        row["Date"] = f"{offset + 1}/11/2025"
        row["PTS"] = "10"
        rows.append(row)
    path = tmp_path / "nba_player_game_logs.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr("app.services.csv_player_history.CSV_PATH", str(path))
    service = CSVPlayerHistoryService(league="nba")
    service.load_csv()
    loaded = service._cache["Blank Type"]
    assert loaded
    assert {game["game_type"] for game in loaded} == {GAME_TYPE_REGULAR}
    replay = replay_league(
        service,
        "nba",
        ["L10"],
        eval_start=datetime(2025, 1, 1),
        markets=[("player_points", "points")],
        threshold=0.65,
        min_games=10,
        do_agent=False,
        validate=0,
    )
    assert replay.daily
    assert {row.game_type for row in replay.daily} == {GAME_TYPE_REGULAR}
    assert replay.postseason_daily == []


def test_wnba_excludes_the_same_tokens_as_nba():
    """Cup, playoffs, and the play-in follow the shared production set in both leagues."""
    from evaluation.walk_forward import _breakdown_types, _history_types

    assert _history_types() == CSVPlayerHistoryService._allowed_game_types()
    assert _breakdown_types() == {GAME_TYPE_PLAYOFFS, GAME_TYPE_PLAY_IN}
    for token in (
        GAME_TYPE_CUP,
        GAME_TYPE_PRESEASON,
        GAME_TYPE_SUMMER,
        GAME_TYPE_GLEAGUE,
        GAME_TYPE_UNCLASSIFIED,
        "all_star",
    ):
        assert token not in _history_types()
        assert token not in _breakdown_types()

    logs = [
        *[_game(offset, 10.0, GAME_TYPE_REGULAR) for offset in range(12)],
        _game(20, 99.0, GAME_TYPE_CUP),
        _game(30, 40.0, GAME_TYPE_PLAY_IN),
        _game(40, 80.0, GAME_TYPE_PLAYOFFS),
    ]
    replay = replay_league(
        _Service({"Test Player": logs}, league="wnba"),
        "wnba",
        ["L10"],
        eval_start=datetime(2025, 11, 1),
        markets=[("player_points", "points")],
        threshold=0.65,
        min_games=10,
        do_agent=False,
        validate=0,
    )
    headline = {row.date for row in replay.daily}
    postseason = {row.game_type for row in replay.postseason_daily}
    cup_date = logs[-3]["game_date"].strftime("%Y-%m-%d")
    assert cup_date not in headline
    assert postseason == {GAME_TYPE_PLAY_IN, GAME_TYPE_PLAYOFFS}
    assert all(row.game_type == GAME_TYPE_REGULAR for row in replay.daily)


def test_eval_modules_do_not_keep_a_second_game_type_list():
    """walk_forward, backtest, report, and oracle call production; they do not list tokens."""
    import evaluation.backtest as backtest
    import evaluation.oracle as oracle
    import evaluation.report as report
    import evaluation.walk_forward as walk_forward

    banned = {
        GAME_TYPE_REGULAR,
        GAME_TYPE_PLAYOFFS,
        GAME_TYPE_PLAY_IN,
        GAME_TYPE_CUP,
        GAME_TYPE_PRESEASON,
        "all_star",
    }
    for module in (walk_forward, backtest, report, oracle):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Set, ast.List, ast.Tuple)):
                continue
            values = [
                element.value
                for element in node.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            ]
            assert banned.isdisjoint(values), (module.__name__, values)
