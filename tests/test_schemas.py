"""Parsing of recorded upstream responses into typed rows and Arrow batches."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pyarrow as pa
import pytest
from fixture_routes import load

from vgi_soccer.detail_schemas import (
    COMMENTARY_SCHEMA,
    KEY_EVENTS_SCHEMA,
    PLAYER_MATCH_SCHEMA,
    PLAYS_SCHEMA,
    SUMMARY_SCHEMA,
    TEAM_STATS_SCHEMA,
    flatten_commentary,
    flatten_key_events,
    flatten_player_match_stats,
    flatten_plays,
    flatten_summary,
    flatten_team_stats,
    summary_event_id,
)
from vgi_soccer.league_schemas import (
    LEAGUES_SCHEMA,
    STANDINGS_SCHEMA,
    flatten_leagues,
    flatten_standings,
    league_names,
)
from vgi_soccer.match_schemas import MATCH_SCHEMA, flatten_events, league_uid_id
from vgi_soccer.meta import batch_from_rows, comment_of
from vgi_soccer.open_schemas import (
    BUNDESLIGA_MATCHES_SCHEMA,
    BUNDESLIGA_TABLE_SCHEMA,
    WORLD_CUP_GOALS_SCHEMA,
    WORLD_CUP_MATCHES_SCHEMA,
    flatten_bundesliga_matches,
    flatten_bundesliga_table,
    flatten_world_cup_goals,
    flatten_world_cup_matches,
)
from vgi_soccer.team_schemas import (
    LEADERS_SCHEMA,
    PLAYER_STATS_SCHEMA,
    ROSTER_SCHEMA,
    TEAMS_SCHEMA,
    flatten_leaders,
    flatten_player_stats,
    flatten_roster,
    flatten_teams,
)

EVENT = 401879240

ALL_SCHEMAS = [
    LEAGUES_SCHEMA,
    STANDINGS_SCHEMA,
    MATCH_SCHEMA,
    TEAMS_SCHEMA,
    ROSTER_SCHEMA,
    LEADERS_SCHEMA,
    PLAYER_STATS_SCHEMA,
    SUMMARY_SCHEMA,
    TEAM_STATS_SCHEMA,
    PLAYER_MATCH_SCHEMA,
    KEY_EVENTS_SCHEMA,
    COMMENTARY_SCHEMA,
    PLAYS_SCHEMA,
    WORLD_CUP_MATCHES_SCHEMA,
    WORLD_CUP_GOALS_SCHEMA,
    BUNDESLIGA_TABLE_SCHEMA,
    BUNDESLIGA_MATCHES_SCHEMA,
]


@pytest.mark.parametrize("schema", ALL_SCHEMAS)
def test_every_column_is_documented_and_unique(schema: pa.Schema) -> None:
    assert len(set(schema.names)) == len(schema.names)
    for column in schema:
        assert comment_of(column).endswith("."), column.name


def test_2015_premier_league_table_is_leicester_with_81_points() -> None:
    rows = flatten_standings(load("espn_standings_eng1_2015.json"), "eng.1")
    assert len(rows) == 20
    champion = rows[0]
    assert champion["team_name"] == "Leicester City"
    assert (champion["rank"], champion["points"], champion["wins"], champion["draws"]) == (1, 81, 23, 12)
    assert champion["losses"] == 3
    assert champion["goal_difference"] == champion["goals_for"] - champion["goals_against"]
    assert champion["season"] == 2015
    assert champion["record"] == "23-12-3"
    assert {row["rank"] for row in rows} == set(range(1, 21))
    # Every match has a winner and a loser or two drawers.
    assert sum(row["wins"] for row in rows) == sum(row["losses"] for row in rows)
    assert sum(row["games_played"] for row in rows) == 20 * 38
    batch = batch_from_rows(rows, STANDINGS_SCHEMA)
    assert batch.num_rows == 20


def test_group_tournament_tables_keep_their_group() -> None:
    rows = flatten_standings(load("espn_standings_fifa_world.json"), "fifa.world")
    assert {row["group_name"] for row in rows} == {"Group A", "Group B"}
    assert len(rows) == 8


def test_cup_without_a_table_yields_no_rows() -> None:
    assert flatten_standings(load("espn_standings_eng_fa.json"), "eng.fa") == []
    assert flatten_standings({"standings": {"entries": [{"team": {}}]}}, "x.1") == []


def test_league_directory_and_id_lookup() -> None:
    payload = load("espn_leagues.json")
    rows = flatten_leagues({"leagues": [*payload["leagues"], payload["leagues"][0]]})
    slugs = {row["league_slug"] for row in rows}
    assert {"eng.1", "uefa.champions", "fifa.world"} <= slugs
    assert len(rows) == len(slugs)
    lookup = league_names(payload)
    assert lookup[700] == ("eng.1", "English Premier League")
    batch_from_rows(rows, LEAGUES_SCHEMA)


def test_scoreboard_events_flatten_with_winner_and_venue() -> None:
    payload = load("espn_scoreboard_eng1_20261108.json")
    rows = flatten_events(payload["events"], league="eng.1", league_name="English Premier League")
    assert len(rows) == 5
    draw = next(row for row in rows if row["event_id"] == EVENT)
    assert (draw["home_team_name"], draw["home_score"], draw["away_score"]) == ("Manchester United", 4, 4)
    assert draw["winner"] == "draw"
    assert draw["kickoff"] == datetime(2026, 11, 8, 16, 30, tzinfo=UTC)
    brighton = next(row for row in rows if row["home_team_abbreviation"] == "BHA")
    assert brighton["winner"] == "home"
    assert brighton["venue_name"] == "American Express Stadium"
    assert brighton["attendance"] == 31629
    assert batch_from_rows(rows, MATCH_SCHEMA).num_rows == 5


def test_all_league_scoreboard_resolves_each_events_league() -> None:
    payload = load("espn_scoreboard_all_current.json")
    rows = flatten_events(
        payload["events"], league="all", league_lookup=league_names(load("espn_leagues.json"))
    )
    assert {row["league_slug"] for row in rows} == {"uefa.wchampions", "esp.copa_del_rey"}
    assert all(row["home_score"] is None for row in rows if row["state"] == "pre")
    assert all(row["winner"] is None for row in rows if not row["completed"])
    unresolved = flatten_events(payload["events"][:1], league="all", league_lookup={})
    assert unresolved[0]["league_slug"] is None
    assert league_uid_id({"uid": "s:600~l:700~e:1"}) == 700
    assert league_uid_id({}) is None


def test_team_schedule_scores_arrive_as_objects() -> None:
    rows = flatten_events(load("espn_team_schedule_360_2025.json")["events"], league="eng.1")
    assert rows[0]["league_slug"] == "eng.1"
    assert all(isinstance(row["home_score"], int) for row in rows)
    fixtures = flatten_events(load("espn_team_fixtures_360.json")["events"], league="eng.1")
    assert all(row["state"] == "pre" and row["home_score"] is None for row in fixtures)


def test_winner_falls_back_to_score_and_shootout() -> None:
    event = {
        "id": "1",
        "competitions": [
            {
                "status": {"type": {"state": "post", "completed": True}},
                "competitors": [
                    {"homeAway": "home", "score": "1", "shootoutScore": 4, "team": {"id": "1"}},
                    {"homeAway": "away", "score": "2", "shootoutScore": {"value": 3}, "team": {"id": "2"}},
                ],
            }
        ],
    }
    row = flatten_events([event, event], league="eng.fa")[0]
    assert row["winner"] == "away"
    assert (row["home_shootout_score"], row["away_shootout_score"]) == (4, 3)


def test_teams_and_roster() -> None:
    teams = flatten_teams(load("espn_teams_eng1.json"), "eng.1")
    assert len(teams) == 20
    assert {"team_id": 360, "team_name": "Manchester United"}.items() <= next(
        team for team in teams if team["team_id"] == 360
    ).items()
    roster = flatten_roster(load("espn_roster_360.json"), "eng.1", 360)
    heaton = roster[0]
    assert heaton["player_name"] == "Tom Heaton"
    assert heaton["date_of_birth"] == date(1986, 4, 15)
    assert heaton["height_in"] == Decimal("74.0")
    assert heaton["position_abbreviation"] == "G"
    batch_from_rows(roster, ROSTER_SCHEMA)
    batch_from_rows(teams, TEAMS_SCHEMA)


def test_2015_leaders_parse_matches_goals_and_assists() -> None:
    rows = flatten_leaders(load("espn_statistics_eng1_2015.json"), "eng.1", 2015)
    goals = [row for row in rows if row["category"] == "goals"]
    assert (goals[0]["player_name"], goals[0]["value"], goals[0]["matches"]) == ("Harry Kane", 25, 38)
    assert goals[0]["season"] == 2015
    assists = [row for row in rows if row["category"] == "assists"]
    assert assists[0]["player_name"] == "Mesut Özil"
    assert assists[0]["assists"] == 19
    assert [row["rank"] for row in goals] == list(range(1, len(goals) + 1))
    current = flatten_leaders(load("espn_statistics_eng1_2015.json"), "eng.1", None)
    assert current[0]["season"] == 2026  # ESPN's payload labels the current season
    batch_from_rows(rows, LEADERS_SCHEMA)


def test_player_stats_merge_outfield_and_goalkeeping() -> None:
    haaland = flatten_player_stats(load("espn_athlete_253989_stats.json"), 253989)
    by_season = {row["season"]: row for row in haaland}
    assert by_season[2022]["goals"] == 36
    assert by_season[2022]["team_name"] == "Manchester City"
    assert [row["season"] for row in haaland] == sorted(by_season, reverse=True)
    keeper = flatten_player_stats(load("espn_athlete_301425_stats.json"), 301425)
    assert all(row.get("saves") is not None and row.get("starts") is not None for row in keeper)
    batch_from_rows(haaland, PLAYER_STATS_SCHEMA)


def test_match_summary_header() -> None:
    payload = load("espn_summary_401879240.json")
    assert summary_event_id(payload) == EVENT
    (row,) = flatten_summary(payload, EVENT)
    assert (row["home_team_name"], row["home_score"], row["away_score"], row["away_team_name"]) == (
        "Manchester United",
        4,
        4,
        "Aston Villa",
    )
    assert row["home_formation"] == "4-2-3-1"
    assert row["home_record"] == "1-5-4"
    assert row["venue_name"] == "Old Trafford"
    assert row["attendance"] == 74149
    assert flatten_summary({}, EVENT) == []
    batch_from_rows([row], SUMMARY_SCHEMA)


def test_match_team_and_player_stats() -> None:
    payload = load("espn_summary_401879240.json")
    teams = flatten_team_stats(payload, EVENT)
    assert [team["home_away"] for team in teams] == ["home", "away"]
    assert sum(team["possession_pct"] for team in teams) == Decimal("100.0")
    united = teams[0]
    assert (united["shots"], united["shots_on_target"], united["passes"]) == (26, 9, 484)
    players = flatten_player_match_stats(payload, EVENT)
    goals = {row["team_name"]: 0 for row in players}
    for row in players:
        goals[row["team_name"]] += row.get("goals") or 0
    assert goals == {"Manchester United": 4, "Aston Villa": 4}
    assert sum(1 for row in players if row["starter"]) == 22
    batch_from_rows(teams, TEAM_STATS_SCHEMA)
    batch_from_rows(players, PLAYER_MATCH_SCHEMA)


def test_key_events_and_commentary() -> None:
    payload = load("espn_summary_401879240.json")
    events = flatten_key_events(payload, EVENT)
    goals = [row for row in events if row["scoring_play"]]
    assert len(goals) == 8
    assert (goals[0]["player_name"], goals[0]["secondary_player_name"], goals[0]["clock_display"]) == (
        "Alysson",
        "John McGinn",
        "1'",
    )
    assert [row["sequence"] for row in events] == list(range(1, len(events) + 1))
    commentary = flatten_commentary(payload, EVENT)
    assert commentary[0]["sequence"] == 0
    assert commentary[2]["play_type"] == "goal"
    batch_from_rows(events, KEY_EVENTS_SCHEMA)
    batch_from_rows(commentary, COMMENTARY_SCHEMA)


def test_plays_extract_ids_from_refs_and_keep_xg() -> None:
    items = load("espn_plays_401879240_p1.json")["items"]
    rows = flatten_plays(items, EVENT)
    assert rows[1]["team_id"] == 362
    assert rows[1]["athlete_id"] == 308524
    assert rows[1]["participant_role"] == "passer"
    shots = [row for row in rows if row["expected_goals"] is not None]
    assert shots and all(0 <= row["expected_goals"] <= 1 for row in shots)
    batch_from_rows(rows, PLAYS_SCHEMA)


def test_world_cup_matches_and_goals() -> None:
    payload = load("openfootball_worldcup_2022.json")
    matches = flatten_world_cup_matches(payload, 2022)
    final = next(row for row in matches if row["round"] == "Final")
    assert (final["team1_goals"], final["team2_goals"]) == (2, 2)
    assert (final["team1_extra_time"], final["team1_penalties"], final["team2_penalties"]) == (3, 4, 2)
    assert final["winner"] == "Argentina"
    opener = matches[0]
    assert (opener["team1"], opener["winner"], opener["match_date"]) == (
        "Qatar",
        "Ecuador",
        date(2022, 11, 20),
    )
    goals = flatten_world_cup_goals(payload, 2022)
    final_goals = [row for row in goals if row["round"] == "Final"]
    assert len(final_goals) == 6
    assert sum(row["penalty"] for row in final_goals) == 3
    stoppage = flatten_world_cup_goals(
        {
            "matches": [
                {"team1": "A", "team2": "B", "goals1": [{"name": "X", "minute": "90+3", "owngoal": True}]}
            ]
        },
        2014,
    )
    assert (stoppage[0]["minute"], stoppage[0]["stoppage_minute"], stoppage[0]["own_goal"]) == (90, 3, True)
    batch_from_rows(matches, WORLD_CUP_MATCHES_SCHEMA)
    batch_from_rows(goals, WORLD_CUP_GOALS_SCHEMA)


def test_openligadb_table_and_matches() -> None:
    table = flatten_bundesliga_table(load("openligadb_table_bl1_2025.json"), "bl1", 2025)
    assert (table[0]["team_name"], table[0]["points"], table[0]["position"]) == ("FC Bayern München", 89, 1)
    matches = flatten_bundesliga_matches(load("openligadb_matches_bl1_2025_10.json"), "bl1")
    first = matches[0]
    assert (first["team1_name"], first["team1_goals"], first["team2_goals"]) == (
        "Borussia Mönchengladbach",
        3,
        1,
    )
    assert (first["team1_halftime"], first["team2_halftime"]) == (1, 0)
    assert first["kickoff"] == datetime(2025, 11, 8, 17, 30, tzinfo=UTC)
    assert first["matchday"] == 10
    batch_from_rows(table, BUNDESLIGA_TABLE_SCHEMA)
    batch_from_rows(matches, BUNDESLIGA_MATCHES_SCHEMA)


def test_projected_schema_selects_only_requested_columns() -> None:
    rows = flatten_standings(load("espn_standings_eng1_2015.json"), "eng.1")
    projected = pa.schema([STANDINGS_SCHEMA.field("points"), STANDINGS_SCHEMA.field("team_name")])
    batch = batch_from_rows(rows, projected)
    assert batch.schema.names == ["points", "team_name"]
