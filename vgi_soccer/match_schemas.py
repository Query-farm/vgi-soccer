"""Arrow schema and flattening for fixtures and results (scoreboards and schedules)."""

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
    to_int,
    to_text,
    to_timestamp,
)

MATCH_SCHEMA = pa.schema(
    [
        field(
            "event_id",
            pa.int64(),
            "ESPN match identifier (opaque integer); pass it to the match_* functions.",
            nullable=False,
        ),
        field("league_slug", pa.string(), "ESPN league slug, e.g. eng.1."),
        field("league_name", pa.string(), "Competition name."),
        field("season", pa.int32(), "Season start year (2025 = 2025-26)."),
        field("kickoff", TIMESTAMP, "Scheduled kick-off time in UTC."),
        field("match_name", pa.string(), "Fixture label, e.g. Arsenal at Liverpool."),
        field("state", pa.string(), "pre (scheduled), in (live), or post (finished)."),
        field("status", pa.string(), "ESPN status, e.g. STATUS_FULL_TIME or STATUS_POSTPONED."),
        field("status_detail", pa.string(), "Short status text, e.g. FT or 63'."),
        field("completed", pa.bool_(), "Whether the match is finished."),
        field("home_team_id", pa.int32(), "Home team ESPN identifier (opaque integer)."),
        field("home_team_name", pa.string(), "Home side display name, e.g. Manchester United."),
        field("home_team_abbreviation", pa.string(), "Home side three-letter code, e.g. MAN."),
        field("home_score", pa.int32(), "Number of goals scored by the home side; null before kick-off."),
        field("away_team_id", pa.int32(), "Away team ESPN identifier (opaque integer)."),
        field("away_team_name", pa.string(), "Away side display name, e.g. Aston Villa."),
        field("away_team_abbreviation", pa.string(), "Away side three-letter code, e.g. AVL."),
        field("away_score", pa.int32(), "Number of goals scored by the away side; null before kick-off."),
        field(
            "home_shootout_score",
            pa.int32(),
            "Number of home penalties scored in a shoot-out, when one was played.",
        ),
        field(
            "away_shootout_score",
            pa.int32(),
            "Number of away penalties scored in a shoot-out, when one was played.",
        ),
        field("winner", pa.string(), "home, away, or draw once finished; null otherwise."),
        field("venue_name", pa.string(), "Stadium name."),
        field("venue_city", pa.string(), "Stadium city."),
        field("venue_country", pa.string(), "Stadium country."),
        field("attendance", pa.int32(), "Number of spectators reported (null when unknown)."),
        field("note", pa.string(), "Round or stage note, e.g. League Phase."),
    ]
)

_LEAGUE_UID = re.compile(r"~l:(\d+)")


def league_uid_id(event: Any) -> int | None:
    """Return the ESPN numeric league id embedded in an event ``uid``."""
    uid = mapping(event).get("uid")
    match = _LEAGUE_UID.search(uid) if isinstance(uid, str) else None
    return int(match.group(1)) if match else None


def _score(competitor: Any) -> int | None:
    score = mapping(competitor).get("score")
    if isinstance(score, dict):
        return to_int(score.get("value", score.get("displayValue")))
    return to_int(score)


def _shootout(competitor: Any) -> int | None:
    value = mapping(competitor).get("shootoutScore")
    if isinstance(value, dict):
        return to_int(value.get("value"))
    return to_int(value)


def _side(competitors: list[Any], home_away: str) -> dict[str, Any]:
    return next(
        (mapping(value) for value in competitors if mapping(value).get("homeAway") == home_away),
        {},
    )


def flatten_events(
    events: Any,
    *,
    league: str | None,
    league_name: str | None = None,
    league_lookup: dict[int, tuple[str, str | None]] | None = None,
) -> list[dict[str, Any]]:
    """One row per match from an ESPN scoreboard or team schedule ``events`` array.

    ``league_lookup`` resolves each event's own league when the request spanned
    every competition (``league = 'all'``).
    """
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for event in sequence(events):
        event = mapping(event)
        event_id = to_int(event.get("id"))
        if event_id is None or event_id in seen:
            continue
        seen.add(event_id)
        competition = mapping(sequence(event.get("competitions"))[0] if event.get("competitions") else {})
        competitors = sequence(competition.get("competitors"))
        home, away = _side(competitors, "home"), _side(competitors, "away")
        home_team, away_team = mapping(home.get("team")), mapping(away.get("team"))
        status = mapping(competition.get("status") or event.get("status"))
        status_type = mapping(status.get("type"))
        completed = to_bool(status_type.get("completed"))
        home_score, away_score = _score(home), _score(away)
        winner = None
        if completed and home_score is not None and away_score is not None:
            if home.get("winner") is True:
                winner = "home"
            elif away.get("winner") is True:
                winner = "away"
            elif home_score == away_score:
                winner = "draw"
            else:
                winner = "home" if home_score > away_score else "away"
        venue = mapping(competition.get("venue") or event.get("venue"))
        address = mapping(venue.get("address"))
        event_league = mapping(event.get("league"))
        slug, name = league, league_name
        if event_league.get("slug"):
            slug, name = to_text(event_league.get("slug")), to_text(event_league.get("name"))
        elif league_lookup is not None:
            resolved = league_lookup.get(league_uid_id(event) or -1)
            if resolved is not None:
                slug, name = resolved
            elif league == "all":
                slug = None
        notes = [to_text(mapping(note).get("headline")) for note in sequence(competition.get("notes"))]
        note = next((value for value in notes if value), None) or to_text(competition.get("altGameNote"))
        rows.append(
            {
                "event_id": event_id,
                "league_slug": slug,
                "league_name": name,
                "season": to_int(mapping(event.get("season")).get("year")),
                "kickoff": to_timestamp(event.get("date") or competition.get("date")),
                "match_name": to_text(event.get("name")),
                "state": to_text(status_type.get("state")),
                "status": to_text(status_type.get("name")),
                "status_detail": to_text(status_type.get("shortDetail")),
                "completed": completed,
                "home_team_id": to_int(home_team.get("id") or home.get("id")),
                "home_team_name": to_text(home_team.get("displayName")),
                "home_team_abbreviation": to_text(home_team.get("abbreviation")),
                "home_score": home_score if status_type.get("state") != "pre" else None,
                "away_team_id": to_int(away_team.get("id") or away.get("id")),
                "away_team_name": to_text(away_team.get("displayName")),
                "away_team_abbreviation": to_text(away_team.get("abbreviation")),
                "away_score": away_score if status_type.get("state") != "pre" else None,
                "home_shootout_score": _shootout(home),
                "away_shootout_score": _shootout(away),
                "winner": winner,
                "venue_name": to_text(venue.get("fullName")),
                "venue_city": to_text(address.get("city")),
                "venue_country": to_text(address.get("country")),
                "attendance": to_int(competition.get("attendance")) or None,
                "note": note,
            }
        )
    return rows
