"""VGI table functions for teams, squads, leaderboards, and player season statistics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, ClassVar

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
    LEAGUE_DOC,
    MAJOR_LEAGUES,
    Sized,
    emit,
    function_examples,
    function_tags,
    gather,
    id_arg,
    league_arg,
    require_single_league,
    season_arg,
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


@dataclass(kw_only=True)
class TeamsArgs:
    """Arguments accepted by ``teams``."""

    league: Annotated[str, league_arg()]


_TEAMS_EXAMPLES = [
    (
        "La Liga clubs and their ESPN ids.",
        "SELECT team_id, team_name, abbreviation FROM soccer.main.teams(league := 'esp.1') "
        "ORDER BY team_name",
    )
]


@init_single_worker
@bind_fixed_schema
class TeamsFunction(Sized, TableFunctionGenerator[TeamsArgs]):
    """Teams registered in a competition this season."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = TEAMS_SCHEMA
    ESTIMATE = 20
    MAXIMUM = 400

    class Meta:
        """Function discovery metadata."""

        name = "teams"
        description = "Teams in a competition, with their ESPN team ids"
        categories = ["soccer", "teams"]
        projection_pushdown = True
        tags = function_tags(
            provider="espn",
            category="teams",
            title="Competition Teams",
            llm=(
                "One row per club or national team in a league (default eng.1) with team_id, the key for "
                "roster() and team_schedule()."
            ),
            schema=TEAMS_SCHEMA,
            examples=_TEAMS_EXAMPLES,
        )
        examples = function_examples(_TEAMS_EXAMPLES)

    @classmethod
    def process(cls, params: ProcessParams[TeamsArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit the team list."""
        league = require_single_league(params.args.league)
        response = api.fetch_teams(league)
        emit(out, flatten_teams(response.payload, league), params.output_schema, response.max_age)


@dataclass(kw_only=True)
class RosterArgs:
    """Arguments accepted by ``roster``."""

    team_id: Annotated[int, id_arg(0, "ESPN team id, from soccer.main.teams() or standings().")]
    league: Annotated[str, league_arg()]


_ROSTER_EXAMPLES = [
    (
        "Manchester United's (team 360) current squad by position.",
        "SELECT position, jersey, player_name, age, citizenship "
        "FROM soccer.main.roster(360, league := 'eng.1') ORDER BY position, player_name",
    )
]


@init_single_worker
@bind_fixed_schema
class RosterFunction(Sized, TableFunctionGenerator[RosterArgs]):
    """A team's current squad."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = ROSTER_SCHEMA
    ESTIMATE = 30
    MAXIMUM = 100

    class Meta:
        """Function discovery metadata."""

        name = "roster"
        description = "A team's current squad with positions, ages and nationalities"
        categories = ["soccer", "teams", "players"]
        projection_pushdown = True
        tags = function_tags(
            provider="espn",
            category="teams",
            title="Team Squad",
            llm=(
                "Current squad for one team (positional team_id) in a league: athlete_id, shirt number, "
                "position, age, birth date, nationality, height (in), weight (lb), injury status. "
                "athlete_id feeds player_stats()."
            ),
            schema=ROSTER_SCHEMA,
            examples=_ROSTER_EXAMPLES,
        )
        examples = function_examples(_ROSTER_EXAMPLES)

    @classmethod
    def process(cls, params: ProcessParams[RosterArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit the squad."""
        args = params.args
        league = require_single_league(args.league)
        response = api.fetch_roster(league, args.team_id)
        emit(
            out,
            flatten_roster(response.payload, league, args.team_id),
            params.output_schema,
            response.max_age,
        )


@dataclass(kw_only=True)
class LeadersArgs:
    """Arguments accepted by ``stat_leaders``."""

    league: Annotated[str, league_arg()]
    season: Annotated[int | None, season_arg()]


_LEADERS_EXAMPLES = [
    (
        "The 2015-16 Premier League top scorers.",
        "SELECT rank, player_name, team_name, goals, matches "
        "FROM soccer.main.stat_leaders(league := 'eng.1', season := 2015) "
        "WHERE category = 'goals' ORDER BY rank LIMIT 10",
    )
]


def _leaders(league: str, season: int | None) -> tuple[list[dict], int]:
    response = api.fetch_statistics(league, season)
    return flatten_leaders(response.payload, league, season), response.max_age


@init_single_worker
@bind_fixed_schema
class StatLeadersFunction(Sized, TableFunctionGenerator[LeadersArgs]):
    """Top scorers and assist leaders for a competition season."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = LEADERS_SCHEMA
    ESTIMATE = 100
    MAXIMUM = 200

    class Meta:
        """Function discovery metadata."""

        name = "stat_leaders"
        description = "Goals and assists leaderboards for a competition season"
        categories = ["soccer", "players", "leaders"]
        projection_pushdown = True
        tags = function_tags(
            provider="espn",
            category="player-stats",
            title="Scoring And Assist Leaders",
            llm=(
                "ESPN's top-50 goals and assists leaderboards: filter category = 'goals' or 'assists' "
                "and order by rank. Each row also carries the player's matches, goals and assists. "
                "season is the start year (2015 = 2015-16); NULL = current."
            ),
            schema=LEADERS_SCHEMA,
            examples=_LEADERS_EXAMPLES,
        )
        examples = function_examples(_LEADERS_EXAMPLES)

    @classmethod
    def process(cls, params: ProcessParams[LeadersArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit both leaderboards."""
        args = params.args
        rows, max_age = _leaders(require_single_league(args.league), args.season)
        emit(out, rows, params.output_schema, max_age)


_CURRENT_LEADERS_EXAMPLES = [
    (
        "Current top scorer in each big-five league.",
        "SELECT league_slug, player_name, team_name, goals FROM soccer.main.all_current_stat_leaders() "
        "WHERE category = 'goals' AND rank = 1 ORDER BY league_slug",
    )
]


@init_single_worker
@bind_fixed_schema
class CurrentStatLeadersFunction(Sized, TableFunctionGenerator[None]):
    """Current big-five goals and assists leaders (scan behind ``current_stat_leaders``)."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = LEADERS_SCHEMA
    ESTIMATE = 500
    MAXIMUM = 1_000

    class Meta:
        """Function discovery metadata."""

        name = "all_current_stat_leaders"
        description = "Current goals and assists leaders in the big-five European leagues"
        categories = ["soccer", "players", "leaders"]
        projection_pushdown = True
        tags = function_tags(
            provider="espn",
            category="player-stats",
            title="Current Big-Five Leaders Scan",
            llm=(
                "The scan behind current_stat_leaders: current-season goals and assists boards for "
                "eng.1, esp.1, ger.1, ita.1 and fra.1. Prefer the table."
            ),
            schema=LEADERS_SCHEMA,
            examples=_CURRENT_LEADERS_EXAMPLES,
        )
        examples = function_examples(_CURRENT_LEADERS_EXAMPLES)

    @classmethod
    def process(cls, params: ProcessParams[None], state: None, out: OutputCollector) -> None:
        """Fetch and emit the five current leaderboards."""
        rows, max_age = gather([lambda league=league: _leaders(league, None) for league in MAJOR_LEAGUES])
        emit(out, rows, params.output_schema, max_age)


@dataclass(kw_only=True)
class PlayerStatsArgs:
    """Arguments accepted by ``player_stats``."""

    athlete_id: Annotated[int, id_arg(0, "ESPN player id, from roster(), stat_leaders() or match data.")]
    league: Annotated[
        str | None,
        Arg(
            "league",
            default=None,
            arrow_type=pa.string(),
            pattern=api.LEAGUE_PATTERN,
            doc="Competition to report; NULL selects the player's main league. " + LEAGUE_DOC,
        ),
    ]


_PLAYER_EXAMPLES = [
    (
        "Erling Haaland's (athlete 253989) Premier League seasons.",
        "SELECT season, team_name, starts, goals, assists, shots_on_target "
        "FROM soccer.main.player_stats(253989, league := 'eng.1') ORDER BY season",
    )
]


@init_single_worker
@bind_fixed_schema
class PlayerStatsFunction(Sized, TableFunctionGenerator[PlayerStatsArgs]):
    """One player's season-by-season totals in a competition."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = PLAYER_STATS_SCHEMA
    ESTIMATE = 5
    MAXIMUM = 50

    class Meta:
        """Function discovery metadata."""

        name = "player_stats"
        description = "One player's recent season totals in a competition"
        categories = ["soccer", "players"]
        projection_pushdown = True
        tags = function_tags(
            provider="espn",
            category="player-stats",
            title="Player Season Statistics",
            llm=(
                "Season lines for one player (positional athlete_id) in one competition, one row per "
                "season and team: starts, goals, assists, shots, cards, plus clean sheets, saves and "
                "goals conceded for goalkeepers. ESPN returns about the last five seasons. league NULL "
                "= the player's main league; pass uefa.champions etc. for others."
            ),
            schema=PLAYER_STATS_SCHEMA,
            examples=_PLAYER_EXAMPLES,
        )
        examples = function_examples(_PLAYER_EXAMPLES)

    @classmethod
    def process(cls, params: ProcessParams[PlayerStatsArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit the player's season lines."""
        args = params.args
        if args.league is not None:
            require_single_league(args.league)
        response = api.fetch_athlete_stats(args.athlete_id, args.league)
        emit(
            out,
            flatten_player_stats(response.payload, args.athlete_id),
            params.output_schema,
            response.max_age,
        )


FUNCTIONS = [
    TeamsFunction,
    RosterFunction,
    StatLeadersFunction,
    CurrentStatLeadersFunction,
    PlayerStatsFunction,
]
