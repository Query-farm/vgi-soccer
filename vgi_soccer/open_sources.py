"""VGI table functions backed by open data: openfootball (CC0) and OpenLigaDB."""

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
from vgi_soccer.common import Sized, emit, function_examples, function_tags
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

#: Men's World Cup editions (none were held in 1942 or 1946).
WORLD_CUP_YEARS = tuple(year for year in range(1930, 2027, 4) if year not in (1942, 1946))
OPENLIGADB_LEAGUES = ("bl1", "bl2", "bl3", "fbl1", "dfb")


@dataclass(kw_only=True)
class WorldCupArgs:
    """Arguments accepted by the World Cup functions."""

    year: Annotated[
        int,
        Arg(
            0,
            arrow_type=pa.int32(),
            choices=WORLD_CUP_YEARS,
            doc="Men's FIFA World Cup year, 1930-2026 (no tournament in 1942 or 1946).",
        ),
    ]


_WC_MATCH_EXAMPLES = [
    (
        "The 2022 World Cup knockout rounds, including extra time and penalties.",
        "SELECT round, team1, team2, team1_goals, team2_goals, team1_extra_time, team2_extra_time, "
        "team1_penalties, team2_penalties, winner FROM soccer.main.world_cup_matches(2022) "
        "WHERE group_name IS NULL ORDER BY match_number",
    )
]


@init_single_worker
@bind_fixed_schema
class WorldCupMatchesFunction(Sized, TableFunctionGenerator[WorldCupArgs]):
    """Every match of one men's World Cup from openfootball."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = WORLD_CUP_MATCHES_SCHEMA
    ESTIMATE = 64
    MAXIMUM = 104

    class Meta:
        """Function discovery metadata."""

        name = "world_cup_matches"
        description = "Every match of one men's FIFA World Cup, 1930-2026 (openfootball, CC0)"
        categories = ["soccer", "world-cup", "history"]
        projection_pushdown = True
        tags = function_tags(
            provider="openfootball",
            category="history",
            title="World Cup Matches",
            llm=(
                "Results of every match at one men's World Cup (positional year). team1_goals/"
                "team2_goals are the 90-minute score; extra-time and shoot-out columns are filled only "
                "when played; winner resolves all three. group_name is null for knockout games."
            ),
            schema=WORLD_CUP_MATCHES_SCHEMA,
            examples=_WC_MATCH_EXAMPLES,
        )
        examples = function_examples(_WC_MATCH_EXAMPLES)

    @classmethod
    def process(cls, params: ProcessParams[WorldCupArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit one tournament's matches."""
        year = params.args.year
        response = api.fetch_world_cup(year)
        emit(out, flatten_world_cup_matches(response.payload, year), params.output_schema, response.max_age)


_WC_GOAL_EXAMPLES = [
    (
        "Top scorers of the 2022 World Cup, excluding own goals and shoot-outs.",
        "SELECT player_name, team, count(*) AS goals FROM soccer.main.world_cup_goals(2022) "
        "WHERE NOT own_goal GROUP BY ALL ORDER BY goals DESC LIMIT 10",
    )
]


@init_single_worker
@bind_fixed_schema
class WorldCupGoalsFunction(Sized, TableFunctionGenerator[WorldCupArgs]):
    """Every goal of one men's World Cup from openfootball."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = WORLD_CUP_GOALS_SCHEMA
    ESTIMATE = 170
    MAXIMUM = 400

    class Meta:
        """Function discovery metadata."""

        name = "world_cup_goals"
        description = "Every goal scored at one men's FIFA World Cup (openfootball, CC0)"
        categories = ["soccer", "world-cup", "history"]
        projection_pushdown = True
        tags = function_tags(
            provider="openfootball",
            category="history",
            title="World Cup Goals",
            llm=(
                "One row per goal (shoot-out kicks excluded) at one men's World Cup: scorer, team "
                "credited, minute with stoppage time split out, penalty and own_goal flags. Exclude "
                "own goals when ranking scorers."
            ),
            schema=WORLD_CUP_GOALS_SCHEMA,
            examples=_WC_GOAL_EXAMPLES,
        )
        examples = function_examples(_WC_GOAL_EXAMPLES)

    @classmethod
    def process(cls, params: ProcessParams[WorldCupArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit one tournament's goals."""
        year = params.args.year
        response = api.fetch_world_cup(year)
        emit(out, flatten_world_cup_goals(response.payload, year), params.output_schema, response.max_age)


_OLDB_LEAGUE_DOC = (
    "OpenLigaDB shortcut: bl1 Bundesliga, bl2 2. Bundesliga, bl3 3. Liga, fbl1 Frauen-Bundesliga, "
    "dfb DFB-Pokal."
)


@dataclass(kw_only=True)
class BundesligaTableArgs:
    """Arguments accepted by ``bundesliga_table``."""

    season: Annotated[int, Arg(0, arrow_type=pa.int32(), ge=2002, le=2100, doc="Season start year.")]
    league: Annotated[
        str,
        Arg(
            "league",
            default="bl1",
            arrow_type=pa.string(),
            choices=OPENLIGADB_LEAGUES[:4],
            doc=_OLDB_LEAGUE_DOC.replace(", dfb DFB-Pokal", ""),
        ),
    ]


_TABLE_EXAMPLES = [
    (
        "The 2025-26 Bundesliga table from OpenLigaDB.",
        "SELECT position, team_name, matches, wins, draws, losses, goal_difference, points "
        "FROM soccer.main.bundesliga_table(2025) ORDER BY position",
    )
]


@init_single_worker
@bind_fixed_schema
class BundesligaTableFunction(Sized, TableFunctionGenerator[BundesligaTableArgs]):
    """German league table from OpenLigaDB."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = BUNDESLIGA_TABLE_SCHEMA
    ESTIMATE = 18
    MAXIMUM = 24

    class Meta:
        """Function discovery metadata."""

        name = "bundesliga_table"
        description = "German league table from the OpenLigaDB community database"
        categories = ["soccer", "standings", "germany"]
        projection_pushdown = True
        tags = function_tags(
            provider="openligadb",
            category="standings",
            title="Bundesliga Table (OpenLigaDB)",
            llm=(
                "German league table from OpenLigaDB, an independent community source useful to "
                "cross-check ESPN's ger.1/ger.2. Positional season start year; league bl1 (default), "
                "bl2, bl3 or fbl1."
            ),
            schema=BUNDESLIGA_TABLE_SCHEMA,
            examples=_TABLE_EXAMPLES,
        )
        examples = function_examples(_TABLE_EXAMPLES)

    @classmethod
    def process(cls, params: ProcessParams[BundesligaTableArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit the table."""
        args = params.args
        response = api.fetch_openligadb_table(args.league, args.season)
        emit(
            out,
            flatten_bundesliga_table(response.payload, args.league, args.season),
            params.output_schema,
            response.max_age,
        )


@dataclass(kw_only=True)
class BundesligaMatchesArgs:
    """Arguments accepted by ``bundesliga_matches``."""

    season: Annotated[int, Arg(0, arrow_type=pa.int32(), ge=2002, le=2100, doc="Season start year.")]
    league: Annotated[
        str,
        Arg(
            "league", default="bl1", arrow_type=pa.string(), choices=OPENLIGADB_LEAGUES, doc=_OLDB_LEAGUE_DOC
        ),
    ]
    matchday: Annotated[
        int | None,
        Arg(
            "matchday",
            default=None,
            arrow_type=pa.int32(),
            ge=1,
            le=60,
            doc="Matchday (Spieltag) or cup round; NULL returns the whole season.",
        ),
    ]


_MATCH_EXAMPLES = [
    (
        "Bundesliga matchday 10 of 2025-26 with half-time and full-time scores.",
        "SELECT kickoff, team1_name, team1_goals, team2_goals, team2_name, team1_halftime, team2_halftime "
        "FROM soccer.main.bundesliga_matches(2025, matchday := 10) ORDER BY kickoff",
    )
]


@init_single_worker
@bind_fixed_schema
class BundesligaMatchesFunction(Sized, TableFunctionGenerator[BundesligaMatchesArgs]):
    """German league or cup matches from OpenLigaDB."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = BUNDESLIGA_MATCHES_SCHEMA
    ESTIMATE = 9
    MAXIMUM = 400

    class Meta:
        """Function discovery metadata."""

        name = "bundesliga_matches"
        description = "German league or DFB-Pokal matches from OpenLigaDB, per matchday or season"
        categories = ["soccer", "matches", "germany"]
        projection_pushdown = True
        tags = function_tags(
            provider="openligadb",
            category="matches",
            title="Bundesliga Matches (OpenLigaDB)",
            llm=(
                "Matches from OpenLigaDB for a positional season start year; league bl1 (default), bl2, "
                "bl3, fbl1 or dfb; matchday NULL returns the whole season. team1 is the home side."
            ),
            schema=BUNDESLIGA_MATCHES_SCHEMA,
            examples=_MATCH_EXAMPLES,
        )
        examples = function_examples(_MATCH_EXAMPLES)

    @classmethod
    def process(cls, params: ProcessParams[BundesligaMatchesArgs], state: None, out: OutputCollector) -> None:
        """Fetch and emit the matches."""
        args = params.args
        response = api.fetch_openligadb_matches(args.league, args.season, args.matchday)
        rows = flatten_bundesliga_matches(response.payload, args.league)
        rows.sort(key=lambda value: (value["kickoff"] is None, value["kickoff"], value["match_id"]))
        emit(out, rows, params.output_schema, response.max_age)


FUNCTIONS = [
    WorldCupMatchesFunction,
    WorldCupGoalsFunction,
    BundesligaTableFunction,
    BundesligaMatchesFunction,
]
