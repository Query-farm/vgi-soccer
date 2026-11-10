"""Map upstream request paths to the recorded, trimmed responses in tests/fixtures.

The same router backs the in-process MockTransport tests and the local HTTP
server used by the hermetic Haybarn end-to-end test, so both exercise the
real request paths the worker builds.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BIG_FIVE = {"eng.1", "esp.1", "ger.1", "ita.1", "fra.1"}


def load(name: str) -> Any:
    """Return a decoded fixture."""
    return json.loads((FIXTURES / name).read_text())


def _empty_scoreboard() -> dict[str, Any]:
    return {"leagues": [{"slug": "eng.1", "name": "English Premier League"}], "events": []}


def resolve(path: str, query: Mapping[str, str]) -> Any | None:
    """Return the payload for one upstream GET, or ``None`` for a 404."""
    path = "/" + path.lstrip("/")
    if path.endswith("/apis/site/v2/leagues/dropdown"):
        return load("espn_leagues.json")
    if match := re.search(r"/apis/v2/sports/soccer/([^/]+)/standings$", path):
        league = match.group(1)
        if league == "fifa.world":
            return load("espn_standings_fifa_world.json")
        if league == "eng.fa":
            return load("espn_standings_eng_fa.json")
        if query.get("season") == "2015":
            return load("espn_standings_eng1_2015.json")
        return load("espn_standings_eng1_current.json") if league in BIG_FIVE | {"uefa.champions"} else None
    if path.endswith("/apis/site/v2/sports/soccer/all/scoreboard"):
        return load("espn_scoreboard_all_current.json")
    if re.search(r"/apis/site/v2/sports/soccer/[^/]+/scoreboard$", path):
        dates = query.get("dates")
        if dates == "2025":
            return load("espn_scoreboard_eng1_2025.json")
        if dates is None or dates == "20261108":
            return load("espn_scoreboard_eng1_20261108.json")
        return _empty_scoreboard()
    if re.search(r"/teams/\d+/roster$", path):
        return load("espn_roster_360.json")
    if re.search(r"/teams/\d+/schedule$", path):
        if query.get("fixture") == "true":
            return load("espn_team_fixtures_360.json")
        return load("espn_team_schedule_360_2025.json")
    if re.search(r"/apis/site/v2/sports/soccer/[^/]+/teams$", path):
        return load("espn_teams_eng1.json")
    if path.endswith("/all/summary"):
        return load("espn_summary_401879240.json") if query.get("event") == "401879240" else None
    if path.endswith("/plays"):
        return load(f"espn_plays_401879240_p{query.get('page', '1')}.json")
    if re.search(r"/apis/site/v2/sports/soccer/[^/]+/statistics$", path):
        return load("espn_statistics_eng1_2015.json")
    if match := re.search(r"/athletes/(\d+)/stats$", path):
        return load(f"espn_athlete_{'301425' if match.group(1) == '301425' else '253989'}_stats.json")
    if re.search(r"/\d{4}/worldcup\.json$", path):
        return load("openfootball_worldcup_2022.json")
    if "/getbltable/" in path:
        return load("openligadb_table_bl1_2025.json")
    if "/getmatchdata/" in path:
        return load("openligadb_matches_bl1_2025_10.json")
    return None
