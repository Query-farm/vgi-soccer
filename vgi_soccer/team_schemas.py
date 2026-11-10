"""Arrow schemas and flattening for teams, squads, leaderboards, and player season totals."""

from __future__ import annotations

import re
from typing import Any

import pyarrow as pa

from vgi_soccer.meta import (
    field,
    mapping,
    sequence,
    to_bool,
    to_date,
    to_decimal,
    to_int,
    to_text,
)

TEAMS_SCHEMA = pa.schema(
    [
        field("league_slug", pa.string(), "ESPN league slug the team list was requested for."),
        field(
            "team_id",
            pa.int32(),
            "ESPN team identifier (opaque integer); pass it to roster() and team_schedule().",
            nullable=False,
        ),
        field("team_name", pa.string(), "Team display name as ESPN shows it, e.g. Leicester City."),
        field("short_name", pa.string(), "Short display name."),
        field("abbreviation", pa.string(), "Three-letter team code, e.g. LEI."),
        field("location", pa.string(), "Location or club name."),
        field("nickname", pa.string(), "Nickname."),
        field("slug", pa.string(), "ESPN team slug."),
        field("color", pa.string(), "Primary colour as hex."),
        field("alternate_color", pa.string(), "Secondary colour as hex."),
        field("is_active", pa.bool_(), "Whether ESPN marks the team active."),
    ]
)

ROSTER_SCHEMA = pa.schema(
    [
        field("league_slug", pa.string(), "ESPN league slug."),
        field("team_id", pa.int32(), "ESPN team identifier (opaque integer)."),
        field(
            "athlete_id",
            pa.int64(),
            "ESPN player identifier (opaque integer); pass it to player_stats().",
            nullable=False,
        ),
        field("player_name", pa.string(), "Player display name, e.g. Harry Kane."),
        field("first_name", pa.string(), "First name."),
        field("last_name", pa.string(), "Last name."),
        field("jersey", pa.string(), "Shirt number."),
        field("position", pa.string(), "Position, e.g. Goalkeeper or Forward."),
        field("position_abbreviation", pa.string(), "Position code: G, D, M, or F."),
        field("age", pa.int32(), "Age in years."),
        field("date_of_birth", pa.date32(), "Date of birth."),
        field("citizenship", pa.string(), "Nationality."),
        field("height_in", pa.decimal128(5, 1), "Height in inches."),
        field("weight_lb", pa.decimal128(5, 1), "Weight in pounds."),
        field("gender", pa.string(), "MALE or FEMALE."),
        field("status", pa.string(), "Squad status, e.g. Active."),
        field("injury_status", pa.string(), "Most recent injury status, when reported."),
    ]
)

LEADERS_SCHEMA = pa.schema(
    [
        field("league_slug", pa.string(), "ESPN league slug.", nullable=False),
        field("season", pa.int32(), "Season start year (2015 = 2015-16)."),
        field("category", pa.string(), "Leaderboard: goals or assists.", nullable=False),
        field("rank", pa.int32(), "Position (1 = best) in ESPN's ordered leaderboard.", nullable=False),
        field("athlete_id", pa.int64(), "ESPN player identifier (opaque integer).", nullable=False),
        field("player_name", pa.string(), "Player display name, e.g. Harry Kane."),
        field("team_id", pa.int32(), "ESPN team identifier (opaque integer)."),
        field("team_name", pa.string(), "Club or national team display name."),
        field("team_abbreviation", pa.string(), "Three-letter team code, e.g. LEI."),
        field("value", pa.int32(), "Leaderboard value: number of goals or assists, per category."),
        field("matches", pa.int32(), "Number of matches played."),
        field("goals", pa.int32(), "Number of goals scored."),
        field("assists", pa.int32(), "Number of assists (passes leading directly to a goal)."),
    ]
)

PLAYER_STATS_SCHEMA = pa.schema(
    [
        field("athlete_id", pa.int64(), "ESPN player identifier (opaque integer).", nullable=False),
        field("league_slug", pa.string(), "ESPN league slug of this season line."),
        field("season", pa.int32(), "Season start year (2025 = 2025-26)."),
        field("season_name", pa.string(), "Season label."),
        field("team_id", pa.int32(), "ESPN team id the line belongs to."),
        field("team_name", pa.string(), "Club or national team display name."),
        field("starts", pa.int32(), "Number of matches started."),
        field("goals", pa.int32(), "Number of goals scored."),
        field("assists", pa.int32(), "Number of assists (passes leading directly to a goal)."),
        field("shots", pa.int32(), "Number of shots attempted."),
        field("shots_on_target", pa.int32(), "Number of shots on target."),
        field("fouls_committed", pa.int32(), "Number of fouls committed."),
        field("fouls_suffered", pa.int32(), "Number of fouls suffered."),
        field("offsides", pa.int32(), "Number of times caught offside."),
        field("yellow_cards", pa.int32(), "Number of yellow cards."),
        field("red_cards", pa.int32(), "Number of red cards."),
        field("clean_sheets", pa.int32(), "Number of clean sheets kept as goalkeeper."),
        field("saves", pa.int32(), "Number of saves made as goalkeeper."),
        field("goals_conceded", pa.int32(), "Number of goals conceded as goalkeeper."),
    ]
)

_LABELS = {
    "STRT": "starts",
    "G": "goals",
    "A": "assists",
    "SHOT": "shots",
    "SOG": "shots_on_target",
    "FC": "fouls_committed",
    "FA": "fouls_suffered",
    "OFF": "offsides",
    "YC": "yellow_cards",
    "RC": "red_cards",
    "CS": "clean_sheets",
    "SV": "saves",
    "GA": "goals_conceded",
}
_DISPLAY_NUMBER = re.compile(r"\b(M|G|A|Matches|Goals|Assists):\s*(\d+)")


def flatten_teams(payload: Any, league: str) -> list[dict[str, Any]]:
    """One row per team listed for a league."""
    rows: list[dict[str, Any]] = []
    for sport in sequence(mapping(payload).get("sports")):
        for competition in sequence(mapping(sport).get("leagues")):
            for wrapper in sequence(mapping(competition).get("teams")):
                team = mapping(mapping(wrapper).get("team"))
                team_id = to_int(team.get("id"))
                if team_id is None:
                    continue
                rows.append(
                    {
                        "league_slug": league,
                        "team_id": team_id,
                        "team_name": to_text(team.get("displayName")),
                        "short_name": to_text(team.get("shortDisplayName")),
                        "abbreviation": to_text(team.get("abbreviation")),
                        "location": to_text(team.get("location")),
                        "nickname": to_text(team.get("nickname")),
                        "slug": to_text(team.get("slug")),
                        "color": to_text(team.get("color")),
                        "alternate_color": to_text(team.get("alternateColor")),
                        "is_active": to_bool(team.get("isActive")),
                    }
                )
    return rows


def flatten_roster(payload: Any, league: str, team_id: int) -> list[dict[str, Any]]:
    """One row per squad member."""
    rows: list[dict[str, Any]] = []
    for athlete in sequence(mapping(payload).get("athletes")):
        athlete = mapping(athlete)
        athlete_id = to_int(athlete.get("id"))
        if athlete_id is None:
            continue
        position = mapping(athlete.get("position"))
        injuries = sequence(athlete.get("injuries"))
        rows.append(
            {
                "league_slug": league,
                "team_id": team_id,
                "athlete_id": athlete_id,
                "player_name": to_text(athlete.get("displayName")),
                "first_name": to_text(athlete.get("firstName")),
                "last_name": to_text(athlete.get("lastName")),
                "jersey": to_text(athlete.get("jersey")),
                "position": to_text(position.get("displayName") or position.get("name")),
                "position_abbreviation": to_text(position.get("abbreviation")),
                "age": to_int(athlete.get("age")),
                "date_of_birth": to_date(athlete.get("dateOfBirth")),
                "citizenship": to_text(athlete.get("citizenship")),
                "height_in": to_decimal(athlete.get("height")),
                "weight_lb": to_decimal(athlete.get("weight")),
                "gender": to_text(athlete.get("gender")),
                "status": to_text(mapping(athlete.get("status")).get("name")),
                "injury_status": to_text(mapping(injuries[0]).get("status")) if injuries else None,
            }
        )
    return rows


def _display_numbers(*values: Any) -> dict[str, int]:
    found: dict[str, int] = {}
    for value in values:
        if not isinstance(value, str):
            continue
        for key, number in _DISPLAY_NUMBER.findall(value):
            found.setdefault(key[0], int(number))
    return found


def flatten_leaders(payload: Any, league: str, season: int | None) -> list[dict[str, Any]]:
    """One row per player per leaderboard (goals, assists).

    ESPN labels the response with its *current* season even when an older one
    was requested, so the payload's season is used only when none was asked for.
    """
    if season is None:
        season = to_int(mapping(mapping(payload).get("season")).get("year"))
    rows: list[dict[str, Any]] = []
    for board in sequence(mapping(payload).get("stats")):
        board = mapping(board)
        name = to_text(board.get("name")) or ""
        category = name.removesuffix("Leaders") or None
        if category is None:
            continue
        for rank, leader in enumerate(sequence(board.get("leaders")), start=1):
            leader = mapping(leader)
            athlete = mapping(leader.get("athlete"))
            athlete_id = to_int(athlete.get("id"))
            if athlete_id is None:
                continue
            team = mapping(athlete.get("team"))
            numbers = _display_numbers(leader.get("shortDisplayValue"), leader.get("displayValue"))
            rows.append(
                {
                    "league_slug": league,
                    "season": season,
                    "category": category,
                    "rank": rank,
                    "athlete_id": athlete_id,
                    "player_name": to_text(athlete.get("displayName")),
                    "team_id": to_int(team.get("id")),
                    "team_name": to_text(team.get("displayName") or team.get("name")),
                    "team_abbreviation": to_text(team.get("abbreviation")),
                    "value": to_int(leader.get("value")),
                    "matches": numbers.get("M"),
                    "goals": numbers.get("G"),
                    "assists": numbers.get("A"),
                }
            )
    return rows


def _team_names(payload: Any) -> dict[str, str]:
    names: dict[str, str] = {}
    for item in sequence(mapping(payload).get("filters")):
        item = mapping(item)
        if item.get("name") != "team":
            continue
        for option in sequence(item.get("options")):
            option = mapping(option)
            if option.get("value") is not None and option.get("displayValue"):
                names[str(option["value"])] = str(option["displayValue"])
    return names


def flatten_player_stats(payload: Any, athlete_id: int) -> list[dict[str, Any]]:
    """One row per team-league-season, merging ESPN's outfield and goalkeeping categories."""
    team_names = _team_names(payload)
    merged: dict[tuple[str | None, str | None, int | None], dict[str, Any]] = {}
    for category in sequence(mapping(payload).get("categories")):
        category = mapping(category)
        labels = [str(label) for label in sequence(category.get("labels") or category.get("names"))]
        for line in sequence(category.get("statistics")):
            line = mapping(line)
            season = mapping(line.get("season"))
            team_id = to_text(line.get("teamId"))
            key = (team_id, to_text(line.get("leagueSlug")), to_int(season.get("year")))
            row = merged.setdefault(
                key,
                {
                    "athlete_id": athlete_id,
                    "league_slug": key[1],
                    "season": key[2],
                    "season_name": to_text(season.get("displayName")),
                    "team_id": to_int(team_id),
                    "team_name": team_names.get(team_id or ""),
                },
            )
            for label, value in zip(labels, sequence(line.get("stats")), strict=False):
                column = _LABELS.get(label)
                if column is not None:
                    row[column] = to_int(value)
    return sorted(
        merged.values(),
        key=lambda row: (-(row["season"] or 0), row["league_slug"] or "", row["team_id"] or 0),
    )
