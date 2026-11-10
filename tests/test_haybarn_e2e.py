"""Hermetic end-to-end coverage through Haybarn and the VGI transport."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from fixture_routes import resolve


class _FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        payload = resolve(parsed.path, dict(parse_qsl(parsed.query)))
        if payload is None:
            self.send_error(404)
            return
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "max-age=60")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_haybarn_attaches_and_queries_every_current_table_and_function_family() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    project = Path(__file__).resolve().parent.parent
    location = f"uv run --project {project} vgi-soccer"
    sql = (
        f"INSTALL vgi FROM community; LOAD vgi; ATTACH 'soccer' (TYPE vgi, LOCATION '{location}'); "
        "SELECT "
        "(SELECT count(*) FROM soccer.main.leagues) AS leagues, "
        "(SELECT count(DISTINCT league_slug) FROM soccer.main.current_standings) AS standings, "
        "(SELECT count(*) FROM soccer.main.current_matches) AS scoreboard, "
        "(SELECT count(DISTINCT league_slug) FROM soccer.main.current_stat_leaders) AS leaders, "
        "(SELECT points FROM soccer.main.standings(league := 'eng.1', season := 2015) WHERE rank = 1) "
        "AS leicester, "
        "(SELECT count(*) FILTER (WHERE scoring_play) "
        "FROM soccer.main.match_key_events(401879240)) AS goals, "
        "(SELECT winner FROM soccer.main.world_cup_matches(2022) WHERE round = 'Final') AS champion;"
    )
    base = f"http://127.0.0.1:{server.server_port}"
    env = {
        **os.environ,
        "SOCCER_ESPN_SITE_URL": base,
        "SOCCER_ESPN_WEB_URL": base,
        "SOCCER_ESPN_CORE_URL": base,
        "SOCCER_OPENFOOTBALL_URL": f"{base}/openfootball",
        "SOCCER_OPENLIGADB_URL": f"{base}/openligadb",
        "SOCCER_MIN_REQUEST_INTERVAL": "0",
    }
    try:
        result = subprocess.run(
            ["uvx", "haybarn-cli", ":memory:", "-csv", "-c", sql],
            cwd=project,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert "leagues,standings,scoreboard,leaders,leicester,goals,champion" in result.stdout
    assert "12,5,6,5,81,8,Argentina" in result.stdout
