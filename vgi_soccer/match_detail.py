"""VGI table functions for one match: summary, box score, player lines, events, commentary, plays."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, ClassVar

import pyarrow as pa
from vgi.table_function import (
    ProcessParams,
    TableFunctionGenerator,
    bind_fixed_schema,
    init_single_worker,
)
from vgi_rpc.rpc import OutputCollector

from vgi_soccer import api
from vgi_soccer.common import Sized, emit, function_examples, function_tags, id_arg
from vgi_soccer.detail_schemas import (
    COMMENTARY_SCHEMA,
    KEY_EVENTS_SCHEMA,
    PLAYER_MATCH_SCHEMA,
    PLAYS_SCHEMA,
    SUMMARY_SCHEMA,
    TEAM_STATS_SCHEMA,
    flatten_commentary,
    flatten_key_events,
    flatten_player_match_stats,
    flatten_plays,
    flatten_summary,
    flatten_team_stats,
)

# Manchester United 4-4 Aston Villa, Premier League, 8 November 2026.
EXAMPLE_EVENT = 401879240


@dataclass(kw_only=True)
class MatchArgs:
    """Arguments accepted by every match_* function."""

    event_id: Annotated[
        int, id_arg(0, "ESPN match id (event_id) from scoreboard(), schedule() or team_schedule().")
    ]


class _SummaryBacked(Sized):
    """Shared process for functions that read the ESPN match summary."""

    FLATTEN: ClassVar[Callable[[Any, int], list[dict[str, Any]]]]

    @classmethod
    def process(cls, params: ProcessParams[MatchArgs], state: None, out: OutputCollector) -> None:
        """Fetch the match summary and emit this function's slice of it."""
        event_id = params.args.event_id
        response = api.fetch_summary(event_id)
        emit(out, cls.FLATTEN(response.payload, event_id), params.output_schema, response.max_age)


def _meta_tags(title: str, llm: str, schema: pa.Schema, examples: list[tuple[str, str]]) -> dict[str, str]:
    return function_tags(
        provider="espn", category="match-detail", title=title, llm=llm, schema=schema, examples=examples
    )


_SUMMARY_EXAMPLES = [
    (
        "Header for Manchester United v Aston Villa (event 401879240).",
        "SELECT home_team_name, home_score, away_score, away_team_name, home_formation, "
        f"away_formation, venue_name, attendance FROM soccer.main.match_summary({EXAMPLE_EVENT})",
    )
]


@init_single_worker
@bind_fixed_schema
class MatchSummaryFunction(_SummaryBacked, TableFunctionGenerator[MatchArgs]):
    """One-row match header."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = SUMMARY_SCHEMA
    FLATTEN = staticmethod(flatten_summary)
    ESTIMATE = 1
    MAXIMUM = 1

    class Meta:
        """Function discovery metadata."""

        name = "match_summary"
        description = "One-row header for a match: teams, score, formations, venue, attendance"
        categories = ["soccer", "match-detail"]
        projection_pushdown = True
        tags = _meta_tags(
            "Match Summary",
            (
                "One row for a match (positional event_id): competition, kick-off, status, score, "
                "formations, W-D-L records, venue, attendance. Get event_id from scoreboard() or "
                "schedule()."
            ),
            SUMMARY_SCHEMA,
            _SUMMARY_EXAMPLES,
        )
        examples = function_examples(_SUMMARY_EXAMPLES)


_TEAM_STATS_EXAMPLES = [
    (
        "Possession, shots and passing for both sides.",
        "SELECT team_name, possession_pct, shots, shots_on_target, corners, passes, accurate_passes "
        f"FROM soccer.main.match_team_stats({EXAMPLE_EVENT})",
    )
]


@init_single_worker
@bind_fixed_schema
class MatchTeamStatsFunction(_SummaryBacked, TableFunctionGenerator[MatchArgs]):
    """Team box score for a match."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = TEAM_STATS_SCHEMA
    FLATTEN = staticmethod(flatten_team_stats)
    ESTIMATE = 2
    MAXIMUM = 2

    class Meta:
        """Function discovery metadata."""

        name = "match_team_stats"
        description = "Team box score for a match: possession, shots, passes, tackles, cards"
        categories = ["soccer", "match-detail"]
        projection_pushdown = True
        tags = _meta_tags(
            "Match Team Statistics",
            (
                "Two rows (home, away) with possession %, shots, shots on target, corners, fouls, cards, "
                "passes, crosses, long balls, tackles, interceptions, clearances and penalties. "
                "Accuracy rates are left to SQL: accurate_passes / passes."
            ),
            TEAM_STATS_SCHEMA,
            _TEAM_STATS_EXAMPLES,
        )
        examples = function_examples(_TEAM_STATS_EXAMPLES)


_PLAYER_EXAMPLES = [
    (
        "Goal scorers and assisters in the match.",
        "SELECT team_name, player_name, goals, assists, shots FROM soccer.main.match_player_stats("
        f"{EXAMPLE_EVENT}) WHERE goals > 0 OR assists > 0 ORDER BY goals DESC, assists DESC",
    )
]


@init_single_worker
@bind_fixed_schema
class MatchPlayerStatsFunction(_SummaryBacked, TableFunctionGenerator[MatchArgs]):
    """Per-player line-up and statistics for a match."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = PLAYER_MATCH_SCHEMA
    FLATTEN = staticmethod(flatten_player_match_stats)
    ESTIMATE = 40
    MAXIMUM = 60

    class Meta:
        """Function discovery metadata."""

        name = "match_player_stats"
        description = "Line-ups and per-player statistics for a match"
        categories = ["soccer", "match-detail", "players"]
        projection_pushdown = True
        tags = _meta_tags(
            "Match Player Statistics",
            (
                "One row per squad member: starter/subbed_in/subbed_out flags, position, goals, "
                "assists, shots, cards, fouls, own goals, and goalkeeper saves/goals conceded."
            ),
            PLAYER_MATCH_SCHEMA,
            _PLAYER_EXAMPLES,
        )
        examples = function_examples(_PLAYER_EXAMPLES)


_KEY_EVENTS_EXAMPLES = [
    (
        "Every goal in order with scorer and assister.",
        "SELECT clock_display, team_name, player_name, secondary_player_name, event_type "
        f"FROM soccer.main.match_key_events({EXAMPLE_EVENT}) WHERE scoring_play ORDER BY sequence",
    )
]


@init_single_worker
@bind_fixed_schema
class MatchKeyEventsFunction(_SummaryBacked, TableFunctionGenerator[MatchArgs]):
    """Goals, cards, substitutions and period markers for a match."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = KEY_EVENTS_SCHEMA
    FLATTEN = staticmethod(flatten_key_events)
    ESTIMATE = 40
    MAXIMUM = 120

    class Meta:
        """Function discovery metadata."""

        name = "match_key_events"
        description = "Goals, cards and substitutions for a match in order"
        categories = ["soccer", "match-detail"]
        projection_pushdown = True
        tags = _meta_tags(
            "Match Key Events",
            (
                "Chronological key events. event_type is a slug (goal, goal---header, penalty---scored, "
                "own-goal, yellow-card, red-card, substitution, kickoff, halftime). WHERE scoring_play "
                "gives the goals; player_name is the scorer and secondary_player_name the assister."
            ),
            KEY_EVENTS_SCHEMA,
            _KEY_EVENTS_EXAMPLES,
        )
        examples = function_examples(_KEY_EVENTS_EXAMPLES)


_COMMENTARY_EXAMPLES = [
    (
        "The first ten commentary lines.",
        f"SELECT clock_display, text FROM soccer.main.match_commentary({EXAMPLE_EVENT}) "
        "ORDER BY sequence LIMIT 10",
    )
]


@init_single_worker
@bind_fixed_schema
class MatchCommentaryFunction(_SummaryBacked, TableFunctionGenerator[MatchArgs]):
    """ESPN text commentary for a match."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = COMMENTARY_SCHEMA
    FLATTEN = staticmethod(flatten_commentary)
    ESTIMATE = 130
    MAXIMUM = 400

    class Meta:
        """Function discovery metadata."""

        name = "match_commentary"
        description = "Minute-by-minute text commentary for a match"
        categories = ["soccer", "match-detail"]
        projection_pushdown = True
        tags = _meta_tags(
            "Match Commentary",
            "Text commentary lines in order (sequence), each with the match minute and linked play type.",
            COMMENTARY_SCHEMA,
            _COMMENTARY_EXAMPLES,
        )
        examples = function_examples(_COMMENTARY_EXAMPLES)


_PLAYS_EXAMPLES = [
    (
        "Shots with expected goals (xG), biggest chances first.",
        "SELECT clock_display, play_type, expected_goals, text FROM soccer.main.match_plays("
        f"{EXAMPLE_EVENT}) WHERE expected_goals IS NOT NULL ORDER BY expected_goals DESC LIMIT 10",
    )
]


@init_single_worker
@bind_fixed_schema
class MatchPlaysFunction(Sized, TableFunctionGenerator[MatchArgs]):
    """Full play-by-play for a match, with shot xG."""

    FIXED_SCHEMA: ClassVar[pa.Schema] = PLAYS_SCHEMA
    ESTIMATE = 1_400
    MAXIMUM = 10_000

    class Meta:
        """Function discovery metadata."""

        name = "match_plays"
        description = "Every on-ball action in a match, with expected goals for shots"
        categories = ["soccer", "match-detail"]
        projection_pushdown = True
        tags = _meta_tags(
            "Match Play-by-Play",
            (
                "About 1,400 actions per match (passes, shots, saves, fouls, ...). Shots carry "
                "expected_goals (xG) and expected_goals_on_target; field_x/field_y are 0-100 pitch "
                "coordinates. Sum expected_goals by team_id for match xG."
            ),
            PLAYS_SCHEMA,
            _PLAYS_EXAMPLES,
        )
        examples = function_examples(_PLAYS_EXAMPLES)

    @classmethod
    def process(cls, params: ProcessParams[MatchArgs], state: None, out: OutputCollector) -> None:
        """Fetch every page of plays and emit them."""
        event_id = params.args.event_id
        response = api.fetch_plays(event_id)
        emit(out, flatten_plays(response.payload, event_id), params.output_schema, response.max_age)


FUNCTIONS = [
    MatchSummaryFunction,
    MatchTeamStatsFunction,
    MatchPlayerStatsFunction,
    MatchKeyEventsFunction,
    MatchCommentaryFunction,
    MatchPlaysFunction,
]
