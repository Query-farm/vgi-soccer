"""VGI table functions for fixtures and results: scoreboards, season schedules, team schedules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, ClassVar

import pyarrow as pa
from vgi.arguments import Arg
from vgi.table_function import (
    ProcessParams,
    TableFunctionGenerator,
    bind_fixed_schema,
    init_single_worker,
)
from vgi_rpc.rpc import OutputCollector

from vgi_soccer import api
from vgi_soccer.common import (
    Sized,
    emit,
    function_examples,
    function_tags,
    id_arg,
    league_arg,
    require_single_league,
    season_arg,
)
from vgi_soccer.league_schemas import league_names
from vgi_soccer.match_schemas import MATCH_SCHEMA, flatten_events
from vgi_soccer.meta import mapping, sequence, to_int, to_text


def _league_name(payload: Any) -> str | None:
    leagues = sequence(mapping(payload).get("leagues"))
    return to_text(mapping(leagues[0]).get("name")) if leagues else None


def scoreboard_rows(league: str, dates: str | None) -> tuple[list[dict[str, Any]], int]:
    """Fetch one scoreboard window and flatten it, resolving leagues for ``all``."""
    response = api.fetch_scoreboard(league, dates)
    events = mapping(response.payload).get("events")
    if league != "all":
        return flatten_events(events, league=league, league_name=_league_name(response.payload)), (
            response.max_age
        )
    directory = api.fetch_leagues()
    rows = flatten_events(events, league="all", league_lookup=league_names(directory.payload))
    return rows, min(response.max_age, directory.max_age)


def current_season(league: str) -> int | None:
    """Return the season start year ESPN currently reports for a league."""
    response = api.fetch_scoreboard(league)
    leagues = sequence(mapping(response.payload).get("leagues"))
    return to_int(mapping(mapping(leagues[0]).get("season")).get("year")) if leagues else None


@dataclass(kw_only=True)
class ScoreboardArgs:
    """Arguments accepted by ``scoreboard``."""

    league: Annotated[
        str,
        league_arg(
            doc=(
                "ESPN league slug such as eng.1, or 'all' for every competition ESPN tracks that day. "
                "Slugs are listed in soccer.main.leagues."
            )
        ),
    ]
    match_date: Annotated[
        date | None,
        Arg(
            "match_date",
            default=None,
            arrow_type=pa.date32(),
            doc="Calendar day (US Eastern, as ESPN groups it). NULL selects ESPN's current match day.",
        ),
    ]


_SCOREBOARD_EXAMPLES = [
    (
        "Premier League results on 8 November 2026.",
        "SELECT kickoff, home_team_name, home_score, away_score, away_team_name, status_detail "
        "FROM soccer.main.scoreboard(league := 'eng.1', match_date := DATE '2026-11-08') ORDER BY kickoff",
    )
]


@init_single_worker
@bind_fixed_schema
class ScoreboardFunction(Sized, TableFunctionGenerator[ScoreboardArgs]):
    """Matches on one day for one competition, or for every competition."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = MATCH_SCHEMA
    ESTIMATE = 10
    MAXIMUM = 1_000

    class Meta:
        """Function discovery metadata."""

        name = "scoreboard"
        description = "Fixtures, live scores and results for one day"
        categories = ["soccer", "matches"]
        projection_pushdown = True
        tags = function_tags(
            provider="espn",
            category="matches",
            title="Daily Scoreboard",
            llm=(
                "One row per match on a calendar day: kick-off (UTC), state pre/in/post, score, winner "
                "(home/away/draw), venue and attendance. league defaults to eng.1; league := 'all' covers "
                "every competition. match_date NULL means today. Use event_id with match_summary(), "
                "match_key_events() and the other match_* functions."
            ),
            schema=MATCH_SCHEMA,
            examples=_SCOREBOARD_EXAMPLES,
        )
        examples = function_examples(_SCOREBOARD_EXAMPLES)

    @classmethod
    def process(cls, params: ProcessParams[ScoreboardArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit one day's matches."""
        args = params.args
        api.validate_league(args.league)
        dates = args.match_date.strftime("%Y%m%d") if args.match_date else None
        rows, max_age = scoreboard_rows(args.league, dates)
        emit(out, rows, params.output_schema, max_age)


_CURRENT_EXAMPLES = [
    (
        "Today's matches in every competition, with live and final scores.",
        "SELECT league_name, home_team_name, home_score, away_score, away_team_name, status_detail "
        "FROM soccer.main.all_current_matches() ORDER BY kickoff",
    )
]


@init_single_worker
@bind_fixed_schema
class CurrentMatchesFunction(Sized, TableFunctionGenerator[None]):
    """Today's matches across every competition (scan behind ``current_matches``)."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = MATCH_SCHEMA
    ESTIMATE = 60
    MAXIMUM = 1_000

    class Meta:
        """Function discovery metadata."""

        name = "all_current_matches"
        description = "Today's matches in every ESPN-covered competition"
        categories = ["soccer", "matches"]
        projection_pushdown = True
        tags = function_tags(
            provider="espn",
            category="matches",
            title="Current Scoreboard Scan",
            llm=(
                "The scan behind current_matches: today's matches across all competitions with "
                "league_slug resolved. Prefer the table; use scoreboard() for another day."
            ),
            schema=MATCH_SCHEMA,
            examples=_CURRENT_EXAMPLES,
        )
        examples = function_examples(_CURRENT_EXAMPLES)

    @classmethod
    def process(cls, params: ProcessParams[None], state: None, out: OutputCollector) -> None:
        """Fetch and emit today's matches."""
        rows, max_age = scoreboard_rows("all", None)
        emit(out, rows, params.output_schema, max_age)


@dataclass(kw_only=True)
class ScheduleArgs:
    """Arguments accepted by ``schedule``."""

    league: Annotated[str, league_arg()]
    season: Annotated[int | None, season_arg()]


_SCHEDULE_EXAMPLES = [
    (
        "Every 2025-26 Premier League match involving Arsenal.",
        "SELECT kickoff, home_team_name, home_score, away_score, away_team_name "
        "FROM soccer.main.schedule(league := 'eng.1', season := 2025) "
        "WHERE 'Arsenal' IN (home_team_name, away_team_name) ORDER BY kickoff",
    )
]


@init_single_worker
@bind_fixed_schema
class ScheduleFunction(Sized, TableFunctionGenerator[ScheduleArgs]):
    """A full competition season of fixtures and results."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = MATCH_SCHEMA
    ESTIMATE = 380
    MAXIMUM = 2_000

    class Meta:
        """Function discovery metadata."""

        name = "schedule"
        description = "Every fixture and result in one competition season"
        categories = ["soccer", "matches"]
        projection_pushdown = True
        tags = function_tags(
            provider="espn",
            category="matches",
            title="Season Schedule",
            llm=(
                "Every match of one competition season (one row per match, results and upcoming "
                "fixtures). season is the START year: 2025 = 2025-26, merged across both calendar "
                "years. NULL = current season. Filter on home_team_name/away_team_name for one club."
            ),
            schema=MATCH_SCHEMA,
            examples=_SCHEDULE_EXAMPLES,
        )
        examples = function_examples(_SCHEDULE_EXAMPLES)

    @classmethod
    def process(cls, params: ProcessParams[ScheduleArgs], state: None, out: OutputCollector) -> None:
        """Fetch both calendar years of a season and keep that season's matches."""
        league = require_single_league(params.args.league)
        season = params.args.season if params.args.season is not None else current_season(league)
        if season is None:
            emit(out, [], params.output_schema, None)
            return
        first, first_age = scoreboard_rows(league, str(season))
        second, second_age = scoreboard_rows(league, str(season + 1))
        rows: list[dict[str, Any]] = []
        seen: set[int] = set()
        for row in sorted(first + second, key=lambda value: (value["kickoff"] is None, value["kickoff"])):
            if row["season"] == season and row["event_id"] not in seen:
                seen.add(row["event_id"])
                rows.append(row)
        emit(out, rows, params.output_schema, min(first_age, second_age))


@dataclass(kw_only=True)
class TeamScheduleArgs:
    """Arguments accepted by ``team_schedule``."""

    team_id: Annotated[int, id_arg(0, "ESPN team id, from soccer.main.teams() or any standings row.")]
    league: Annotated[str, league_arg()]
    season: Annotated[int | None, season_arg()]


_TEAM_SCHEDULE_EXAMPLES = [
    (
        "Manchester United (team 360) results and fixtures this Premier League season.",
        "SELECT kickoff, home_team_name, home_score, away_score, away_team_name, state "
        "FROM soccer.main.team_schedule(360, league := 'eng.1') ORDER BY kickoff",
    )
]


@init_single_worker
@bind_fixed_schema
class TeamScheduleFunction(Sized, TableFunctionGenerator[TeamScheduleArgs]):
    """One team's results and remaining fixtures in a competition season."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = MATCH_SCHEMA
    ESTIMATE = 38
    MAXIMUM = 120

    class Meta:
        """Function discovery metadata."""

        name = "team_schedule"
        description = "One team's results and upcoming fixtures in a competition season"
        categories = ["soccer", "matches", "teams"]
        projection_pushdown = True
        tags = function_tags(
            provider="espn",
            category="matches",
            title="Team Schedule",
            llm=(
                "Results plus remaining fixtures for one team (positional ESPN team_id) in one league. "
                "league defaults to eng.1; season is the start year, NULL = current. Find team ids "
                "in teams() or standings()."
            ),
            schema=MATCH_SCHEMA,
            examples=_TEAM_SCHEDULE_EXAMPLES,
        )
        examples = function_examples(_TEAM_SCHEDULE_EXAMPLES)

    @classmethod
    def process(cls, params: ProcessParams[TeamScheduleArgs], state: None, out: OutputCollector) -> None:
        """Fetch results and fixtures and merge them chronologically."""
        args = params.args
        league = require_single_league(args.league)
        results = api.fetch_team_schedule(league, args.team_id, args.season)
        fixtures = api.fetch_team_schedule(league, args.team_id, args.season, fixtures=True)
        events = sequence(mapping(results.payload).get("events")) + sequence(
            mapping(fixtures.payload).get("events")
        )
        rows = flatten_events(events, league=league)
        rows.sort(key=lambda value: (value["kickoff"] is None, value["kickoff"]))
        emit(out, rows, params.output_schema, min(results.max_age, fixtures.max_age))


FUNCTIONS = [ScoreboardFunction, CurrentMatchesFunction, ScheduleFunction, TeamScheduleFunction]
