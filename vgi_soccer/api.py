"""Small, read-only, caching client for the soccer worker's upstream sources.

Every outbound request in the package goes through :func:`fetch_json`. The
client is deliberately conservative:

* one shared connection pool, a 30-second request timeout, and a 120-second
  deadline for each logical fetch (including every page of a paged fetch);
* bounded retries with exponential backoff and ``Retry-After`` support for
  HTTP 429 and transient 5xx responses; redirects are followed;
* a polite minimum interval between request starts to the same upstream
  (about one request per second for ESPN) and a small concurrency cap;
* an in-process response cache keyed by URL and query string that honors the
  origin's ``Cache-Control: max-age`` with a per-source floor, so repeated SQL
  queries do not re-hit the source.

Nothing is persisted to disk and nothing is rehosted: responses are fetched on
demand for the caller and discarded when the cache entry expires.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import random
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from vgi_soccer import __version__

USER_AGENT = f"vgi-soccer/{__version__} (+https://github.com/Query-farm/vgi-soccer)"
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 4
MAX_RETRY_DELAY = 30.0
QUERY_TIMEOUT = 120.0
MAX_CONCURRENT_REQUESTS = 2
MAX_PAGES = 10
CACHE_MAX_ENTRIES = 128
CACHE_MAX_BYTES = 16 * 1024 * 1024
ESPN_PAGE_LIMIT = 1_000

LEAGUE_PATTERN = r"^(all|[a-z]{2,10}(\.[a-z0-9_]+){0,3})$"
OPENLIGADB_PATTERN = r"^[a-z0-9]{2,12}$"
_LEAGUE = re.compile(LEAGUE_PATTERN)
_OPENLIGADB = re.compile(OPENLIGADB_PATTERN)
_MAX_AGE = re.compile(r"(?:^|[,\s])max-age=(\d+)", re.IGNORECASE)
_NO_STORE = re.compile(r"(?:^|[,\s])no-store(?:$|[,\s])", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Source:
    """One upstream origin: its override variable, default root, and politeness policy."""

    name: str
    env_var: str
    default_url: str
    bucket: str
    min_interval: float
    default_ttl: int
    min_ttl: int


SOURCES: dict[str, Source] = {
    source.name: source
    for source in (
        Source("site", "SOCCER_ESPN_SITE_URL", "https://site.api.espn.com", "espn", 1.0, 60, 30),
        Source("web", "SOCCER_ESPN_WEB_URL", "https://site.web.api.espn.com", "espn", 1.0, 300, 60),
        Source("core", "SOCCER_ESPN_CORE_URL", "https://sports.core.api.espn.com", "espn", 1.0, 60, 30),
        Source(
            "openfootball",
            "SOCCER_OPENFOOTBALL_URL",
            "https://raw.githubusercontent.com/openfootball/worldcup.json/master",
            "openfootball",
            0.25,
            3_600,
            300,
        ),
        Source(
            "openligadb", "SOCCER_OPENLIGADB_URL", "https://api.openligadb.de", "openligadb", 0.5, 300, 60
        ),
    )
}

logger = logging.getLogger(__name__)
_request_slots = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)
_throttle_lock = threading.Lock()
_next_start: dict[str, float] = {}
_cache_lock = threading.Lock()
_cache: OrderedDict[str, tuple[float, Any, int]] = OrderedDict()
_shared_client: httpx.Client | None = None
_client_lock = threading.Lock()


class SoccerApiError(RuntimeError):
    """A failed response from an upstream source."""

    def __init__(self, source: str, status: int, body: str) -> None:
        detail = body.strip()[:400]
        super().__init__(f"{source} returned HTTP {status}: {detail}")
        self.source = source
        self.status = status


@dataclass(frozen=True, slots=True)
class ApiResponse:
    """A decoded JSON payload plus the freshness lifetime it was cached for."""

    payload: Any
    max_age: int


def base_url(source: str) -> str:
    """Return a source's root URL, optionally overridden for hermetic tests."""
    spec = SOURCES[source]
    return os.environ.get(spec.env_var, spec.default_url).rstrip("/")


def clear_cache() -> None:
    """Forget every cached response and throttle reservation (used by tests)."""
    with _cache_lock:
        _cache.clear()
    with _throttle_lock:
        _next_start.clear()


def validate_league(league: str) -> str:
    """Return an ESPN league slug such as ``eng.1``, rejecting path-unsafe input."""
    if not isinstance(league, str) or not _LEAGUE.match(league):
        raise ValueError(f"invalid ESPN league slug {league!r}; expected a slug such as 'eng.1' or 'all'")
    return league


def validate_openligadb_league(league: str) -> str:
    """Return an OpenLigaDB league shortcut such as ``bl1``."""
    if not isinstance(league, str) or not _OPENLIGADB.match(league):
        raise ValueError(f"invalid OpenLigaDB league shortcut {league!r}; expected a value such as 'bl1'")
    return league


def _positive(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _min_interval(spec: Source) -> float:
    raw = os.environ.get("SOCCER_MIN_REQUEST_INTERVAL")
    if raw is None:
        return spec.min_interval
    try:
        return max(0.0, float(raw))
    except ValueError:
        return spec.min_interval


def _http() -> httpx.Client:
    """Return the process-wide connection pool."""
    global _shared_client
    with _client_lock:
        if _shared_client is None:
            _shared_client = httpx.Client(timeout=TIMEOUT, follow_redirects=True)
        return _shared_client


def _wait_turn(spec: Source, deadline: float) -> None:
    """Space request starts to one upstream by the source's polite interval."""
    interval = _min_interval(spec)
    if interval <= 0:
        return
    with _throttle_lock:
        now = time.monotonic()
        start = max(now, _next_start.get(spec.bucket, 0.0))
        _next_start[spec.bucket] = start + interval
    delay = start - time.monotonic()
    if delay > 0:
        if time.monotonic() + delay > deadline:
            raise TimeoutError(f"{spec.name} query exceeded {QUERY_TIMEOUT:g} seconds")
        time.sleep(delay)


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    """Return a bounded Retry-After delay or exponential backoff with jitter."""
    if response is not None:
        raw = response.headers.get("retry-after")
        if raw:
            try:
                delay = float(raw)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(raw)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=UTC)
                    delay = (retry_at - datetime.now(UTC)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    delay = -1.0
            if delay >= 0:
                return min(delay, MAX_RETRY_DELAY)
    base = min(0.25 * 2**attempt, MAX_RETRY_DELAY)
    return min(base + random.uniform(0, base * 0.25), MAX_RETRY_DELAY)


def _request(
    spec: Source,
    url: str,
    params: Mapping[str, str | int],
    *,
    client: httpx.Client,
    deadline: float,
) -> httpx.Response:
    """Issue one GET, retrying transient failures within the query deadline."""
    for attempt in range(MAX_ATTEMPTS):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"{spec.name} query exceeded {QUERY_TIMEOUT:g} seconds")
        _wait_turn(spec, deadline)
        started = time.monotonic()
        try:
            if not _request_slots.acquire(timeout=max(0.0, deadline - time.monotonic())):
                raise TimeoutError(f"{spec.name} query exceeded {QUERY_TIMEOUT:g} seconds")
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"{spec.name} query exceeded {QUERY_TIMEOUT:g} seconds")
                response = client.get(
                    url,
                    params=params,
                    headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                    timeout=httpx.Timeout(min(30.0, remaining), connect=min(10.0, remaining)),
                )
            finally:
                _request_slots.release()
        except httpx.TransportError:
            logger.warning(
                "soccer_api_transport_error source=%s attempt=%d duration_ms=%d",
                spec.name,
                attempt + 1,
                round((time.monotonic() - started) * 1_000),
            )
            if attempt + 1 == MAX_ATTEMPTS:
                raise
            time.sleep(min(_retry_delay(None, attempt), max(0.0, deadline - time.monotonic())))
            continue
        logger.debug(
            "soccer_api_response source=%s status=%d attempt=%d duration_ms=%d",
            spec.name,
            response.status_code,
            attempt + 1,
            round((time.monotonic() - started) * 1_000),
        )
        if response.status_code not in RETRYABLE_STATUSES or attempt + 1 == MAX_ATTEMPTS:
            return response
        delay = min(_retry_delay(response, attempt), max(0.0, deadline - time.monotonic()))
        logger.warning(
            "soccer_api_retry source=%s status=%d attempt=%d delay_seconds=%.3f",
            spec.name,
            response.status_code,
            attempt + 1,
            delay,
        )
        time.sleep(delay)
    raise AssertionError("retry loop exited without a response")


def _decode(spec: Source, response: httpx.Response) -> Any:
    """Decode JSON, tolerating a gzip body served without a Content-Encoding header."""
    body = response.content
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    try:
        return json.loads(body)
    except ValueError as exc:
        raise ValueError(f"{spec.name} returned a non-JSON response") from exc


def _ttl(spec: Source, response: httpx.Response) -> int:
    header = response.headers.get("cache-control", "")
    match = _MAX_AGE.search(header)
    origin = int(match.group(1)) if match else spec.default_ttl
    return max(origin, spec.min_ttl)


def _cache_key(url: str, params: Mapping[str, str | int]) -> str:
    return url + "?" + "&".join(f"{key}={params[key]}" for key in sorted(params))


def fetch_json(
    source: str,
    path: str,
    params: Mapping[str, str | int] | None = None,
    *,
    client: httpx.Client | None = None,
    deadline: float | None = None,
) -> ApiResponse:
    """Fetch and decode one JSON document, serving a fresh cached copy when available."""
    spec = SOURCES[source]
    query = dict(params or {})
    url = f"{base_url(source)}/{path.lstrip('/')}"
    key = _cache_key(url, query)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None and cached[0] > now:
            _cache.move_to_end(key)
            return ApiResponse(payload=cached[1], max_age=max(1, round(cached[0] - now)))
    response = _request(
        spec,
        url,
        query,
        client=client or _http(),
        deadline=deadline if deadline is not None else time.monotonic() + QUERY_TIMEOUT,
    )
    if not response.is_success:
        raise SoccerApiError(spec.name, response.status_code, response.text)
    payload = _decode(spec, response)
    ttl = _ttl(spec, response)
    if not _NO_STORE.search(response.headers.get("cache-control", "")) and (
        len(response.content) <= CACHE_MAX_BYTES
    ):
        with _cache_lock:
            _cache[key] = (time.monotonic() + ttl, payload, ttl)
            _cache.move_to_end(key)
            while len(_cache) > CACHE_MAX_ENTRIES:
                _cache.popitem(last=False)
    return ApiResponse(payload=payload, max_age=ttl)


def _object(response: ApiResponse, what: str) -> dict[str, Any]:
    if not isinstance(response.payload, dict):
        raise ValueError(f"{what} response is not a JSON object")
    return response.payload


def _list(response: ApiResponse, what: str) -> list[Any]:
    if not isinstance(response.payload, list):
        raise ValueError(f"{what} response is not a JSON array")
    return response.payload


# --- ESPN -------------------------------------------------------------------


def fetch_leagues(*, client: httpx.Client | None = None) -> ApiResponse:
    """Fetch ESPN's soccer league directory (about 220 competitions)."""
    response = fetch_json(
        "site", "apis/site/v2/leagues/dropdown", {"sport": "soccer", "limit": 500}, client=client
    )
    if not isinstance(_object(response, "ESPN leagues").get("leagues"), list):
        raise ValueError("ESPN leagues response has no leagues array")
    return response


def fetch_standings(
    league: str, season: int | None = None, *, client: httpx.Client | None = None
) -> ApiResponse:
    """Fetch a league table; ``season`` is the start year (2015 = 2015-16)."""
    params: dict[str, str | int] = {}
    if season is not None:
        params["season"] = _positive("season", season)
    response = fetch_json(
        "site", f"apis/v2/sports/soccer/{validate_league(league)}/standings", params, client=client
    )
    _object(response, "ESPN standings")
    return response


def fetch_scoreboard(
    league: str, dates: str | None = None, *, client: httpx.Client | None = None
) -> ApiResponse:
    """Fetch a scoreboard for a ``YYYYMMDD``, ``YYYYMM``, or ``YYYY`` window (ranges are rejected)."""
    params: dict[str, str | int] = {"limit": ESPN_PAGE_LIMIT}
    if dates is not None:
        if not re.fullmatch(r"\d{4}(\d{2}(\d{2})?)?", dates):
            raise ValueError("dates must be YYYY, YYYYMM, or YYYYMMDD")
        params["dates"] = dates
    response = fetch_json(
        "site", f"apis/site/v2/sports/soccer/{validate_league(league)}/scoreboard", params, client=client
    )
    if not isinstance(_object(response, "ESPN scoreboard").get("events", []), list):
        raise ValueError("ESPN scoreboard response has a malformed events array")
    return response


def fetch_teams(league: str, *, client: httpx.Client | None = None) -> ApiResponse:
    """Fetch the clubs (or national teams) currently registered in a league."""
    response = fetch_json(
        "site", f"apis/site/v2/sports/soccer/{validate_league(league)}/teams", {}, client=client
    )
    _object(response, "ESPN teams")
    return response


def fetch_roster(league: str, team_id: int, *, client: httpx.Client | None = None) -> ApiResponse:
    """Fetch a team's current squad."""
    path = (
        f"apis/site/v2/sports/soccer/{validate_league(league)}/teams/{_positive('team_id', team_id)}/roster"
    )
    response = fetch_json("site", path, {}, client=client)
    if not isinstance(_object(response, "ESPN roster").get("athletes", []), list):
        raise ValueError("ESPN roster response has a malformed athletes array")
    return response


def fetch_team_schedule(
    league: str,
    team_id: int,
    season: int | None = None,
    *,
    fixtures: bool = False,
    client: httpx.Client | None = None,
) -> ApiResponse:
    """Fetch one team's results (default) or upcoming fixtures in a league season."""
    params: dict[str, str | int] = {}
    if season is not None:
        params["season"] = _positive("season", season)
    if fixtures:
        params["fixture"] = "true"
    path = (
        f"apis/site/v2/sports/soccer/{validate_league(league)}/teams/{_positive('team_id', team_id)}/schedule"
    )
    response = fetch_json("site", path, params, client=client)
    _object(response, "ESPN team schedule")
    return response


def fetch_summary(event_id: int, *, client: httpx.Client | None = None) -> ApiResponse:
    """Fetch a match summary: header, box score, line-ups, key events, and commentary."""
    response = fetch_json(
        "site",
        "apis/site/v2/sports/soccer/all/summary",
        {"event": _positive("event_id", event_id)},
        client=client,
    )
    _object(response, "ESPN match summary")
    return response


def fetch_plays(event_id: int, *, client: httpx.Client | None = None) -> ApiResponse:
    """Fetch every play-by-play item for a match, following the core API's pages."""
    _positive("event_id", event_id)
    path = f"v2/sports/soccer/leagues/all/events/{event_id}/competitions/{event_id}/plays"
    deadline = time.monotonic() + QUERY_TIMEOUT
    items: list[Any] = []
    ttls: list[int] = []
    for page in range(1, MAX_PAGES + 1):
        response = fetch_json(
            "core", path, {"limit": ESPN_PAGE_LIMIT, "page": page}, client=client, deadline=deadline
        )
        payload = _object(response, "ESPN plays")
        page_items = payload.get("items")
        if not isinstance(page_items, list):
            raise ValueError("ESPN plays response has no items array")
        items.extend(page_items)
        ttls.append(response.max_age)
        page_count = payload.get("pageCount")
        if not page_items or not isinstance(page_count, int) or page >= page_count:
            return ApiResponse(payload=items, max_age=min(ttls))
    raise RuntimeError(f"ESPN plays pagination exceeded {MAX_PAGES} pages after {len(items)} plays")


def fetch_statistics(
    league: str, season: int | None = None, *, client: httpx.Client | None = None
) -> ApiResponse:
    """Fetch a league's goal and assist leaderboards for a season."""
    params: dict[str, str | int] = {}
    if season is not None:
        params["season"] = _positive("season", season)
    response = fetch_json(
        "site", f"apis/site/v2/sports/soccer/{validate_league(league)}/statistics", params, client=client
    )
    _object(response, "ESPN statistics")
    return response


def fetch_athlete_stats(
    athlete_id: int, league: str | None = None, *, client: httpx.Client | None = None
) -> ApiResponse:
    """Fetch one player's season-by-season totals in a league (default: their main league)."""
    params: dict[str, str | int] = {}
    if league is not None:
        params["league"] = validate_league(league)
    response = fetch_json(
        "web",
        f"apis/common/v3/sports/soccer/athletes/{_positive('athlete_id', athlete_id)}/stats",
        params,
        client=client,
    )
    _object(response, "ESPN athlete statistics")
    return response


# --- openfootball (CC0) and OpenLigaDB ---------------------------------------


def fetch_world_cup(year: int, *, client: httpx.Client | None = None) -> ApiResponse:
    """Fetch openfootball's public-domain match list for one men's World Cup."""
    response = fetch_json("openfootball", f"{_positive('year', year)}/worldcup.json", {}, client=client)
    if not isinstance(_object(response, "openfootball").get("matches"), list):
        raise ValueError("openfootball response has no matches array")
    return response


def fetch_openligadb_table(league: str, season: int, *, client: httpx.Client | None = None) -> ApiResponse:
    """Fetch an OpenLigaDB league table (``bl1`` = Bundesliga) for a season start year."""
    path = f"getbltable/{validate_openligadb_league(league)}/{_positive('season', season)}"
    response = fetch_json("openligadb", path, {}, client=client)
    _list(response, "OpenLigaDB table")
    return response


def fetch_openligadb_matches(
    league: str, season: int, matchday: int | None = None, *, client: httpx.Client | None = None
) -> ApiResponse:
    """Fetch OpenLigaDB matches for a whole season or one matchday."""
    path = f"getmatchdata/{validate_openligadb_league(league)}/{_positive('season', season)}"
    if matchday is not None:
        path += f"/{_positive('matchday', matchday)}"
    response = fetch_json("openligadb", path, {}, client=client)
    _list(response, "OpenLigaDB matches")
    return response
