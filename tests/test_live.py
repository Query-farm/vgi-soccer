"""Opt-in smoke tests against the real upstream sources (``uv run pytest -m live``).

They pin historical facts that cannot change: the 2015-16 Premier League table,
a finished 2026 match, the 2022 World Cup final, and a completed Bundesliga season.
"""

from __future__ import annotations

import pytest

from vgi_soccer import api
from vgi_soccer.detail_schemas import (
    flatten_key_events,
    flatten_player_match_stats,
    flatten_plays,
    flatten_summary,
    flatten_team_stats,
)
from vgi_soccer.league_schemas import flatten_leagues, flatten_standings
from vgi_soccer.match_schemas import flatten_events
from vgi_soccer.open_schemas import (
    flatten_bundesliga_matches,
    flatten_bundesliga_table,
    flatten_world_cup_goals,
    flatten_world_cup_matches,
)
from vgi_soccer.team_schemas import flatten_leaders, flatten_player_stats, flatten_roster, flatten_teams

pytestmark = pytest.mark.live
EVENT = 401879240


@pytest.fixture(autouse=True)
def _polite(monkeypatch: pytest.MonkeyPatch) -> None:
    # Live tests keep the production politeness interval.
    monkeypatch.delenv("SOCCER_MIN_REQUEST_INTERVAL", raising=False)


def test_league_directory() -> None:
    rows = flatten_leagues(api.fetch_leagues().payload)
    assert len(rows) >= 150
    assert {"eng.1", "esp.1", "uefa.champions", "fifa.world"} <= {row["league_slug"] for row in rows}


def test_2015_premier_league_table() -> None:
    rows = flatten_standings(api.fetch_standings("eng.1", 2015).payload, "eng.1")
    assert len(rows) == 20
    assert (rows[0]["team_name"], rows[0]["points"]) == ("Leicester City", 81)
    assert sum(row["points"] for row in rows) == 1_033


def test_current_big_five_tables_have_teams() -> None:
    for league in ("eng.1", "esp.1", "ger.1", "ita.1", "fra.1"):
        rows = flatten_standings(api.fetch_standings(league).payload, league)
        assert len(rows) in (18, 20), league


def test_group_tournament_and_cup() -> None:
    world = flatten_standings(api.fetch_standings("fifa.world").payload, "fifa.world")
    assert len({row["group_name"] for row in world}) >= 8
    assert flatten_standings(api.fetch_standings("eng.fa").payload, "eng.fa") == []


def test_full_2025_premier_league_season() -> None:
    events = []
    for year in ("2025", "2026"):
        events += api.fetch_scoreboard("eng.1", year).payload["events"]
    rows = [row for row in flatten_events(events, league="eng.1") if row["season"] == 2025]
    assert len({row["event_id"] for row in rows}) == 380


def test_finished_match_detail() -> None:
    payload = api.fetch_summary(EVENT).payload
    (summary,) = flatten_summary(payload, EVENT)
    assert (summary["home_score"], summary["away_score"]) == (4, 4)
    assert len(flatten_team_stats(payload, EVENT)) == 2
    assert sum(row.get("goals") or 0 for row in flatten_player_match_stats(payload, EVENT)) == 8
    assert sum(1 for row in flatten_key_events(payload, EVENT) if row["scoring_play"]) == 8
    plays = flatten_plays(api.fetch_plays(EVENT).payload, EVENT)
    assert len(plays) > 1_000
    assert any(row["expected_goals"] for row in plays)


def test_teams_roster_leaders_and_player() -> None:
    assert len(flatten_teams(api.fetch_teams("eng.1").payload, "eng.1")) == 20
    assert len(flatten_roster(api.fetch_roster("eng.1", 360).payload, "eng.1", 360)) >= 18
    leaders = flatten_leaders(api.fetch_statistics("eng.1", 2015).payload, "eng.1", 2015)
    top = next(row for row in leaders if row["category"] == "goals")
    assert (top["player_name"], top["value"]) == ("Harry Kane", 25)
    lines = flatten_player_stats(api.fetch_athlete_stats(253989, "eng.1").payload, 253989)
    assert next(row for row in lines if row["season"] == 2022)["goals"] == 36


def test_world_cup_history() -> None:
    payload = api.fetch_world_cup(2022).payload
    matches = flatten_world_cup_matches(payload, 2022)
    assert len(matches) == 64
    assert all(row["team1_goals"] is not None and row["team2_goals"] is not None for row in matches)
    assert next(row for row in matches if row["round"] == "Final")["winner"] == "Argentina"
    assert len(flatten_world_cup_goals(payload, 2022)) == 172
    assert len(flatten_world_cup_matches(api.fetch_world_cup(1930).payload, 1930)) == 18
    # 1990 stores most results as bare [team1, team2] lists.
    italia = flatten_world_cup_matches(api.fetch_world_cup(1990).payload, 1990)
    assert all(row["team1_goals"] is not None for row in italia)
    final_scores = [
        (row["team1_extra_time"], row["team2_extra_time"])
        if row["team1_extra_time"] is not None
        else (row["team1_goals"], row["team2_goals"])
        for row in italia
    ]
    assert sum(home + away for home, away in final_scores) == 115  # Italia 90's famous low total


def test_openligadb_completed_season() -> None:
    table = flatten_bundesliga_table(api.fetch_openligadb_table("bl1", 2025).payload, "bl1", 2025)
    assert (table[0]["team_name"], table[0]["points"]) == ("FC Bayern München", 89)
    matches = flatten_bundesliga_matches(api.fetch_openligadb_matches("bl1", 2025, 10).payload, "bl1")
    assert len(matches) == 9
