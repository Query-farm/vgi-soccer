"""VGI table functions for the league directory and league tables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, ClassVar

import pyarrow as pa
from vgi.table_function import (
    ProcessParams,
    TableFunctionGenerator,
    bind_fixed_schema,
    init_single_worker,
)
from vgi_rpc.rpc import OutputCollector

from vgi_soccer import api
from vgi_soccer.common import (
    MAJOR_LEAGUES,
    Sized,
    emit,
    function_examples,
    function_tags,
    gather,
    league_arg,
    require_single_league,
    season_arg,
)
from vgi_soccer.league_schemas import (
    LEAGUES_SCHEMA,
    STANDINGS_SCHEMA,
    flatten_leagues,
    flatten_standings,
)


def _standings(league: str, season: int | None) -> tuple[list[dict], int]:
    response = api.fetch_standings(league, season)
    return flatten_standings(response.payload, league), response.max_age


_LEAGUES_EXAMPLES = [
    (
        "Find the slug for any competition by name.",
        "SELECT league_slug, league_name FROM soccer.main.all_leagues() "
        "WHERE league_name ILIKE '%champions%' ORDER BY league_slug",
    )
]


@init_single_worker
@bind_fixed_schema
class LeaguesFunction(Sized, TableFunctionGenerator[None]):
    """ESPN's soccer league directory (scan behind the ``leagues`` table)."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = LEAGUES_SCHEMA
    ESTIMATE = 220
    MAXIMUM = 600

    class Meta:
        """Function discovery metadata."""

        name = "all_leagues"
        description = "Every soccer competition ESPN covers (scan behind the leagues table)"
        categories = ["soccer", "leagues"]
        projection_pushdown = True
        tags = function_tags(
            provider="espn",
            category="leagues",
            title="Soccer League Directory Scan",
            llm=(
                "The scan behind the leagues table: about 220 competitions with the league_slug every "
                "other function's league argument takes. Prefer the leagues table."
            ),
            schema=LEAGUES_SCHEMA,
            examples=_LEAGUES_EXAMPLES,
        )
        examples = function_examples(_LEAGUES_EXAMPLES)

    @classmethod
    def process(cls, params: ProcessParams[None], state: None, out: OutputCollector) -> None:
        """Fetch and emit the league directory."""
        response = api.fetch_leagues()
        emit(out, flatten_leagues(response.payload), params.output_schema, response.max_age)


@dataclass(kw_only=True)
class StandingsArgs:
    """Arguments accepted by ``standings``."""

    league: Annotated[str, league_arg()]
    season: Annotated[int | None, season_arg()]


_STANDINGS_EXAMPLES = [
    (
        "Leicester City's 2015-16 title-winning Premier League table.",
        "SELECT rank, team_name, wins, draws, losses, goal_difference, points "
        "FROM soccer.main.standings(league := 'eng.1', season := 2015) ORDER BY rank",
    ),
    (
        "The current Champions League league-phase table.",
        "SELECT rank, team_name, points, qualification "
        "FROM soccer.main.standings(league := 'uefa.champions') ORDER BY rank",
    ),
]


@init_single_worker
@bind_fixed_schema
class StandingsFunction(Sized, TableFunctionGenerator[StandingsArgs]):
    """A league table for any ESPN competition and season."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = STANDINGS_SCHEMA
    ESTIMATE = 20
    MAXIMUM = 200

    class Meta:
        """Function discovery metadata."""

        name = "standings"
        description = "League table for a competition and season"
        categories = ["soccer", "standings"]
        projection_pushdown = True
        tags = function_tags(
            provider="espn",
            category="standings",
            title="League Standings",
            llm=(
                "One row per team per table or group: rank, played, W/D/L, goals for/against, goal "
                "difference, points, and the qualification or relegation zone. league defaults to "
                "eng.1; season is the START year (2015 = 2015-16) and NULL means current. Group "
                "tournaments (fifa.world, uefa.euro) return one table per group_name. Cups without a "
                "table (eng.fa) return no rows."
            ),
            md=(
                "League tables from ESPN back to roughly 2002. All arguments are named. "
                "`season` is the season start year. Group-stage competitions return several "
                "tables distinguished by `group_name`; knockout cups return an empty result."
            ),
            schema=STANDINGS_SCHEMA,
            examples=_STANDINGS_EXAMPLES,
        )
        examples = function_examples(_STANDINGS_EXAMPLES)

    @classmethod
    def process(cls, params: ProcessParams[StandingsArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit the requested table."""
        args = params.args
        rows, max_age = _standings(require_single_league(args.league), args.season)
        emit(out, rows, params.output_schema, max_age)


_CURRENT_EXAMPLES = [
    (
        "Current leaders of the big-five European leagues.",
        "SELECT league_name, team_name, points FROM soccer.main.all_current_standings() "
        "WHERE rank = 1 ORDER BY league_slug",
    )
]


@init_single_worker
@bind_fixed_schema
class CurrentStandingsFunction(Sized, TableFunctionGenerator[None]):
    """Current big-five league tables (scan behind ``current_standings``)."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = STANDINGS_SCHEMA
    ESTIMATE = 96
    MAXIMUM = 120

    class Meta:
        """Function discovery metadata."""

        name = "all_current_standings"
        description = "Current Premier League, La Liga, Bundesliga, Serie A and Ligue 1 tables"
        categories = ["soccer", "standings"]
        projection_pushdown = True
        tags = function_tags(
            provider="espn",
            category="standings",
            title="Current Big-Five Standings Scan",
            llm=(
                "The scan behind current_standings: current tables for eng.1, esp.1, ger.1, ita.1 and "
                "fra.1. Prefer the table; use standings() for other leagues or past seasons."
            ),
            schema=STANDINGS_SCHEMA,
            examples=_CURRENT_EXAMPLES,
        )
        examples = function_examples(_CURRENT_EXAMPLES)

    @classmethod
    def process(cls, params: ProcessParams[None], state: None, out: OutputCollector) -> None:
        """Fetch and emit the five current tables."""
        rows, max_age = gather([lambda league=league: _standings(league, None) for league in MAJOR_LEAGUES])
        emit(out, rows, params.output_schema, max_age)


FUNCTIONS = [LeaguesFunction, StandingsFunction, CurrentStandingsFunction]
