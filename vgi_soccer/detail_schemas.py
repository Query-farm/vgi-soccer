"""Arrow schemas and flattening for single-match detail from ESPN summaries and plays."""

from __future__ import annotations

from typing import Any

import pyarrow as pa

from vgi_soccer.meta import (
    TIMESTAMP,
    field,
    mapping,
    ref_id,
    sequence,
    to_bool,
    to_decimal,
    to_float,
    to_int,
    to_text,
    to_timestamp,
)

_EVENT_ID = field("event_id", pa.int64(), "ESPN match identifier (opaque integer).", nullable=False)

SUMMARY_SCHEMA = pa.schema(
    [
        _EVENT_ID,
        field("league_slug", pa.string(), "ESPN league slug."),
        field("league_name", pa.string(), "Competition name."),
        field("season", pa.int32(), "Season start year (2025 = 2025-26)."),
        field("kickoff", TIMESTAMP, "Kick-off time in UTC."),
        field("state", pa.string(), "pre, in, or post."),
        field("status", pa.string(), "ESPN status name."),
        field("status_detail", pa.string(), "Short status text, e.g. FT."),
        field("completed", pa.bool_(), "Whether the match is finished."),
        field("home_team_id", pa.int32(), "Home team ESPN identifier (opaque integer)."),
        field("home_team_name", pa.string(), "Home side display name, e.g. Manchester United."),
        field("home_score", pa.int32(), "Number of goals scored by the home side."),
        field("home_formation", pa.string(), "Home starting formation, e.g. 4-2-3-1."),
        field("home_record", pa.string(), "Home team's W-D-L record after the match."),
        field("away_team_id", pa.int32(), "Away team ESPN identifier (opaque integer)."),
        field("away_team_name", pa.string(), "Away side display name, e.g. Aston Villa."),
        field("away_score", pa.int32(), "Number of goals scored by the away side."),
        field("away_formation", pa.string(), "Away starting formation."),
        field("away_record", pa.string(), "Away team's W-D-L record after the match."),
        field("venue_name", pa.string(), "Stadium name."),
        field("venue_city", pa.string(), "Stadium city."),
        field("attendance", pa.int32(), "Number of spectators reported (null when unknown)."),
        field("neutral_site", pa.bool_(), "Whether the match was at a neutral venue."),
    ]
)

# ESPN box-score stat name -> column. Percentages ESPN rounds to one decimal
# (pass %, shot %) are omitted; compute them from the exact counts instead.
_TEAM_STATS = {
    "possessionPct": "possession_pct",
    "totalShots": "shots",
    "shotsOnTarget": "shots_on_target",
    "blockedShots": "blocked_shots",
    "wonCorners": "corners",
    "offsides": "offsides",
    "foulsCommitted": "fouls",
    "yellowCards": "yellow_cards",
    "redCards": "red_cards",
    "saves": "saves",
    "totalPasses": "passes",
    "accuratePasses": "accurate_passes",
    "totalCrosses": "crosses",
    "accurateCrosses": "accurate_crosses",
    "totalLongBalls": "long_balls",
    "accurateLongBalls": "accurate_long_balls",
    "totalTackles": "tackles",
    "effectiveTackles": "effective_tackles",
    "interceptions": "interceptions",
    "totalClearance": "clearances",
    "effectiveClearance": "effective_clearances",
    "penaltyKickShots": "penalties_taken",
    "penaltyKickGoals": "penalty_goals",
}

TEAM_STATS_SCHEMA = pa.schema(
    [
        _EVENT_ID,
        field("team_id", pa.int32(), "ESPN team identifier (opaque integer).", nullable=False),
        field("team_name", pa.string(), "Club or national team display name."),
        field("home_away", pa.string(), "home or away."),
        field("possession_pct", pa.decimal128(4, 1), "Ball possession in percent (both sides sum to 100)."),
        *[
            field(column, pa.int32(), "Number of " + column.replace("_", " ") + ".")
            for column in list(_TEAM_STATS.values())[1:]
        ],
    ]
)

_PLAYER_STATS = {
    "totalGoals": "goals",
    "goalAssists": "assists",
    "totalShots": "shots",
    "shotsOnTarget": "shots_on_target",
    "foulsCommitted": "fouls_committed",
    "foulsSuffered": "fouls_suffered",
    "offsides": "offsides",
    "yellowCards": "yellow_cards",
    "redCards": "red_cards",
    "ownGoals": "own_goals",
    "saves": "saves",
    "goalsConceded": "goals_conceded",
    "shotsFaced": "shots_faced",
}

PLAYER_MATCH_SCHEMA = pa.schema(
    [
        _EVENT_ID,
        field("team_id", pa.int32(), "ESPN team identifier (opaque integer)."),
        field("team_name", pa.string(), "Club or national team display name."),
        field("home_away", pa.string(), "home or away."),
        field("athlete_id", pa.int64(), "ESPN player identifier (opaque integer).", nullable=False),
        field("player_name", pa.string(), "Player display name, e.g. Harry Kane."),
        field("jersey", pa.string(), "Shirt number."),
        field("position", pa.string(), "Position played."),
        field("position_abbreviation", pa.string(), "Position code."),
        field("starter", pa.bool_(), "Started the match."),
        field("subbed_in", pa.bool_(), "Came on as a substitute."),
        field("subbed_out", pa.bool_(), "Was substituted off."),
        field("formation_place", pa.int32(), "Formation slot index (1 = goalkeeper; 0 for substitutes)."),
        *[
            field(column, pa.int32(), "Number of " + column.replace("_", " ") + ".")
            for column in _PLAYER_STATS.values()
        ],
    ]
)

KEY_EVENTS_SCHEMA = pa.schema(
    [
        _EVENT_ID,
        field("sequence", pa.int32(), "Order within the match (1 = first).", nullable=False),
        field("key_event_id", pa.int64(), "ESPN play identifier (opaque integer)."),
        field("event_type", pa.string(), "Type slug, e.g. goal, yellow-card, substitution."),
        field("event_type_text", pa.string(), "Type label, e.g. Goal."),
        field("period", pa.int32(), "Match period number (1-2 halves, 3-4 extra time, 5 shoot-out)."),
        field("clock_seconds", pa.int32(), "Match clock in seconds since kick-off."),
        field("clock_display", pa.string(), "Displayed minute, e.g. 45'+2'."),
        field("scoring_play", pa.bool_(), "Whether a goal was scored."),
        field("team_id", pa.int32(), "Team ESPN identifier (opaque integer)."),
        field("team_name", pa.string(), "Club or national team display name."),
        field(
            "athlete_id",
            pa.int64(),
            "ESPN identifier of the primary player (scorer, booked player, or incoming substitute).",
        ),
        field("player_name", pa.string(), "Primary player name."),
        field(
            "secondary_athlete_id",
            pa.int64(),
            "ESPN identifier of the second player (assister or outgoing substitute).",
        ),
        field("secondary_player_name", pa.string(), "Second player name."),
        field("text", pa.string(), "ESPN description."),
        field("wallclock", TIMESTAMP, "Real-world UTC time of the event."),
    ]
)

COMMENTARY_SCHEMA = pa.schema(
    [
        _EVENT_ID,
        field("sequence", pa.int32(), "Order within the commentary (0 = first line).", nullable=False),
        field("clock_seconds", pa.int32(), "Match clock in seconds since kick-off."),
        field("clock_display", pa.string(), "Displayed minute."),
        field("text", pa.string(), "Commentary text."),
        field(
            "play_id",
            pa.int64(),
            "Linked ESPN play identifier (opaque integer), when the line describes a play.",
        ),
        field("play_type", pa.string(), "Linked play type slug."),
    ]
)

PLAYS_SCHEMA = pa.schema(
    [
        _EVENT_ID,
        field("sequence", pa.int32(), "Order within the match (1 = first).", nullable=False),
        field("play_id", pa.int64(), "ESPN play identifier (opaque integer)."),
        field("play_type", pa.string(), "Type slug, e.g. pass, shot-on-target, goal."),
        field("play_type_text", pa.string(), "Type label."),
        field("period", pa.int32(), "Match period number (1-2 halves, 3-4 extra time, 5 shoot-out)."),
        field("clock_seconds", pa.int32(), "Match clock in seconds since kick-off."),
        field("clock_display", pa.string(), "Displayed minute."),
        field("team_id", pa.int32(), "ESPN identifier of the acting team (opaque integer)."),
        field("athlete_id", pa.int64(), "ESPN identifier of the first participant (opaque integer)."),
        field("participant_role", pa.string(), "First participant's role, e.g. shooter."),
        field("home_score", pa.int32(), "Number of home goals after the play."),
        field("away_score", pa.int32(), "Number of away goals after the play."),
        field("scoring_play", pa.bool_(), "Whether a goal was scored."),
        field(
            "expected_goals",
            pa.float64(),
            "Expected goals (probability 0-1) of the shot, when the play is a shot.",
        ),
        field(
            "expected_goals_on_target",
            pa.float64(),
            "Post-shot expected goals (probability 0-1) for on-target shots.",
        ),
        field(
            "field_x", pa.float64(), "Start x coordinate in percent of pitch length (0-100, attacking right)."
        ),
        field("field_y", pa.float64(), "Start y coordinate in percent of pitch width (0-100)."),
        field("text", pa.string(), "ESPN description."),
        field("wallclock", TIMESTAMP, "Real-world UTC time of the play."),
    ]
)


def _clock(value: Any) -> tuple[int | None, str | None]:
    clock = mapping(value)
    seconds = to_float(clock.get("value"))
    return (int(seconds) if seconds is not None else None), to_text(clock.get("displayValue"))


def _header(payload: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    header = mapping(mapping(payload).get("header"))
    competitions = sequence(header.get("competitions"))
    return dict(header), dict(mapping(competitions[0] if competitions else {}))


def summary_event_id(payload: Any) -> int | None:
    """Return the match id an ESPN summary describes."""
    header, competition = _header(payload)
    return to_int(header.get("id") or competition.get("id"))


def _formations(payload: Any) -> dict[str, str | None]:
    return {
        str(mapping(roster).get("homeAway")): to_text(mapping(roster).get("formation"))
        for roster in sequence(mapping(payload).get("rosters"))
    }


def flatten_summary(payload: Any, event_id: int) -> list[dict[str, Any]]:
    """One row describing the match."""
    header, competition = _header(payload)
    if not competition:
        return []
    league = mapping(header.get("league"))
    competitors = sequence(competition.get("competitors"))
    sides = {str(mapping(value).get("homeAway")): mapping(value) for value in competitors}
    home, away = sides.get("home", {}), sides.get("away", {})
    status = mapping(mapping(competition.get("status")).get("type"))
    info = mapping(mapping(payload).get("gameInfo"))
    venue = mapping(info.get("venue"))
    formations = _formations(payload)

    def record(side: Any) -> str | None:
        for value in sequence(mapping(side).get("record")):
            if mapping(value).get("type") == "total":
                return to_text(mapping(value).get("summary"))
        return None

    pre = status.get("state") == "pre"
    return [
        {
            "event_id": event_id,
            "league_slug": to_text(league.get("slug")),
            "league_name": to_text(league.get("name")),
            "season": to_int(mapping(header.get("season")).get("year")),
            "kickoff": to_timestamp(competition.get("date")),
            "state": to_text(status.get("state")),
            "status": to_text(status.get("name")),
            "status_detail": to_text(status.get("shortDetail")),
            "completed": to_bool(status.get("completed")),
            "home_team_id": to_int(mapping(home.get("team")).get("id")),
            "home_team_name": to_text(mapping(home.get("team")).get("displayName")),
            "home_score": None if pre else to_int(home.get("score")),
            "home_formation": formations.get("home"),
            "home_record": record(home),
            "away_team_id": to_int(mapping(away.get("team")).get("id")),
            "away_team_name": to_text(mapping(away.get("team")).get("displayName")),
            "away_score": None if pre else to_int(away.get("score")),
            "away_formation": formations.get("away"),
            "away_record": record(away),
            "venue_name": to_text(venue.get("fullName")),
            "venue_city": to_text(mapping(venue.get("address")).get("city")),
            "attendance": to_int(info.get("attendance")) or None,
            "neutral_site": to_bool(competition.get("neutralSite")),
        }
    ]


def flatten_team_stats(payload: Any, event_id: int) -> list[dict[str, Any]]:
    """One row per team with the match box score."""
    rows: list[dict[str, Any]] = []
    for team_box in sequence(mapping(mapping(payload).get("boxscore")).get("teams")):
        team_box = mapping(team_box)
        team = mapping(team_box.get("team"))
        team_id = to_int(team.get("id"))
        if team_id is None:
            continue
        row: dict[str, Any] = {
            "event_id": event_id,
            "team_id": team_id,
            "team_name": to_text(team.get("displayName")),
            "home_away": to_text(team_box.get("homeAway")),
        }
        for stat in sequence(team_box.get("statistics")):
            stat = mapping(stat)
            column = _TEAM_STATS.get(str(stat.get("name")))
            if column is None:
                continue
            raw = stat.get("displayValue", stat.get("value"))
            row[column] = to_decimal(raw) if column == "possession_pct" else to_int(raw)
        rows.append(row)
    return rows


def flatten_player_match_stats(payload: Any, event_id: int) -> list[dict[str, Any]]:
    """One row per player in either match-day squad."""
    rows: list[dict[str, Any]] = []
    for roster in sequence(mapping(payload).get("rosters")):
        roster = mapping(roster)
        team = mapping(roster.get("team"))
        for player in sequence(roster.get("roster")):
            player = mapping(player)
            athlete = mapping(player.get("athlete"))
            athlete_id = to_int(athlete.get("id"))
            if athlete_id is None:
                continue
            position = mapping(player.get("position"))
            row: dict[str, Any] = {
                "event_id": event_id,
                "team_id": to_int(team.get("id")),
                "team_name": to_text(team.get("displayName")),
                "home_away": to_text(roster.get("homeAway")),
                "athlete_id": athlete_id,
                "player_name": to_text(athlete.get("displayName")),
                "jersey": to_text(player.get("jersey")),
                "position": to_text(position.get("displayName") or position.get("name")),
                "position_abbreviation": to_text(position.get("abbreviation")),
                "starter": to_bool(player.get("starter")),
                "subbed_in": to_bool(player.get("subbedIn")),
                "subbed_out": to_bool(player.get("subbedOut")),
                "formation_place": to_int(player.get("formationPlace")),
            }
            for stat in sequence(player.get("stats")):
                stat = mapping(stat)
                column = _PLAYER_STATS.get(str(stat.get("name")))
                if column is not None:
                    row[column] = to_int(stat.get("value", stat.get("displayValue")))
            rows.append(row)
    return rows


def _participant(play: Any, index: int) -> tuple[int | None, str | None]:
    participants = sequence(mapping(play).get("participants"))
    if len(participants) <= index:
        return None, None
    athlete = mapping(mapping(participants[index]).get("athlete"))
    return to_int(athlete.get("id")), to_text(athlete.get("displayName"))


def flatten_key_events(payload: Any, event_id: int) -> list[dict[str, Any]]:
    """One row per key event: goals, cards, substitutions, and period markers."""
    rows: list[dict[str, Any]] = []
    for index, event in enumerate(sequence(mapping(payload).get("keyEvents")), start=1):
        event = mapping(event)
        kind = mapping(event.get("type"))
        team = mapping(event.get("team"))
        seconds, display = _clock(event.get("clock"))
        primary_id, primary_name = _participant(event, 0)
        secondary_id, secondary_name = _participant(event, 1)
        rows.append(
            {
                "event_id": event_id,
                "sequence": index,
                "key_event_id": to_int(event.get("id")),
                "event_type": to_text(kind.get("type")),
                "event_type_text": to_text(kind.get("text")),
                "period": to_int(mapping(event.get("period")).get("number")),
                "clock_seconds": seconds,
                "clock_display": display,
                "scoring_play": to_bool(event.get("scoringPlay")),
                "team_id": to_int(team.get("id")),
                "team_name": to_text(team.get("displayName")),
                "athlete_id": primary_id,
                "player_name": primary_name,
                "secondary_athlete_id": secondary_id,
                "secondary_player_name": secondary_name,
                "text": to_text(event.get("text")),
                "wallclock": to_timestamp(event.get("wallclock")),
            }
        )
    return rows


def flatten_commentary(payload: Any, event_id: int) -> list[dict[str, Any]]:
    """One row per line of ESPN's text commentary."""
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(sequence(mapping(payload).get("commentary"))):
        line = mapping(line)
        play = mapping(line.get("play"))
        seconds, display = _clock(line.get("time"))
        sequence_number = to_int(line.get("sequence"))
        rows.append(
            {
                "event_id": event_id,
                "sequence": sequence_number if sequence_number is not None else index,
                "clock_seconds": seconds,
                "clock_display": display,
                "text": to_text(line.get("text")),
                "play_id": to_int(play.get("id")),
                "play_type": to_text(mapping(play.get("type")).get("type")),
            }
        )
    return rows


def flatten_plays(items: Any, event_id: int) -> list[dict[str, Any]]:
    """One row per play-by-play action, including ESPN's shot xG where supplied."""
    rows: list[dict[str, Any]] = []
    for index, play in enumerate(sequence(items), start=1):
        play = mapping(play)
        kind = mapping(play.get("type"))
        seconds, display = _clock(play.get("clock"))
        participants = sequence(play.get("participants"))
        first = mapping(participants[0]) if participants else {}
        rows.append(
            {
                "event_id": event_id,
                "sequence": index,
                "play_id": to_int(play.get("id")),
                "play_type": to_text(kind.get("type")),
                "play_type_text": to_text(kind.get("text")),
                "period": to_int(mapping(play.get("period")).get("number")),
                "clock_seconds": seconds,
                "clock_display": display,
                "team_id": ref_id(play.get("team"), "teams"),
                "athlete_id": ref_id(first.get("athlete"), "athletes"),
                "participant_role": to_text(first.get("type")),
                "home_score": to_int(play.get("homeScore")),
                "away_score": to_int(play.get("awayScore")),
                "scoring_play": to_bool(play.get("scoringPlay")),
                "expected_goals": to_float(play.get("expectedGoals")),
                "expected_goals_on_target": to_float(play.get("expectedGoalsOnTarget")),
                "field_x": to_float(play.get("fieldPositionX")),
                "field_y": to_float(play.get("fieldPositionY")),
                "text": to_text(play.get("text")),
                "wallclock": to_timestamp(play.get("wallclock")),
            }
        )
    return rows
