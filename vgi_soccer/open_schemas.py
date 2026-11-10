"""Arrow schemas and flattening for openfootball (CC0) and OpenLigaDB open data."""

from __future__ import annotations

import re
from typing import Any

import pyarrow as pa

from vgi_soccer.meta import (
    TIMESTAMP,
    field,
    mapping,
    sequence,
    to_bool,
    to_date,
    to_int,
    to_text,
    to_timestamp,
)

WORLD_CUP_MATCHES_SCHEMA = pa.schema(
    [
        field("year", pa.int32(), "Tournament year, e.g. 2022.", nullable=False),
        field(
            "match_number",
            pa.int32(),
            "Match number within the tournament (1 = opening match).",
            nullable=False,
        ),
        field("round", pa.string(), "Round, e.g. Matchday 1, Quarter-finals, Final."),
        field("group_name", pa.string(), "Group, for group-stage matches."),
        field("match_date", pa.date32(), "Local match date."),
        field("kickoff_time", pa.string(), "Local kick-off time as published, e.g. 15:00 UTC-4."),
        field("ground", pa.string(), "Stadium and city."),
        field("team1", pa.string(), "First-named team."),
        field("team2", pa.string(), "Second-named team."),
        field("team1_goals", pa.int32(), "Number of team 1 goals after 90 minutes."),
        field("team2_goals", pa.int32(), "Number of team 2 goals after 90 minutes."),
        field("team1_halftime", pa.int32(), "Number of team 1 goals at half-time."),
        field("team2_halftime", pa.int32(), "Number of team 2 goals at half-time."),
        field("team1_extra_time", pa.int32(), "Number of team 1 goals after extra time, when played."),
        field("team2_extra_time", pa.int32(), "Number of team 2 goals after extra time, when played."),
        field("team1_penalties", pa.int32(), "Number of team 1 penalties scored in a shoot-out, when taken."),
        field("team2_penalties", pa.int32(), "Number of team 2 penalties scored in a shoot-out, when taken."),
        field("winner", pa.string(), "Winning team name; null for a draw or unplayed match."),
    ]
)

WORLD_CUP_GOALS_SCHEMA = pa.schema(
    [
        field("year", pa.int32(), "Tournament year, e.g. 2022.", nullable=False),
        field(
            "match_number",
            pa.int32(),
            "Match number within the tournament (1 = opening match).",
            nullable=False,
        ),
        field("round", pa.string(), "Round."),
        field("team", pa.string(), "Team credited with the goal."),
        field("opponent", pa.string(), "Opposing team."),
        field("player_name", pa.string(), "Scorer (for an own goal, the defender)."),
        field("minute", pa.int32(), "Regulation minute of the goal, e.g. 90 for 90+3."),
        field("stoppage_minute", pa.int32(), "Added-time minutes, e.g. 3 for 90+3."),
        field("minute_display", pa.string(), "Minute as published, e.g. 90+3."),
        field("penalty", pa.bool_(), "Scored from the penalty spot in play."),
        field("own_goal", pa.bool_(), "Own goal by the opposing team's player."),
    ]
)

BUNDESLIGA_TABLE_SCHEMA = pa.schema(
    [
        field("league", pa.string(), "OpenLigaDB league shortcut, e.g. bl1.", nullable=False),
        field("season", pa.int32(), "Season start year (2025 = 2025-26).", nullable=False),
        field("position", pa.int32(), "Table position (1 = top).", nullable=False),
        field("team_id", pa.int32(), "OpenLigaDB team identifier (opaque integer).", nullable=False),
        field("team_name", pa.string(), "Club or national team display name."),
        field("short_name", pa.string(), "Short team name."),
        field("matches", pa.int32(), "Number of matches played."),
        field("wins", pa.int32(), "Number of matches won."),
        field("draws", pa.int32(), "Number of matches drawn."),
        field("losses", pa.int32(), "Number of matches lost."),
        field("goals_for", pa.int32(), "Number of goals scored."),
        field("goals_against", pa.int32(), "Number of goals conceded."),
        field("goal_difference", pa.int32(), "Goal difference: goals for minus goals against (count)."),
        field("points", pa.int32(), "League points (3 per win, 1 per draw)."),
    ]
)

BUNDESLIGA_MATCHES_SCHEMA = pa.schema(
    [
        field("match_id", pa.int32(), "OpenLigaDB match identifier (opaque integer).", nullable=False),
        field("league", pa.string(), "OpenLigaDB league shortcut."),
        field("league_name", pa.string(), "Competition name."),
        field("season", pa.int32(), "Season start year (2025 = 2025-26)."),
        field("matchday", pa.int32(), "Matchday (Spieltag) or cup round number (1 = first)."),
        field("matchday_name", pa.string(), "Matchday label, e.g. 10. Spieltag."),
        field("kickoff", TIMESTAMP, "Kick-off time in UTC."),
        field("team1_id", pa.int32(), "Home team OpenLigaDB identifier (opaque integer)."),
        field("team1_name", pa.string(), "Home side display name, e.g. Manchester United."),
        field("team2_id", pa.int32(), "Away team OpenLigaDB identifier (opaque integer)."),
        field("team2_name", pa.string(), "Away side display name, e.g. Aston Villa."),
        field("team1_goals", pa.int32(), "Number of home goals at full time."),
        field("team2_goals", pa.int32(), "Number of away goals at full time."),
        field("team1_halftime", pa.int32(), "Number of home goals at half-time."),
        field("team2_halftime", pa.int32(), "Number of away goals at half-time."),
        field("finished", pa.bool_(), "Whether the match is finished."),
        field("viewers", pa.int32(), "Number of spectators reported (null when unknown)."),
    ]
)

_MINUTE = re.compile(r"^\s*(\d+)(?:\s*\+\s*(\d+))?")


def _pair(score: Any, key: str) -> tuple[int | None, int | None]:
    values = sequence(mapping(score).get(key))
    if len(values) != 2:
        return None, None
    return to_int(values[0]), to_int(values[1])


def _match_row(match: Any, index: int, year: int) -> dict[str, Any]:
    match = mapping(match)
    score = match.get("score")
    ft1, ft2 = _pair(score, "ft")
    ht1, ht2 = _pair(score, "ht")
    et1, et2 = _pair(score, "et")
    p1, p2 = _pair(score, "p")
    winner = None
    for first, second in ((p1, p2), (et1, et2), (ft1, ft2)):
        if first is not None and second is not None:
            if first != second:
                winner = match.get("team1") if first > second else match.get("team2")
            break
    return {
        "year": year,
        "match_number": to_int(match.get("num")) or index,
        "round": to_text(match.get("round")),
        "group_name": to_text(match.get("group")),
        "match_date": to_date(match.get("date")),
        "kickoff_time": to_text(match.get("time")),
        "ground": to_text(match.get("ground")),
        "team1": to_text(match.get("team1")),
        "team2": to_text(match.get("team2")),
        "team1_goals": ft1,
        "team2_goals": ft2,
        "team1_halftime": ht1,
        "team2_halftime": ht2,
        "team1_extra_time": et1,
        "team2_extra_time": et2,
        "team1_penalties": p1,
        "team2_penalties": p2,
        "winner": to_text(winner),
    }


def flatten_world_cup_matches(payload: Any, year: int) -> list[dict[str, Any]]:
    """One row per match in an openfootball worldcup.json file."""
    matches = sequence(mapping(payload).get("matches"))
    return [_match_row(match, index, year) for index, match in enumerate(matches, start=1)]


def flatten_world_cup_goals(payload: Any, year: int) -> list[dict[str, Any]]:
    """One row per goal; openfootball lists each goal under the team it counts for."""
    rows: list[dict[str, Any]] = []
    for index, source in enumerate(sequence(mapping(payload).get("matches")), start=1):
        source = mapping(source)
        match = _match_row(source, index, year)
        for side, team, opponent in (("goals1", "team1", "team2"), ("goals2", "team2", "team1")):
            for goal in sequence(source.get(side)):
                goal = mapping(goal)
                display = to_text(goal.get("minute"))
                parsed = _MINUTE.match(display or "")
                rows.append(
                    {
                        "year": year,
                        "match_number": match["match_number"],
                        "round": match["round"],
                        "team": match[team],
                        "opponent": match[opponent],
                        "player_name": to_text(goal.get("name")),
                        "minute": int(parsed.group(1)) if parsed else None,
                        "stoppage_minute": int(parsed.group(2)) if parsed and parsed.group(2) else None,
                        "minute_display": display,
                        "penalty": bool(goal.get("penalty")),
                        "own_goal": bool(goal.get("owngoal")),
                    }
                )
    return rows


def flatten_bundesliga_table(payload: Any, league: str, season: int) -> list[dict[str, Any]]:
    """One row per team in an OpenLigaDB table, in table order."""
    rows: list[dict[str, Any]] = []
    for position, team in enumerate(sequence(payload), start=1):
        team = mapping(team)
        team_id = to_int(team.get("teamInfoId", team.get("teamId")))
        if team_id is None:
            continue
        rows.append(
            {
                "league": league,
                "season": season,
                "position": position,
                "team_id": team_id,
                "team_name": to_text(team.get("teamName")),
                "short_name": to_text(team.get("shortName")),
                "matches": to_int(team.get("matches")),
                "wins": to_int(team.get("won")),
                "draws": to_int(team.get("draw")),
                "losses": to_int(team.get("lost")),
                "goals_for": to_int(team.get("goals")),
                "goals_against": to_int(team.get("opponentGoals")),
                "goal_difference": to_int(team.get("goalDiff")),
                "points": to_int(team.get("points")),
            }
        )
    return rows


def _result(match: Any, type_id: int) -> tuple[int | None, int | None]:
    for result in sequence(mapping(match).get("matchResults")):
        result = mapping(result)
        if to_int(result.get("resultTypeID")) == type_id:
            return to_int(result.get("pointsTeam1")), to_int(result.get("pointsTeam2"))
    return None, None


def flatten_bundesliga_matches(payload: Any, league: str) -> list[dict[str, Any]]:
    """One row per OpenLigaDB match."""
    rows: list[dict[str, Any]] = []
    for match in sequence(payload):
        match = mapping(match)
        match_id = to_int(match.get("matchID"))
        if match_id is None:
            continue
        group = mapping(match.get("group"))
        team1, team2 = mapping(match.get("team1")), mapping(match.get("team2"))
        ft1, ft2 = _result(match, 2)
        ht1, ht2 = _result(match, 1)
        rows.append(
            {
                "match_id": match_id,
                "league": to_text(match.get("leagueShortcut")) or league,
                "league_name": to_text(match.get("leagueName")),
                "season": to_int(match.get("leagueSeason")),
                "matchday": to_int(group.get("groupOrderID")),
                "matchday_name": to_text(group.get("groupName")),
                "kickoff": to_timestamp(match.get("matchDateTimeUTC")),
                "team1_id": to_int(team1.get("teamId")),
                "team1_name": to_text(team1.get("teamName")),
                "team2_id": to_int(team2.get("teamId")),
                "team2_name": to_text(team2.get("teamName")),
                "team1_goals": ft1,
                "team2_goals": ft2,
                "team1_halftime": ht1,
                "team2_halftime": ht2,
                "finished": to_bool(match.get("matchIsFinished")),
                "viewers": to_int(match.get("numberOfViewers")),
            }
        )
    return rows
