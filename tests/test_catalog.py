"""Tests for the SQL-facing catalog shape and discovery metadata."""

from __future__ import annotations

import json

import pytest

from vgi_soccer.matches import CurrentMatchesFunction
from vgi_soccer.standings import CurrentStandingsFunction, LeaguesFunction, StandingsFunction
from vgi_soccer.teams import CurrentStatLeadersFunction, PlayerStatsFunction
from vgi_soccer.worker import SOCCER_CATALOG

SCHEMA = SOCCER_CATALOG.schemas[0]
FUNCTIONS = {function.Meta.name: function for function in SCHEMA.functions}
REQUIRED_FUNCTION_TAGS = {
    "vgi.title",
    "vgi.doc_llm",
    "vgi.doc_md",
    "vgi.example_queries",
    "vgi.result_columns_schema",
    "vgi.category",
}


def test_catalog_surface() -> None:
    assert SOCCER_CATALOG.name == "soccer"
    assert SCHEMA.path == ["main"]
    assert set(FUNCTIONS) == {
        "all_leagues",
        "standings",
        "all_current_standings",
        "scoreboard",
        "all_current_matches",
        "schedule",
        "team_schedule",
        "teams",
        "roster",
        "stat_leaders",
        "all_current_stat_leaders",
        "player_stats",
        "match_summary",
        "match_team_stats",
        "match_player_stats",
        "match_key_events",
        "match_commentary",
        "match_plays",
        "world_cup_matches",
        "world_cup_goals",
        "bundesliga_table",
        "bundesliga_matches",
    }
    assert {table.name: table.function for table in SCHEMA.tables} == {
        "leagues": LeaguesFunction,
        "current_standings": CurrentStandingsFunction,
        "current_matches": CurrentMatchesFunction,
        "current_stat_leaders": CurrentStatLeadersFunction,
    }


@pytest.mark.parametrize("name", sorted(FUNCTIONS))
def test_every_function_is_documented(name: str) -> None:
    function = FUNCTIONS[name]
    tags = function.Meta.tags
    assert tags.keys() >= REQUIRED_FUNCTION_TAGS
    examples = json.loads(tags["vgi.example_queries"])
    assert examples and all(f"soccer.main.{name}(" in example["sql"] for example in examples)
    columns = json.loads(tags["vgi.result_columns_schema"])
    assert [column["name"] for column in columns] == function.FIXED_SCHEMA.names
    assert all(column["description"] for column in columns)
    assert function.Meta.projection_pushdown is True


def test_standings_arguments_are_named_and_optional() -> None:
    parameters = {parameter.name: parameter for parameter in StandingsFunction.get_metadata().parameters}
    assert set(parameters) == {"league", "season"}
    assert all(not parameter.required for parameter in parameters.values())


def test_player_stats_takes_a_positional_athlete_id() -> None:
    parameters = {parameter.name: parameter for parameter in PlayerStatsFunction.get_metadata().parameters}
    assert parameters["athlete_id"].required
    assert not parameters["league"].required


def _key_of(table, kind: str) -> list[tuple[str, ...]]:
    return [
        tuple(name for path in record.definition.column_paths for name in path)
        for record in table.constraints
        if record.definition.kind == kind
    ]


def test_table_keys() -> None:
    tables = {table.name: table for table in SCHEMA.tables}
    assert _key_of(tables["leagues"], "PRIMARY_KEY") == [("league_slug",)]
    assert _key_of(tables["current_standings"], "PRIMARY_KEY") == [("league_slug", "team_id")]
    assert _key_of(tables["current_matches"], "PRIMARY_KEY") == [("event_id",)]
    assert _key_of(tables["current_stat_leaders"], "NOT_NULL") == [("league_slug",), ("category",), ("rank",)]
    for table in tables.values():
        assert {"vgi.title", "vgi.doc_llm", "vgi.doc_md", "vgi.keywords", "vgi.example_queries"} <= set(
            table.tags
        )
        assert table.column_comments


def test_catalog_discovery_contract_is_public_and_machine_readable() -> None:
    tags = SOCCER_CATALOG.tags
    assert {"vgi.title", "vgi.subtitle", "vgi.doc_llm", "vgi.doc_md", "vgi.keywords"} <= set(tags)
    assert "Not affiliated with ESPN" in tags["vgi.copyright"]
    examples = json.loads(tags["vgi.executable_examples"])
    tasks = json.loads(tags["vgi.agent_test_tasks"])
    assert all({"name", "description", "sql", "expected_result"} <= example.keys() for example in examples)
    assert 6 <= len(tasks) <= 10
    assert all(set(task) == {"name", "prompt"} for task in tasks)
    assert len({task["name"] for task in tasks}) == len(tasks)
