import os
import sys

from fastapi.testclient import TestClient


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.services import lineup_source_support as source_support
from app.services.lineup_provider_rotogrinders import parse_rotogrinders_html
from app.services.lineup_provider_rotowire import parse_rotowire_html
from app.services.lineup_service import LineupReadResult, build_consensus_lineups


ROTOWIRE_HTML = """
<html>
  <body>
    <div>Warriors</div>
    <div>Lakers</div>
    <div>Confirmed Lineup</div>
    <div>PG</div><div>Stephen Curry</div>
    <div>SG</div><div>B. Hield</div>
    <div>SF</div><div>Jimmy Butler III</div>
    <div>PF</div><div>D. Green Prob</div>
    <div>C</div><div>Q. Post Ques</div>
    <div>Expected Lineup</div>
    <div>PG</div><div>Luka Doncic</div>
    <div>SG</div><div>Austin Reaves</div>
    <div>SF</div><div>LeBron James Prob</div>
    <div>PF</div><div>Rui Hachimura</div>
    <div>C</div><div>J. Hayes</div>
  </body>
</html>
"""


ROTOGRINDERS_HTML = """
<html>
  <body>
    <div>10:00 PM ET</div>
    <div>Golden State Warriors</div>
    <div>Los Angeles Lakers</div>
    <div>Starters</div>
    <div>Stephen Curry PG $10.2K 36.4 18.2%</div>
    <div>Buddy Hield SG $5.4K 24.1 11%</div>
    <div>Jimmy Butler III SF $8.2K 40.3 21%</div>
    <div>Draymond Green PF $6.1K 30.5 12%</div>
    <div>Quinten Post C $4.5K 16.1 5%</div>
    <div>Bench</div>
    <div>Brandin Podziemski SG $5.7K 26.1 9%</div>
    <div>Starters</div>
    <div>Luka Doncic PG $12.1K 58.7 31%</div>
    <div>Austin Reaves SG $8.4K 41.1 19%</div>
    <div>LeBron James SF $10.8K 53.2 24%</div>
    <div>Rui Hachimura PF $6.2K 27.4 10%</div>
    <div>Jaxson Hayes C $4.1K 19.2 7%</div>
    <div>Bench</div>
    <div>Dalton Knecht SF $3.6K 14.1 4%</div>
  </body>
</html>
"""


ROTOWIRE_REGRESSION_HTML = """
<html>
  <body>
    <div>POR</div>
    <div>BKN</div>
    <div>Trail Blazers</div>
    <div>Nets</div>
    <div>Expected Lineup</div>
    <div>PG</div><div>Jrue Holiday</div>
    <div>SG</div><div>Toumani Camara</div>
    <div>SF</div><div>Deni Avdija</div>
    <div>PF</div><div>Jerami Grant</div>
    <div>C</div><div>Donovan Clingan</div>
    <div>Projected Minutes</div>
    <div>Expected Lineup</div>
    <div>PG</div><div>Nolan Traore</div>
    <div>SG</div><div>Drake Powell</div>
    <div>SF</div><div>Ziaire Williams</div>
    <div>PF</div><div>Danny Wolf</div>
    <div>C</div><div>Nic Claxton</div>
    <div>MEM</div>
    <div>CHI</div>
    <div>Grizzlies</div>
    <div>Bulls</div>
    <div>Expected Lineup</div>
    <div>PG</div><div>Javon Small</div>
    <div>SG</div><div>Cedric Coward</div>
    <div>SF</div><div>Jaylen Wells</div>
    <div>PF</div><div>Taylor Hendricks</div>
    <div>C</div><div>Olivier-Maxence Prosper</div>
    <div>Projected Minutes</div>
    <div>Expected Lineup</div>
    <div>PG</div><div>Josh Giddey</div>
    <div>SG</div><div>Tre Jones</div>
    <div>SF</div><div>Matas Buzelis</div>
    <div>PF</div><div>Leonard Miller</div>
    <div>C</div><div>Jalen Smith</div>
    <div>PHX</div>
    <div>BOS</div>
    <div>Suns</div>
    <div>Celtics</div>
    <div>Expected Lineup</div>
    <div>PG</div><div>Collin Gillespie</div>
    <div>SG</div><div>Devin Booker</div>
    <div>SF</div><div>Jalen Green</div>
    <div>PF</div><div>Royce O'Neale</div>
    <div>C</div><div>Oso Ighodaro</div>
    <div>Projected Minutes</div>
    <div>Expected Lineup</div>
    <div>PG</div><div>Derrick White</div>
    <div>SG</div><div>Jaylen Brown</div>
    <div>SF</div><div>Sam Hauser</div>
    <div>PF</div><div>Jayson Tatum</div>
    <div>C</div><div>Neemias Queta</div>
    <div>DAL</div>
    <div>NOP</div>
    <div>Mavericks</div>
    <div>Pelicans</div>
    <div>Expected Lineup</div>
    <div>PG</div><div>Ryan Nembhard</div>
    <div>SG</div><div>Max Christie</div>
    <div>SF</div><div>Naji Marshall</div>
    <div>PF</div><div>Cooper Flagg</div>
    <div>C</div><div>PJ Washington</div>
    <div>Projected Minutes</div>
    <div>Expected Lineup</div>
    <div>PG</div><div>Dejounte Murray</div>
    <div>SG</div><div>Trey Murphy</div>
    <div>SF</div><div>Herbert Jones</div>
    <div>PF</div><div>Saddiq Bey</div>
    <div>C</div><div>Zion Williamson</div>
    <div>LAL</div>
    <div>HOU</div>
    <div>Lakers</div>
    <div>Rockets</div>
    <div>Expected Lineup</div>
    <div>PG</div><div>Luka Doncic</div>
    <div>SG</div><div>Austin Reaves</div>
    <div>SF</div><div>Marcus Smart</div>
    <div>PF</div><div>LeBron James</div>
    <div>C</div><div>Deandre Ayton</div>
    <div>Projected Minutes</div>
    <div>Expected Lineup</div>
    <div>PG</div><div>Amen Thompson</div>
    <div>SG</div><div>Tari Eason</div>
    <div>SF</div><div>Kevin Durant</div>
    <div>PF</div><div>Jabari Smith</div>
    <div>C</div><div>Alperen Sengun</div>
    <div>SAS</div>
    <div>LAC</div>
    <div>Spurs</div>
    <div>Clippers</div>
    <div>Expected Lineup</div>
    <div>PG</div><div>De'Aaron Fox</div>
    <div>SG</div><div>Stephon Castle</div>
    <div>SF</div><div>Devin Vassell</div>
    <div>PF</div><div>Julian Champagnie</div>
    <div>C</div><div>Victor Wembanyama</div>
    <div>Projected Minutes</div>
    <div>Expected Lineup</div>
    <div>PG</div><div>Darius Garland</div>
    <div>SG</div><div>Kris Dunn</div>
    <div>SF</div><div>Derrick Jones Jr.</div>
    <div>PF</div><div>John Collins</div>
    <div>C</div><div>Brook Lopez</div>
  </body>
</html>
"""


ROTOGRINDERS_REGRESSION_HTML = """
<html>
  <body>
    <div>Admin</div>
    <div>Edit</div>
    <div>7:30 PM ET</div>
    <div>Portland</div>
    <div>Trail Blazers</div>
    <div>Brooklyn</div>
    <div>Nets</div>
    <div>lineup not released</div>
    <div>Starters</div>
    <div>Jrue Holiday PG $7.4K 34.7 13%</div>
    <div>Toumani Camara SG/SF $6K 25.9 1%</div>
    <div>Deni Avdija SF/PF $8.8K 42.5 15%</div>
    <div>Jerami Grant PF $6.5K 30.1 5%</div>
    <div>Donovan Clingan C $7.8K 40.3 17%</div>
    <div>Bench</div>
    <div>Admin</div>
    <div>Edit</div>
    <div>8:00 PM ET</div>
    <div>Memphis</div>
    <div>Grizzlies</div>
    <div>Chicago</div>
    <div>Bulls</div>
    <div>lineup not released</div>
    <div>Starters</div>
    <div>Javon Small PG $6K 28.8 8%</div>
    <div>Cedric Coward SG $5.1K 26.5 26%</div>
    <div>Jaylen Wells SF $5.8K 31 17%</div>
    <div>Taylor Hendricks PF $4.9K 24.5 12%</div>
    <div>Olivier-Maxence Prosper C $4.1K 19.3 9%</div>
    <div>Bench</div>
    <div>Starters</div>
    <div>Josh Giddey PG $9K 49 35%</div>
    <div>Tre Jones PG/SG $5.8K 29.1 15%</div>
    <div>Matas Buzelis PF $7.7K 37 12%</div>
    <div>Leonard Miller SF/PF $4.3K 22.7 18%</div>
    <div>Jalen Smith C $5.2K 28.5 29%</div>
    <div>Bench</div>
    <div>Admin</div>
    <div>Edit</div>
    <div>7:30 PM ET</div>
    <div>Phoenix</div>
    <div>Suns</div>
    <div>Boston</div>
    <div>Celtics</div>
    <div>lineup not released</div>
    <div>Starters</div>
    <div>Collin Gillespie PG $6.2K 24.8 0%</div>
    <div>Devin Booker PG/SG $9.2K 36.9 0%</div>
    <div>Jalen Green SG/SF $8.1K 34.2 1%</div>
    <div>Royce O'Neale PF $5.5K 27.4 0%</div>
    <div>Oso Ighodaro C $4.1K 18.2 0%</div>
    <div>Bench</div>
    <div>Starters</div>
    <div>Derrick White PG $7.8K 33.9 1%</div>
    <div>Jaylen Brown SG/SF $9.1K 40 6%</div>
    <div>Sam Hauser SF/PF $4.7K 18.9 0%</div>
    <div>Jayson Tatum PF $8.6K 41 17%</div>
    <div>Neemias Queta C $6.4K 26.2 0%</div>
    <div>Bench</div>
    <div>Admin</div>
    <div>Edit</div>
    <div>8:00 PM ET</div>
    <div>Dallas</div>
    <div>Mavericks</div>
    <div>New Orleans</div>
    <div>Pelicans</div>
    <div>lineup not released</div>
    <div>Starters</div>
    <div>Ryan Nembhard PG $3.4K 18.4 16%</div>
    <div>Max Christie SG $4.6K 20.3 1%</div>
    <div>Cooper Flagg PG $8.7K 43 22%</div>
    <div>Naji Marshall SG/SF $5.9K 28 12%</div>
    <div>PJ Washington PF $5.8K 26.7 3%</div>
    <div>Bench</div>
    <div>Admin</div>
    <div>Edit</div>
    <div>9:30 PM ET</div>
    <div>Los Angeles</div>
    <div>Lakers</div>
    <div>Houston</div>
    <div>Rockets</div>
    <div>lineup not released</div>
    <div>Starters</div>
    <div>Luka Doncic PG $12.2K 57.7</div>
    <div>Austin Reaves PG/SG $8.2K 36.6</div>
    <div>Marcus Smart SG/SF $4.9K 19.1</div>
    <div>LeBron James PF $7.9K 37.6</div>
    <div>Deandre Ayton C $5.2K 23.2</div>
    <div>Bench</div>
    <div>Admin</div>
    <div>Edit</div>
    <div>10:00 PM ET</div>
    <div>San Antonio</div>
    <div>Spurs</div>
    <div>Los Angeles</div>
    <div>Clippers</div>
    <div>lineup not released</div>
    <div>Starters</div>
    <div>De'Aaron Fox PG $7.5K 34.8</div>
    <div>Stephon Castle SG $7.7K 37.8</div>
    <div>Devin Vassell SF $5.1K 26.4</div>
    <div>Julian Champagnie SF/PF $4.8K 23.9</div>
    <div>Victor Wembanyama C $11K 53.7</div>
    <div>Bench</div>
  </body>
</html>
"""


def _sample_lineup(
    *,
    team: str = "GSW",
    opponent: str = "LAL",
    starters: list[str] | None = None,
    confidence: str = "high",
    status: str = "projected",
    updated_at: str = "2026-03-16T17:40:00+00:00",
    source_disagreement: bool = False,
    source_snapshots: dict | None = None,
):
    return {
        "date": "2026-03-16",
        "team": team,
        "opponent": opponent,
        "home_or_away": "AWAY",
        "status": status,
        "starters": starters
        or ["Stephen Curry", "Buddy Hield", "Jimmy Butler III", "Draymond Green", "Quinten Post"],
        "bench_candidates": ["Brandin Podziemski"],
        "sources": ["rotowire", "rotogrinders"],
        "source_disagreement": source_disagreement,
        "confidence": confidence,
        "updated_at": updated_at,
        "source_snapshots": source_snapshots
        or {
            "rotowire": {"team": team, "status": "confirmed"},
            "rotogrinders": {"team": team, "status": "projected"},
        },
    }


def test_rotowire_parser_normalizes_status_suffixes_and_resolves_team_abbreviations(monkeypatch):
    monkeypatch.setattr(
        source_support,
        "_get_team_roster_candidates",
        lambda team_code: {
            "GSW": [
                "Stephen Curry",
                "Buddy Hield",
                "Jimmy Butler III",
                "Draymond Green",
                "Quinten Post",
            ],
            "LAL": [
                "Luka Doncic",
                "Austin Reaves",
                "LeBron James",
                "Rui Hachimura",
                "Jaxson Hayes",
            ],
        }.get(team_code, []),
    )

    parsed = parse_rotowire_html(ROTOWIRE_HTML, date="2026-03-16")

    gsw = parsed["GSW"]
    gsw_snapshot = gsw["source_snapshots"]["rotowire"]
    assert gsw["starters"] == [
        "Stephen Curry",
        "Buddy Hield",
        "Jimmy Butler III",
        "Draymond Green",
        "Quinten Post",
    ]
    assert gsw_snapshot["raw_starters"] == [
        "Stephen Curry",
        "B. Hield",
        "Jimmy Butler III",
        "D. Green Prob",
        "Q. Post Ques",
    ]
    assert gsw_snapshot["canonical_starters"] == [
        "Stephen Curry",
        "Buddy Hield",
        "Jimmy Butler III",
        "Draymond Green",
        "Quinten Post",
    ]
    assert gsw_snapshot["unresolved_starters"] == []


def test_rotogrinders_parser_strips_dfs_metadata_and_bench_noise(monkeypatch):
    monkeypatch.setattr(
        source_support,
        "_get_team_roster_candidates",
        lambda team_code: {
            "GSW": [
                "Stephen Curry",
                "Buddy Hield",
                "Jimmy Butler III",
                "Draymond Green",
                "Quinten Post",
                "Brandin Podziemski",
            ],
            "LAL": [
                "Luka Doncic",
                "Austin Reaves",
                "LeBron James",
                "Rui Hachimura",
                "Jaxson Hayes",
                "Dalton Knecht",
            ],
        }.get(team_code, []),
    )

    parsed = parse_rotogrinders_html(ROTOGRINDERS_HTML, date="2026-03-16")

    gsw = parsed["GSW"]
    gsw_snapshot = gsw["source_snapshots"]["rotogrinders"]
    assert gsw["starters"] == [
        "Stephen Curry",
        "Buddy Hield",
        "Jimmy Butler III",
        "Draymond Green",
        "Quinten Post",
    ]
    assert gsw["bench_candidates"] == ["Brandin Podziemski"]
    assert gsw_snapshot["raw_starters"][1] == "Buddy Hield SG $5.4K 24.1 11%"
    assert gsw_snapshot["canonical_starters"][1] == "Buddy Hield"
    assert gsw_snapshot["unresolved_starters"] == []


def test_resolver_keeps_ambiguous_initials_unresolved(monkeypatch):
    monkeypatch.setattr(
        source_support,
        "_get_team_roster_candidates",
        lambda team_code: ["Jalen Williams", "Jaylin Williams"] if team_code == "OKC" else [],
    )

    result = source_support.resolve_canonical_player_name("J. Williams", "OKC")

    assert result["canonical_name"] is None
    assert result["resolution_status"] == "unresolved"
    assert result["resolution_reason"] == "ambiguous_team_match"


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


def test_clean_player_name_keeps_names_that_embed_team_aliases():
    assert source_support.clean_player_name("Deni Avdija") == "Deni Avdija"
    assert source_support.clean_player_name("Leonard Miller") == "Leonard Miller"
    assert source_support.clean_player_name("Neemias Queta") == "Neemias Queta"
    assert source_support.clean_player_name("PJ Washington") == "PJ Washington"
    assert source_support.clean_player_name("Julian Champagnie") == "Julian Champagnie"


def test_build_consensus_lineups_aligns_canonicalized_starters_without_false_disagreement():
    primary = {
        "GSW": _sample_lineup(
            source_snapshots={
                "rotowire": {
                    "team": "GSW",
                    "status": "confirmed",
                    "raw_starters": ["Stephen Curry", "B. Hield", "Jimmy Butler III", "D. Green Prob", "Q. Post Ques"],
                    "canonical_starters": ["Stephen Curry", "Buddy Hield", "Jimmy Butler III", "Draymond Green", "Quinten Post"],
                    "unresolved_starters": [],
                    "normalization_warnings": [],
                }
            },
        ),
    }
    secondary = {
        "GSW": _sample_lineup(
            starters=["Stephen Curry", "Buddy Hield", "Jimmy Butler III", "Draymond Green", "Quinten Post"],
            source_snapshots={
                "rotogrinders": {
                    "team": "GSW",
                    "status": "projected",
                    "raw_starters": ["Stephen Curry PG $10.2K", "Buddy Hield SG $5.4K", "Jimmy Butler III SF $8.2K", "Draymond Green PF $6.1K", "Quinten Post C $4.5K"],
                    "canonical_starters": ["Stephen Curry", "Buddy Hield", "Jimmy Butler III", "Draymond Green", "Quinten Post"],
                    "unresolved_starters": [],
                    "normalization_warnings": [],
                }
            },
        ),
    }

    consensus = build_consensus_lineups(
        date="2026-03-16",
        primary_source=primary,
        secondary_source=secondary,
    )

    assert consensus["GSW"]["status"] == "projected"
    assert consensus["GSW"]["confidence"] == "high"
    assert consensus["GSW"]["source_disagreement"] is False


def test_rotowire_parser_regression_keeps_correct_team_keys_and_full_starting_fives():
    parsed = parse_rotowire_html(ROTOWIRE_REGRESSION_HTML, date="2026-03-16")

    assert parsed["POR"]["starters"] == [
        "Jrue Holiday",
        "Toumani Camara",
        "Deni Avdija",
        "Jerami Grant",
        "Donovan Clingan",
    ]
    assert parsed["CHI"]["starters"] == [
        "Josh Giddey",
        "Tre Jones",
        "Matas Buzelis",
        "Leonard Miller",
        "Jalen Smith",
    ]
    assert parsed["BOS"]["starters"][-1] == "Neemias Queta"
    assert parsed["DAL"]["starters"][-1] == "P.J. Washington"
    assert parsed["LAL"]["starters"] == [
        "Luka Doncic",
        "Austin Reaves",
        "Marcus Smart",
        "LeBron James",
        "Deandre Ayton",
    ]
    assert parsed["SAS"]["starters"] == [
        "De'Aaron Fox",
        "Stephon Castle",
        "Devin Vassell",
        "Julian Champagnie",
        "Victor Wembanyama",
    ]


def test_rotogrinders_parser_regression_keeps_correct_team_keys_and_full_starting_fives():
    parsed = parse_rotogrinders_html(ROTOGRINDERS_REGRESSION_HTML, date="2026-03-16")

    assert parsed["POR"]["starters"] == [
        "Jrue Holiday",
        "Toumani Camara",
        "Deni Avdija",
        "Jerami Grant",
        "Donovan Clingan",
    ]
    assert parsed["CHI"]["starters"] == [
        "Josh Giddey",
        "Tre Jones",
        "Matas Buzelis",
        "Leonard Miller",
        "Jalen Smith",
    ]
    assert parsed["BOS"]["starters"][-1] == "Neemias Queta"
    assert parsed["DAL"]["starters"][-1] == "P.J. Washington"
    assert parsed["LAL"]["starters"] == [
        "Luka Doncic",
        "Austin Reaves",
        "Marcus Smart",
        "LeBron James",
        "Deandre Ayton",
    ]
    assert parsed["SAS"]["starters"] == [
        "De'Aaron Fox",
        "Stephon Castle",
        "Devin Vassell",
        "Julian Champagnie",
        "Victor Wembanyama",
    ]


def test_build_consensus_lineups_degrades_to_partial_when_any_source_is_unresolved():
    primary = {
        "OKC": _sample_lineup(
            team="OKC",
            opponent="BOS",
            starters=["Shai Gilgeous-Alexander", "Luguentz Dort", "J. Williams", "Chet Holmgren", "Isaiah Hartenstein"],
            source_snapshots={
                "rotowire": {
                    "team": "OKC",
                    "status": "expected",
                    "raw_starters": ["Shai Gilgeous-Alexander", "Luguentz Dort", "J. Williams Prob", "Chet Holmgren", "Isaiah Hartenstein"],
                    "canonical_starters": ["Shai Gilgeous-Alexander", "Luguentz Dort", "Chet Holmgren", "Isaiah Hartenstein"],
                    "unresolved_starters": ["J. Williams"],
                    "normalization_warnings": ["unresolved: J. Williams"],
                }
            },
            confidence="low",
            status="partial",
        ),
    }
    secondary = {
        "OKC": _sample_lineup(
            team="OKC",
            opponent="BOS",
            starters=["Shai Gilgeous-Alexander", "Luguentz Dort", "Jalen Williams", "Chet Holmgren", "Isaiah Hartenstein"],
            source_snapshots={
                "rotogrinders": {
                    "team": "OKC",
                    "status": "projected",
                    "raw_starters": ["Shai Gilgeous-Alexander", "Luguentz Dort", "Jalen Williams", "Chet Holmgren", "Isaiah Hartenstein"],
                    "canonical_starters": ["Shai Gilgeous-Alexander", "Luguentz Dort", "Jalen Williams", "Chet Holmgren", "Isaiah Hartenstein"],
                    "unresolved_starters": [],
                    "normalization_warnings": [],
                }
            },
            confidence="high",
        ),
    }

    consensus = build_consensus_lineups(
        date="2026-03-16",
        primary_source=primary,
        secondary_source=secondary,
    )

    assert consensus["OKC"]["status"] == "partial"
    assert consensus["OKC"]["confidence"] == "low"
    assert consensus["OKC"]["source_disagreement"] is False
    assert "J. Williams" in consensus["OKC"]["starters"]


def test_build_consensus_lineups_regression_keeps_expected_metadata_and_lakers_present():
    primary = parse_rotowire_html(ROTOWIRE_REGRESSION_HTML, date="2026-03-16")
    secondary = parse_rotogrinders_html(ROTOGRINDERS_REGRESSION_HTML, date="2026-03-16")

    consensus = build_consensus_lineups(
        date="2026-03-16",
        primary_source=primary,
        secondary_source=secondary,
    )

    assert consensus["LAL"]["team"] == "LAL"
    assert consensus["LAL"]["status"] == "projected"
    assert consensus["CHI"]["opponent"] == "MEM"
    assert consensus["CHI"]["home_or_away"] == "HOME"
    assert consensus["BOS"]["opponent"] == "PHX"
    assert consensus["BOS"]["home_or_away"] == "HOME"
    assert consensus["DAL"]["opponent"] == "NOP"
    assert consensus["DAL"]["home_or_away"] == "AWAY"


def test_lineups_api_returns_team_count(monkeypatch):
    from app.api import lineups as lineups_api

    async def fake_get_lineups(_date: str):
        return LineupReadResult(
            date="2026-03-16",
            lineups={"GSW": _sample_lineup()},
            fetched_at="2026-03-16T17:40:00+00:00",
            cache_state="fresh",
        )

    monkeypatch.setattr(lineups_api.lineup_service, "get_lineups", fake_get_lineups)

    client = TestClient(app)
    response = client.get("/api/nba/lineups?date=2026-03-16")

    assert response.status_code == 200
    payload = response.json()
    assert payload["team_count"] == 1
    assert payload["cache_state"] == "fresh"
    assert payload["lineups"][0]["team"] == "GSW"
