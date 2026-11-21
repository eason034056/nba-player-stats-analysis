"""Team-code lookup still used by the roster cache."""

from app.services import lineup_source_support as source_support


def test_detect_team_code_matches_only_exact_team_labels():
    assert source_support.detect_team_code("POR") == "POR"
    assert source_support.detect_team_code("Trail Blazers") == "POR"
    assert source_support.detect_team_code("Lakers") == "LAL"
    assert source_support.detect_team_code("Celtics") == "BOS"
    assert source_support.detect_team_code("Pelicans") == "NOP"
    assert source_support.detect_team_code("Deni Avdija") is None
    assert source_support.detect_team_code("Leonard Miller") is None
    assert source_support.detect_team_code("Neemias Queta") is None
    assert source_support.detect_team_code("PJ Washington") is None
    assert source_support.detect_team_code("Julian Champagnie") is None
    assert source_support.detect_team_code("Admin") is None
    assert source_support.detect_team_code("Projected Minutes") is None
    assert source_support.detect_team_code("BOS -400") is None
