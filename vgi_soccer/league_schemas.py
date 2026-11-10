"""Arrow schemas and flattening for the league directory and league tables."""

from __future__ import annotations

from typing import Any

import pyarrow as pa

from vgi_soccer.meta import field, mapping, sequence, to_bool, to_int, to_text

LEAGUES_SCHEMA = pa.schema(
    [
        field(
            "league_slug",
            pa.string(),
            "ESPN league slug used by every league argument, e.g. eng.1.",
            nullable=False,
        ),
        field(
            "espn_league_id",
            pa.int32(),
            "ESPN numeric league identifier (an opaque integer, also embedded in event uids).",
        ),
        field("league_name", pa.string(), "Full competition name."),
        field("abbreviation", pa.string(), "ESPN abbreviation."),
        field("short_name", pa.string(), "Short competition name."),
        field("midsize_name", pa.string(), "Mid-length label such as ENG.1."),
        field("has_standings", pa.bool_(), "Whether ESPN publishes a league table for it."),
    ]
)

STANDINGS_SCHEMA = pa.schema(
    [
        field("league_slug", pa.string(), "ESPN league slug, e.g. eng.1.", nullable=False),
        field("league_name", pa.string(), "Competition name."),
        field("season", pa.int32(), "Season start year; 2015 is the 2015-16 season."),
        field("season_name", pa.string(), "Season label, e.g. 2015-16 Barclays Premier League."),
        field("group_name", pa.string(), "Table or group, e.g. Group A or League Phase."),
        field("rank", pa.int32(), "Table position (1 = top) within the table or group."),
        field(
            "team_id",
            pa.int32(),
            "ESPN team identifier (opaque integer; key for roster() and team_schedule()).",
            nullable=False,
        ),
        field("team_name", pa.string(), "Team display name as ESPN shows it, e.g. Leicester City."),
        field("team_abbreviation", pa.string(), "Three-letter team code, e.g. LEI."),
        field("games_played", pa.int32(), "Number of matches played."),
        field("wins", pa.int32(), "Number of matches won."),
        field("draws", pa.int32(), "Number of matches drawn."),
        field("losses", pa.int32(), "Number of matches lost."),
        field("goals_for", pa.int32(), "Number of goals scored."),
        field("goals_against", pa.int32(), "Number of goals conceded."),
        field("goal_difference", pa.int32(), "Goal difference: goals for minus goals against (count)."),
        field("points", pa.int32(), "League points (3 per win, 1 per draw) after any deductions."),
        field("point_deductions", pa.int32(), "Number of points deducted by the competition (0 when none)."),
        field("rank_change", pa.int32(), "Number of places gained (+) or lost (-) since the last round."),
        field("record", pa.string(), "ESPN W-D-L summary."),
        field("qualification", pa.string(), "Zone note, e.g. Champions League or Relegation."),
    ]
)


def flatten_leagues(payload: Any) -> list[dict[str, Any]]:
    """One row per competition in ESPN's soccer league directory."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for league in sequence(mapping(payload).get("leagues")):
        league = mapping(league)
        slug = to_text(league.get("slug"))
        if slug is None or slug in seen:
            continue
        seen.add(slug)
        rows.append(
            {
                "league_slug": slug,
                "espn_league_id": to_int(league.get("id")),
                "league_name": to_text(league.get("name")),
                "abbreviation": to_text(league.get("abbreviation")),
                "short_name": to_text(league.get("shortName")),
                "midsize_name": to_text(league.get("midsizeName")),
                "has_standings": to_bool(league.get("hasStandings")),
            }
        )
    return rows


def league_names(payload: Any) -> dict[int, tuple[str, str | None]]:
    """Map ESPN numeric league ids to ``(slug, name)`` from the league directory."""
    return {
        row["espn_league_id"]: (row["league_slug"], row["league_name"])
        for row in flatten_leagues(payload)
        if row["espn_league_id"] is not None
    }


def _stats(entry: Any) -> dict[str, Any]:
    """Pivot ESPN's name/value stat list into a mapping of stat name to stat object."""
    return {
        stat["name"]: stat
        for stat in sequence(mapping(entry).get("stats"))
        if isinstance(stat, dict) and isinstance(stat.get("name"), str)
    }


def _value(stats: dict[str, Any], name: str) -> int | None:
    stat = mapping(stats.get(name))
    value = to_int(stat.get("value"))
    return value if value is not None else to_int(stat.get("displayValue"))


def flatten_standings(payload: Any, league: str) -> list[dict[str, Any]]:
    """One row per team per table/group; competitions without a table yield no rows."""
    root = mapping(payload)
    rows: list[dict[str, Any]] = []
    children = sequence(root.get("children"))
    # Single-table competitions occasionally put standings at the root.
    if not children and root.get("standings"):
        children = [root]
    for group in children:
        group = mapping(group)
        standings = mapping(group.get("standings"))
        group_name = to_text(group.get("name"))
        for entry in sequence(standings.get("entries")):
            entry = mapping(entry)
            team = mapping(entry.get("team"))
            team_id = to_int(team.get("id"))
            if team_id is None:
                continue
            stats = _stats(entry)
            rows.append(
                {
                    "league_slug": league,
                    "league_name": to_text(root.get("name")),
                    "season": to_int(standings.get("season")),
                    "season_name": to_text(standings.get("seasonDisplayName")),
                    "group_name": group_name,
                    "rank": _value(stats, "rank"),
                    "team_id": team_id,
                    "team_name": to_text(team.get("displayName")),
                    "team_abbreviation": to_text(team.get("abbreviation")),
                    "games_played": _value(stats, "gamesPlayed"),
                    "wins": _value(stats, "wins"),
                    "draws": _value(stats, "ties"),
                    "losses": _value(stats, "losses"),
                    "goals_for": _value(stats, "pointsFor"),
                    "goals_against": _value(stats, "pointsAgainst"),
                    "goal_difference": _value(stats, "pointDifferential"),
                    "points": _value(stats, "points"),
                    "point_deductions": _value(stats, "deductions"),
                    "rank_change": _value(stats, "rankChange"),
                    "record": to_text(mapping(stats.get("overall")).get("displayValue")),
                    "qualification": to_text(mapping(entry.get("note")).get("description")),
                }
            )
    return rows
