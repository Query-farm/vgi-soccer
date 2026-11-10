"""Every table function's process() against recorded fixtures, in-process."""

from __future__ import annotations

from datetime import date

import pytest
from harness import run_function

from vgi_soccer.match_detail import (
    MatchArgs,
    MatchCommentaryFunction,
    MatchKeyEventsFunction,
    MatchPlayerStatsFunction,
    MatchPlaysFunction,
    MatchSummaryFunction,
    MatchTeamStatsFunction,
)
from vgi_soccer.matches import (
    CurrentMatchesFunction,
    ScheduleArgs,
    ScheduleFunction,
    ScoreboardArgs,
    ScoreboardFunction,
    TeamScheduleArgs,
    TeamScheduleFunction,
)
from vgi_soccer.open_sources import (
    BundesligaMatchesArgs,
    BundesligaMatchesFunction,
    BundesligaTableArgs,
    BundesligaTableFunction,
    WorldCupArgs,
    WorldCupGoalsFunction,
    WorldCupMatchesFunction,
)
from vgi_soccer.standings import (
    CurrentStandingsFunction,
    LeaguesFunction,
    StandingsArgs,
    StandingsFunction,
)
from vgi_soccer.teams import (
    CurrentStatLeadersFunction,
    LeadersArgs,
    PlayerStatsArgs,
    PlayerStatsFunction,
    RosterArgs,
    RosterFunction,
    StatLeadersFunction,
    TeamsArgs,
    TeamsFunction,
)

pytestmark = pytest.mark.usefixtures("fixture_upstream")
EVENT = 401879240


def test_leagues_and_standings() -> None:
    assert len(run_function(LeaguesFunction).rows()) >= 10
    out = run_function(StandingsFunction, StandingsArgs(league="eng.1", season=2015))
    rows = out.rows()
    assert rows[0]["team_name"] == "Leicester City" and rows[0]["points"] == 81
    assert out.cache_controls[0] is not None
    current = run_function(CurrentStandingsFunction).rows()
    assert {row["league_slug"] for row in current} == {"eng.1", "esp.1", "ger.1", "ita.1", "fra.1"}


def test_standings_reject_all_pseudo_league() -> None:
    with pytest.raises(ValueError, match="one competition"):
        run_function(StandingsFunction, StandingsArgs(league="all", season=None))


def test_scoreboards(fixture_upstream) -> None:
    rows = run_function(
        ScoreboardFunction, ScoreboardArgs(league="eng.1", match_date=date(2026, 11, 8))
    ).rows()
    assert len(rows) == 5 and rows[0]["league_name"] == "English Premier League"
    assert fixture_upstream[-1].url.params["dates"] == "20261108"
    everything = run_function(ScoreboardFunction, ScoreboardArgs(league="all", match_date=None)).rows()
    assert all(row["league_slug"] for row in everything)
    assert run_function(CurrentMatchesFunction).rows() == everything


def test_schedule_merges_both_calendar_years_and_filters_the_season(fixture_upstream) -> None:
    rows = run_function(ScheduleFunction, ScheduleArgs(league="eng.1", season=2025)).rows()
    assert rows and {row["season"] for row in rows} == {2025}
    assert [row["kickoff"] for row in rows] == sorted(row["kickoff"] for row in rows)
    dates = [request.url.params.get("dates") for request in fixture_upstream]
    assert dates == ["2025", "2026"]


def test_schedule_defaults_to_espns_current_season(fixture_upstream) -> None:
    run_function(ScheduleFunction, ScheduleArgs(league="eng.1", season=None))
    dates = [request.url.params.get("dates") for request in fixture_upstream]
    assert dates == [None, "2026", "2027"]


def test_team_schedule_merges_results_and_fixtures() -> None:
    rows = run_function(
        TeamScheduleFunction, TeamScheduleArgs(team_id=360, league="eng.1", season=None)
    ).rows()
    states = [row["state"] for row in rows]
    assert "post" in states and "pre" in states
    assert [row["kickoff"] for row in rows] == sorted(row["kickoff"] for row in rows)


def test_teams_roster_leaders_and_player_stats() -> None:
    assert len(run_function(TeamsFunction, TeamsArgs(league="eng.1")).rows()) == 20
    roster = run_function(RosterFunction, RosterArgs(team_id=360, league="eng.1")).rows()
    assert all(row["team_id"] == 360 for row in roster)
    leaders = run_function(StatLeadersFunction, LeadersArgs(league="eng.1", season=2015)).rows()
    assert leaders[0]["player_name"] == "Harry Kane"
    current = run_function(CurrentStatLeadersFunction).rows()
    assert len({row["league_slug"] for row in current}) == 5
    lines = run_function(PlayerStatsFunction, PlayerStatsArgs(athlete_id=253989, league="eng.1")).rows()
    assert max(row["goals"] for row in lines) == 36
    run_function(PlayerStatsFunction, PlayerStatsArgs(athlete_id=301425, league=None))


@pytest.mark.parametrize(
    ("function", "expected_rows"),
    [
        (MatchSummaryFunction, 1),
        (MatchTeamStatsFunction, 2),
        (MatchKeyEventsFunction, 38),
        (MatchCommentaryFunction, 12),
    ],
)
def test_match_detail_functions(function, expected_rows: int) -> None:
    rows = run_function(function, MatchArgs(event_id=EVENT)).rows()
    assert len(rows) == expected_rows
    assert all(row["event_id"] == EVENT for row in rows)


def test_match_player_stats_and_plays() -> None:
    players = run_function(MatchPlayerStatsFunction, MatchArgs(event_id=EVENT)).rows()
    assert sum(row["goals"] or 0 for row in players) == 8
    plays = run_function(MatchPlaysFunction, MatchArgs(event_id=EVENT)).rows()
    assert len(plays) == 18  # both recorded pages
    assert [row["sequence"] for row in plays] == list(range(1, 19))


def test_open_data_functions() -> None:
    matches = run_function(WorldCupMatchesFunction, WorldCupArgs(year=2022)).rows()
    assert any(row["winner"] == "Argentina" for row in matches)
    goals = run_function(WorldCupGoalsFunction, WorldCupArgs(year=2022)).rows()
    assert goals
    table = run_function(BundesligaTableFunction, BundesligaTableArgs(season=2025, league="bl1")).rows()
    assert table[0]["position"] == 1
    fixtures = run_function(
        BundesligaMatchesFunction, BundesligaMatchesArgs(season=2025, league="bl1", matchday=10)
    ).rows()
    assert [row["kickoff"] for row in fixtures] == sorted(row["kickoff"] for row in fixtures)
