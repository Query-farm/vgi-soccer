"""Argument definitions, metadata builders, and emit helpers shared by every table function."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any, ClassVar

import pyarrow as pa
from vgi.arguments import Arg
from vgi.cache_control import CacheControl
from vgi.metadata import FunctionExample
from vgi.table_function import TableCardinality
from vgi_rpc.rpc import OutputCollector

from vgi_soccer import api
from vgi_soccer.meta import batch_from_rows, result_columns_schema

#: The "big five" European top flights used by the current_* convenience tables.
MAJOR_LEAGUES = ("eng.1", "esp.1", "ger.1", "ita.1", "fra.1")

LEAGUE_DOC = (
    "ESPN league slug, e.g. eng.1 (Premier League), esp.1, ger.1, ita.1, fra.1, uefa.champions, "
    "fifa.world. List every slug with SELECT league_slug FROM soccer.main.leagues."
)


def league_arg(default: str = "eng.1", doc: str = LEAGUE_DOC) -> Arg:
    """A named, optional ESPN league-slug argument."""
    return Arg("league", default=default, arrow_type=pa.string(), pattern=api.LEAGUE_PATTERN, doc=doc)


def season_arg(doc: str = "Season start year (2015 = 2015-16). NULL selects ESPN's current season.") -> Arg:
    """A named, optional season-start-year argument."""
    return Arg("season", default=None, arrow_type=pa.int32(), ge=1900, le=2100, doc=doc)


def id_arg(position: int, doc: str) -> Arg:
    """A required positional numeric identifier."""
    return Arg(position, arrow_type=pa.int64(), ge=1, doc=doc)


def require_single_league(league: str) -> str:
    """Reject the ``all`` pseudo-league for endpoints that need one competition."""
    api.validate_league(league)
    if league == "all":
        raise ValueError("this function needs one competition; pass a league slug such as 'eng.1'")
    return league


def cache_control(max_age: int | None) -> CacheControl | None:
    """Forward the freshness lifetime the upstream response was cached for."""
    return CacheControl(ttl=max_age) if max_age else None


def emit(
    out: OutputCollector,
    rows: Sequence[Mapping[str, Any]],
    output_schema: pa.Schema,
    max_age: int | None,
) -> None:
    """Emit one batch in the (possibly projected) output schema and finish the stream."""
    out.emit(batch_from_rows(rows, output_schema), cache_control=cache_control(max_age))
    out.finish()


def gather(
    fetches: Sequence[Callable[[], tuple[list[dict[str, Any]], int]]],
) -> tuple[list[dict[str, Any]], int | None]:
    """Run several fetch-and-flatten steps; the result is fresh for the shortest lifetime."""
    rows: list[dict[str, Any]] = []
    ages: list[int] = []
    for fetch in fetches:
        part, age = fetch()
        rows.extend(part)
        ages.append(age)
    return rows, (min(ages) if ages else None)


_SOURCE_NOTES = {
    "espn": (
        "**Source:** ESPN's undocumented public soccer endpoints, fetched on demand and cached in "
        "process for the upstream's freshness lifetime (at least 30 seconds). Use is subject to "
        "ESPN's terms; this worker is not affiliated with ESPN, Disney or any competition."
    ),
    "openfootball": (
        "**Source:** the openfootball worldcup.json project on GitHub, dedicated to the public "
        "domain (CC0). Player names are as published and occasionally vary in spelling."
    ),
    "openligadb": (
        "**Source:** OpenLigaDB, a community-maintained open football database (api.openligadb.de). "
        "Team ids are OpenLigaDB ids, not ESPN ids."
    ),
}


def function_tags(
    *,
    provider: str,
    category: str,
    title: str,
    llm: str,
    schema: pa.Schema,
    examples: Sequence[tuple[str, str]],
    md: str | None = None,
) -> dict[str, str]:
    """Build the discovery tags every soccer function carries."""
    return {
        "provider": provider,
        "vgi.category": category,
        "vgi.title": title,
        "vgi.result_columns_schema": result_columns_schema(schema),
        "vgi.doc_llm": llm,
        "vgi.doc_md": f"{md or llm}\n\n{_SOURCE_NOTES[provider]}",
        "vgi.example_queries": json.dumps([{"description": text, "sql": sql} for text, sql in examples]),
    }


def function_examples(examples: Sequence[tuple[str, str]]) -> list[FunctionExample]:
    """Mirror the example queries as SDK function examples."""
    return [FunctionExample(sql=sql, description=text) for text, sql in examples]


class Sized:
    """Mixin supplying a static planner estimate."""

    ESTIMATE: ClassVar[int] = 20
    MAXIMUM: ClassVar[int] = 1_000

    @classmethod
    def cardinality(cls, params: object) -> TableCardinality:
        """Return the static planner estimate for this function."""
        return TableCardinality(estimate=cls.ESTIMATE, max=cls.MAXIMUM)
