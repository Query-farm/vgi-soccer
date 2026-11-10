"""VGI worker exposing world football data as a read-only SQL catalog."""

from __future__ import annotations

import json
import os
import sys

from vgi import Worker
from vgi.catalog import Catalog, ConstraintInfo, Schema, Table, constraint_record

from vgi_soccer.league_schemas import LEAGUES_SCHEMA, STANDINGS_SCHEMA
from vgi_soccer.match_detail import FUNCTIONS as DETAIL_FUNCTIONS
from vgi_soccer.match_schemas import MATCH_SCHEMA
from vgi_soccer.matches import FUNCTIONS as MATCH_FUNCTIONS
from vgi_soccer.matches import CurrentMatchesFunction
from vgi_soccer.meta import column_comments
from vgi_soccer.open_sources import FUNCTIONS as OPEN_FUNCTIONS
from vgi_soccer.standings import FUNCTIONS as STANDINGS_FUNCTIONS
from vgi_soccer.standings import CurrentStandingsFunction, LeaguesFunction
from vgi_soccer.team_schemas import LEADERS_SCHEMA
from vgi_soccer.teams import FUNCTIONS as TEAM_FUNCTIONS
from vgi_soccer.teams import CurrentStatLeadersFunction

SOURCE_URL = "https://github.com/Query-farm/vgi-soccer"


def _examples(*items: tuple[str, str]) -> str:
    return json.dumps([{"description": text, "sql": sql} for text, sql in items])


_LEAGUES_TAGS = {
    "provider": "espn",
    "vgi.category": "leagues",
    "vgi.title": "Soccer League Directory",
    "vgi.keywords": json.dumps(["leagues", "competitions", "league slug", "tournaments", "cups"]),
    "vgi.doc_llm": (
        "About 220 competitions ESPN covers, one row per league_slug. Look up the slug here first: "
        "every other function's league argument takes it (eng.1 Premier League, esp.1 La Liga, "
        "ger.1 Bundesliga, ita.1 Serie A, fra.1 Ligue 1, uefa.champions, fifa.world, eng.w.1 WSL)."
    ),
    "vgi.doc_md": (
        "ESPN's soccer competition directory. `league_slug` is the identifier accepted by the "
        "`league` argument of `standings()`, `scoreboard()`, `schedule()`, `teams()` and more."
    ),
    "vgi.example_queries": _examples(
        (
            "Find the slug for a competition by name.",
            "SELECT league_slug, league_name FROM soccer.main.leagues "
            "WHERE league_name ILIKE '%women%' ORDER BY league_slug",
        )
    ),
}

_CURRENT_STANDINGS_TAGS = {
    "provider": "espn",
    "vgi.category": "standings",
    "vgi.title": "Current Big-Five League Tables",
    "vgi.keywords": json.dumps(
        ["standings", "league table", "Premier League", "La Liga", "Bundesliga", "Serie A", "Ligue 1"]
    ),
    "vgi.doc_llm": (
        "Current league tables for the Premier League (eng.1), La Liga (esp.1), Bundesliga (ger.1), "
        "Serie A (ita.1) and Ligue 1 (fra.1), one row per team, with rank, W/D/L, goals, goal "
        "difference, points and qualification zone. Filter by league_slug. For any other league or "
        "a past season call standings(league := ..., season := ...)."
    ),
    "vgi.doc_md": (
        "Today's tables for Europe's big-five leagues as one read-only table. Use `standings()` for "
        "other competitions and historical seasons."
    ),
    "vgi.example_queries": _examples(
        (
            "The current Premier League table.",
            "SELECT rank, team_name, games_played, goal_difference, points "
            "FROM soccer.main.current_standings WHERE league_slug = 'eng.1' ORDER BY rank",
        ),
        (
            "Leaders of each big-five league.",
            "SELECT league_name, team_name, points FROM soccer.main.current_standings "
            "WHERE rank = 1 ORDER BY points DESC",
        ),
    ),
}

_CURRENT_SCOREBOARD_TAGS = {
    "provider": "espn",
    "vgi.category": "matches",
    "vgi.title": "Today's Matches",
    "vgi.keywords": json.dumps(["scores", "live scores", "fixtures", "results", "today"]),
    "vgi.doc_llm": (
        "Today's matches across every competition ESPN tracks (one row per match): league, kick-off "
        "(UTC), state pre/in/post, live or final score, winner, venue. event_id feeds the match_* "
        "functions. Use scoreboard(league := ..., match_date := ...) for another day."
    ),
    "vgi.doc_md": (
        "Every soccer match on ESPN's current match day, across all competitions. Scores update as "
        "matches progress, subject to the short cache lifetime."
    ),
    "vgi.example_queries": _examples(
        (
            "Matches being played right now.",
            "SELECT league_name, home_team_name, home_score, away_score, away_team_name, status_detail "
            "FROM soccer.main.current_matches WHERE state = 'in' ORDER BY league_name",
        )
    ),
}

_CURRENT_LEADERS_TAGS = {
    "provider": "espn",
    "vgi.category": "player-stats",
    "vgi.title": "Current Big-Five Scoring Leaders",
    "vgi.keywords": json.dumps(["top scorers", "golden boot", "assists", "leaders", "goals"]),
    "vgi.doc_llm": (
        "Current-season top-50 goals and assists leaderboards for eng.1, esp.1, ger.1, ita.1 and fra.1. "
        "Filter category = 'goals' or 'assists' and league_slug, order by rank. For another league "
        "or season call stat_leaders()."
    ),
    "vgi.doc_md": "Current goals and assists leaders in Europe's big-five leagues.",
    "vgi.example_queries": _examples(
        (
            "Premier League top ten scorers this season.",
            "SELECT rank, player_name, team_name, goals, matches FROM soccer.main.current_stat_leaders "
            "WHERE league_slug = 'eng.1' AND category = 'goals' ORDER BY rank LIMIT 10",
        )
    ),
}

_EXECUTABLE_EXAMPLES = json.dumps(
    [
        {
            "name": "leicester_2015_title",
            "description": "Leicester City won the 2015-16 Premier League with 81 points.",
            "sql": (
                "SELECT team_name, points FROM soccer.main.standings(league := 'eng.1', season := 2015) "
                "WHERE rank = 1"
            ),
            "expected_result": [{"team_name": "Leicester City", "points": 81}],
        },
        {
            "name": "world_cup_2022_final",
            "description": "Argentina won the 2022 World Cup final on penalties.",
            "sql": (
                "SELECT winner, team1_penalties, team2_penalties FROM soccer.main.world_cup_matches(2022) "
                "WHERE round = 'Final'"
            ),
            "expected_result": [{"winner": "Argentina", "team1_penalties": 4, "team2_penalties": 2}],
        },
        {
            "name": "leagues_directory_has_premier_league",
            "description": "The league directory resolves eng.1 to the Premier League.",
            "sql": "SELECT league_name FROM soccer.main.leagues WHERE league_slug = 'eng.1'",
            "expected_result": [{"league_name": "English Premier League"}],
        },
        {
            "name": "current_tables_cover_big_five",
            "description": "The current tables cover all five leagues.",
            "sql": "SELECT count(DISTINCT league_slug) AS leagues FROM soccer.main.current_standings",
            "expected_result": [{"leagues": 5}],
        },
    ]
)

_AGENT_TEST_TASKS = json.dumps(
    [
        {
            "name": "leicester_title",
            "prompt": (
                "Which club won the 2015-16 Premier League, with how many points, and who was the "
                "league's top scorer that season?"
            ),
        },
        {
            "name": "big_five_leaders",
            "prompt": (
                "Which team tops each of Europe's big-five leagues right now, and who is the leading "
                "goal scorer in each of those leagues?"
            ),
        },
        {
            "name": "todays_matches",
            "prompt": "Which competitions have matches today, and how many matches does each have?",
        },
        {
            "name": "match_report",
            "prompt": (
                "Find the Premier League match between Manchester United and Aston Villa on "
                "8 November 2026, give the final score, list every goal with scorer and minute, and "
                "quote the commentary line for the opening goal."
            ),
        },
        {
            "name": "match_box_score",
            "prompt": (
                "For ESPN match 401879240, compare the two teams' possession, shots and expected "
                "goals (xG), and list the players who scored."
            ),
        },
        {
            "name": "arsenal_season",
            "prompt": "List every 2025-26 Premier League match Arsenal played, with the result.",
        },
        {
            "name": "squad_and_scorer",
            "prompt": (
                "Who are the forwards in Manchester City's current squad (ESPN team 382), and how many "
                "Premier League goals has Erling Haaland (ESPN athlete 253989) scored each season?"
            ),
        },
        {
            "name": "united_fixtures",
            "prompt": (
                "Look up Manchester United in the Premier League team list and show their remaining "
                "league fixtures this season."
            ),
        },
        {
            "name": "world_cup_2022",
            "prompt": (
                "Who won the 2022 World Cup final and how was it decided, and which team scored the "
                "most goals at that tournament?"
            ),
        },
        {
            "name": "bundesliga_season",
            "prompt": (
                "Show the final 2025-26 Bundesliga table from OpenLigaDB and the results of the last "
                "matchday (34)."
            ),
        },
    ]
)


def _key_constraints(table: str, key: tuple[str, ...]) -> tuple[ConstraintInfo, ...]:
    """Primary-key and NOT NULL records for a read-only table keyed by ``key``."""
    records = [
        constraint_record(
            ["main"],
            table,
            "pk",
            "PRIMARY_KEY",
            [[column] for column in key],
            enforcement="ENFORCED",
            validation="ALL_ROWS",
        )
    ]
    records += [
        constraint_record(
            ["main"],
            table,
            f"{column}_not_null",
            "NOT_NULL",
            [[column]],
            enforcement="ENFORCED",
            validation="ALL_ROWS",
        )
        for column in key
    ]
    return tuple(records)


SOCCER_CATALOG = Catalog(
    name="soccer",
    default_schema="main",
    source_url=SOURCE_URL,
    comment=(
        "Read-only world football data: league tables, fixtures, results, match detail and player "
        "statistics from ESPN, plus open World Cup (openfootball) and German league (OpenLigaDB) data"
    ),
    tags={
        "provider": "espn",
        "domain": "sports",
        "vgi.title": "World Football (Soccer) Data",
        "vgi.subtitle": (
            "League tables, scores, match events, xG and player statistics for 200+ competitions as SQL."
        ),
        "vgi.source_url": SOURCE_URL,
        "vgi.author": "Query Farm LLC <hello@query.farm>",
        "vgi.copyright": (
            "Worker (c) 2026 Query Farm LLC. Match data is fetched on demand from ESPN's undocumented "
            "public endpoints and remains subject to ESPN's terms; openfootball data is CC0; "
            "OpenLigaDB data is community-maintained open data. Not affiliated with ESPN, Disney, "
            "FIFA, UEFA or any league."
        ),
        "vgi.license": "MIT",
        "vgi.support_contact": "https://github.com/Query-farm/vgi-soccer/issues",
        "vgi.support_policy_url": "https://github.com/Query-farm/vgi-soccer/blob/main/README.md",
        "vgi.keywords": json.dumps(
            [
                "soccer",
                "football",
                "Premier League",
                "Champions League",
                "World Cup",
                "standings",
                "xG",
            ]
        ),
        "vgi.executable_examples": _EXECUTABLE_EXAMPLES,
        "vgi.agent_test_tasks": _AGENT_TEST_TASKS,
        "vgi.doc_llm": (
            "Read-only world football data. Competitions are identified by ESPN league slugs (eng.1 "
            "Premier League, esp.1, ger.1, ita.1, fra.1, uefa.champions, fifa.world, ...; see the leagues "
            "table). Seasons are START years: 2015 = 2015-16. Tables: leagues, current_standings and "
            "current_stat_leaders (big-five leagues), current_matches (today, all competitions). "
            "Functions: standings, scoreboard, schedule, team_schedule, teams, roster, stat_leaders, "
            "player_stats(athlete_id), and per-match detail keyed by event_id: match_summary, "
            "match_team_stats, match_player_stats, match_key_events, match_commentary, match_plays (with "
            "xG). Open data: world_cup_matches/world_cup_goals(year) 1930-2026 and bundesliga_table/"
            "bundesliga_matches(season) from OpenLigaDB. Leading id/year arguments are positional; "
            "everything else is named (league := 'esp.1')."
        ),
        "vgi.doc_md": (
            "# World football data\n\n"
            "Query league tables, fixtures and results, match events, box scores, play-by-play with "
            "expected goals, squads, leaderboards and player season lines for 200+ competitions, plus "
            "every men's World Cup since 1930 and German league data from OpenLigaDB.\n\n"
            "## Data model\n\n"
            "Competitions are addressed by ESPN league slug (`eng.1`, `uefa.champions`, `fifa.world`; "
            "list them in `leagues`). Seasons are start years. Matches carry an `event_id` that keys "
            "every `match_*` function.\n\n"
            "## Sources and terms\n\n"
            "Data is fetched on demand and never rehosted. ESPN endpoints are undocumented and subject "
            "to ESPN's terms; openfootball is CC0; OpenLigaDB is community open data. This worker is not "
            "affiliated with ESPN, Disney, FIFA, UEFA or any league."
        ),
    },
    schemas=[
        Schema(
            path=["main"],
            comment="World football league tables, matches, match detail, players and open history",
            tags={
                "provider": "espn",
                "domain": "sports",
                "vgi.title": "World Football",
                "vgi.keywords": json.dumps(
                    ["soccer", "football", "standings", "fixtures", "match events", "players", "World Cup"]
                ),
                "vgi.categories": json.dumps(
                    [
                        {
                            "name": "leagues",
                            "title": "Leagues",
                            "description": "The competition directory and league slugs.",
                            "keywords": ["leagues", "competitions", "slug"],
                        },
                        {
                            "name": "standings",
                            "title": "Standings",
                            "description": "League tables and group tables.",
                            "keywords": ["standings", "table", "points", "rank"],
                        },
                        {
                            "name": "matches",
                            "title": "Matches",
                            "description": "Fixtures, live scores, results and season schedules.",
                            "keywords": ["fixtures", "results", "scores", "schedule"],
                        },
                        {
                            "name": "match-detail",
                            "title": "Match Detail",
                            "description": "Box scores, line-ups, key events, commentary and play-by-play.",
                            "keywords": ["box score", "line-ups", "goals", "cards", "xG"],
                        },
                        {
                            "name": "teams",
                            "title": "Teams",
                            "description": "Teams in a competition and their squads.",
                            "keywords": ["teams", "clubs", "squad", "roster"],
                        },
                        {
                            "name": "player-stats",
                            "title": "Player Statistics",
                            "description": "Scoring and assist leaderboards and player season totals.",
                            "keywords": ["top scorers", "assists", "player stats"],
                        },
                        {
                            "name": "history",
                            "title": "World Cup History",
                            "description": "Every men's World Cup match and goal, 1930-2026 (CC0).",
                            "keywords": ["World Cup", "history", "goals"],
                        },
                    ]
                ),
                "vgi.doc_llm": (
                    "Start with leagues to find a league_slug, current_standings for today's big-five "
                    "tables, current_matches for today's matches and event_ids, and "
                    "current_stat_leaders for top scorers. Parameterized functions cover any league, "
                    "past seasons (start year), single-match detail by event_id, squads, player season "
                    "lines, World Cup history and OpenLigaDB German data."
                ),
                "vgi.doc_md": (
                    "## World football analytical data\n\n"
                    "Rows are explicitly league-, team-, match-, player-, event- or goal-grain. Current "
                    "tables serve the common questions; parameterized functions reach any competition "
                    "and season ESPN covers.\n\n"
                    "Find a competition's `league_slug` in `leagues`, take an `event_id` from "
                    "`scoreboard()` or `schedule()`, and pass it to the `match_*` functions for box "
                    "scores, line-ups, key events, commentary and play-by-play with expected goals."
                ),
                "vgi.example_queries": _CURRENT_STANDINGS_TAGS["vgi.example_queries"],
            },
            functions=[
                *STANDINGS_FUNCTIONS,
                *MATCH_FUNCTIONS,
                *TEAM_FUNCTIONS,
                *DETAIL_FUNCTIONS,
                *OPEN_FUNCTIONS,
            ],
            tables=[
                Table(
                    name="leagues",
                    function=LeaguesFunction,
                    comment="Every soccer competition ESPN covers, one row per league slug",
                    tags=_LEAGUES_TAGS,
                    column_comments=column_comments(LEAGUES_SCHEMA),
                    constraints=_key_constraints("leagues", ("league_slug",)),
                    cardinality_estimate=220,
                ),
                Table(
                    name="current_standings",
                    function=CurrentStandingsFunction,
                    comment="Current big-five European league tables, one row per team",
                    tags=_CURRENT_STANDINGS_TAGS,
                    column_comments=column_comments(STANDINGS_SCHEMA),
                    constraints=_key_constraints("current_standings", ("league_slug", "team_id")),
                    cardinality_estimate=96,
                ),
                Table(
                    name="current_matches",
                    function=CurrentMatchesFunction,
                    comment="Today's matches across every ESPN-covered competition, one row per match",
                    tags=_CURRENT_SCOREBOARD_TAGS,
                    column_comments=column_comments(MATCH_SCHEMA),
                    constraints=_key_constraints("current_matches", ("event_id",)),
                    cardinality_estimate=60,
                ),
                Table(
                    name="current_stat_leaders",
                    function=CurrentStatLeadersFunction,
                    comment="Current big-five goals and assists leaderboards, one row per player per board",
                    tags=_CURRENT_LEADERS_TAGS,
                    column_comments=column_comments(LEADERS_SCHEMA),
                    constraints=_key_constraints("current_stat_leaders", ("league_slug", "category", "rank")),
                    cardinality_estimate=500,
                ),
            ],
        )
    ],
)


class SoccerWorker(Worker):
    """Worker process hosting the read-only soccer catalog."""

    catalog = SOCCER_CATALOG


def main() -> None:
    """Run over stdio by default, or HTTP when VGI's ``--http`` flag is supplied."""
    SoccerWorker.main()


def main_http() -> None:
    """Run HTTP with production-safe configuration requirements."""
    if not os.environ.get("VGI_SIGNING_KEY"):
        raise SystemExit(
            "VGI_SIGNING_KEY is required for HTTP mode so state remains valid across restarts and replicas"
        )
    auth_configured = bool(os.environ.get("VGI_BEARER_TOKENS") or os.environ.get("VGI_JWT_ISSUER"))
    auth_configured = auth_configured or os.environ.get("VGI_PROXY_PROOF_MODE", "").lower() == "require"
    if not auth_configured and os.environ.get("VGI_ALLOW_ANONYMOUS") != "1":
        raise SystemExit(
            "HTTP authentication is required; configure bearer/JWT/proxy proof, or explicitly set "
            "VGI_ALLOW_ANONYMOUS=1 for an intentionally public deployment"
        )
    argv = sys.argv[1:]
    if "--http" not in argv:
        argv = ["--http", *argv]
    if "--describe" not in argv and "--no-describe" not in argv:
        argv = ["--no-describe", *argv]
    if not any(value == "--cors-origins" or value.startswith("--cors-origins=") for value in argv):
        argv = ["--cors-origins", "", *argv]
    sys.argv = [sys.argv[0], *argv]
    SoccerWorker.main()
