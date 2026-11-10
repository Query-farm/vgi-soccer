"""Tests for the upstream HTTP boundary: URLs, headers, caching, retries, and validation."""

from __future__ import annotations

import gzip
import json

import httpx
import pytest

from vgi_soccer import api


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_request_shape_user_agent_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOCCER_ESPN_SITE_URL", "https://example.test/espn/")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"children": []}, headers={"Cache-Control": "max-age=300"})

    with _client(handler) as client:
        response = api.fetch_standings("eng.1", 2015, client=client)

    (request,) = seen
    assert str(request.url) == "https://example.test/espn/apis/v2/sports/soccer/eng.1/standings?season=2015"
    assert request.headers["user-agent"] == (
        f"vgi-soccer/{api.__version__} (+https://github.com/Query-farm/vgi-soccer)"
    )
    assert request.headers["accept"] == "application/json"
    assert response.max_age == 300


def test_responses_are_cached_in_process() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"events": []}, headers={"Cache-Control": "max-age=10"})

    with _client(handler) as client:
        first = api.fetch_scoreboard("eng.1", "20261108", client=client)
        second = api.fetch_scoreboard("eng.1", "20261108", client=client)
        api.fetch_scoreboard("eng.1", "20261109", client=client)

    assert calls == 2
    # A 10-second origin lifetime is raised to the source's politeness floor.
    assert first.max_age == api.SOURCES["site"].min_ttl
    assert 1 <= second.max_age <= first.max_age


def test_no_store_and_oversized_responses_are_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"leagues": []}, headers={"Cache-Control": "no-store"})

    with _client(handler) as client:
        api.fetch_leagues(client=client)
        api.fetch_leagues(client=client)
    assert calls == 2

    monkeypatch.setattr(api, "CACHE_MAX_BYTES", 1)
    with _client(lambda request: httpx.Response(200, json={"leagues": []})) as client:
        api.fetch_leagues(client=client)
    assert not api._cache


def test_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "CACHE_MAX_ENTRIES", 2)
    with _client(lambda request: httpx.Response(200, json={"events": []})) as client:
        for day in ("20261101", "20261102", "20261103"):
            api.fetch_scoreboard("eng.1", day, client=client)
    assert len(api._cache) == 2


def test_default_ttl_applies_without_cache_control() -> None:
    with _client(lambda request: httpx.Response(200, json=[])) as client:
        response = api.fetch_openligadb_table("bl1", 2025, client=client)
    assert response.max_age == api.SOURCES["openligadb"].default_ttl


def test_retries_transient_failures_honoring_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    statuses = iter([503, 429, 200])
    sleeps: list[float] = []
    monkeypatch.setattr(api.time, "sleep", sleeps.append)

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        if status == 200:
            return httpx.Response(200, json={"matches": []})
        return httpx.Response(status, headers={"Retry-After": "2"})

    with _client(handler) as client:
        api.fetch_world_cup(2022, client=client)
    assert sleeps == [2.0, 2.0]


def test_transport_errors_are_retried_then_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api.time, "sleep", lambda delay: None)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("boom", request=request)

    with _client(handler) as client, pytest.raises(httpx.ConnectError):
        api.fetch_world_cup(2022, client=client)
    assert calls == api.MAX_ATTEMPTS


def test_retry_delay_parses_http_dates_and_backs_off() -> None:
    past = httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
    assert 0.25 <= api._retry_delay(past, 0) <= 0.3125
    future = httpx.Response(429, headers={"Retry-After": "Fri, 01 Jan 2100 00:00:00 GMT"})
    assert api._retry_delay(future, 0) == api.MAX_RETRY_DELAY
    garbage = httpx.Response(429, headers={"Retry-After": "soon"})
    assert 0.25 <= api._retry_delay(garbage, 0) <= 0.3125
    assert api._retry_delay(None, 20) <= api.MAX_RETRY_DELAY


def test_http_errors_are_descriptive() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": 400, "message": "Unable to retrieve any standings"})

    with (
        _client(handler) as client,
        pytest.raises(api.SoccerApiError, match="site returned HTTP 400.*standings"),
    ):
        api.fetch_standings("xxx.9", client=client)


def test_gzip_body_without_content_encoding_is_decoded() -> None:
    body = gzip.compress(json.dumps({"leagues": [{"slug": "eng.1"}]}).encode())
    with _client(lambda request: httpx.Response(200, content=body)) as client:
        response = api.fetch_leagues(client=client)
    assert response.payload["leagues"][0]["slug"] == "eng.1"


def test_non_json_and_malformed_payloads_are_rejected() -> None:
    with _client(lambda request: httpx.Response(200, text="<html>")) as client, pytest.raises(ValueError):
        api.fetch_teams("eng.1", client=client)
    with _client(lambda request: httpx.Response(200, json={"x": 1})) as client, pytest.raises(ValueError):
        api.fetch_world_cup(2022, client=client)
    with _client(lambda request: httpx.Response(200, json={"x": 1})) as client, pytest.raises(ValueError):
        api.fetch_openligadb_matches("bl1", 2025, client=client)
    with _client(lambda request: httpx.Response(200, json=[])) as client, pytest.raises(ValueError):
        api.fetch_summary(1, client=client)
    with (
        _client(lambda request: httpx.Response(200, json={"events": {}})) as client,
        pytest.raises(ValueError),
    ):
        api.fetch_scoreboard("eng.1", client=client)
    with (
        _client(lambda request: httpx.Response(200, json={"athletes": 1})) as client,
        pytest.raises(ValueError),
    ):
        api.fetch_roster("eng.1", 1, client=client)
    with _client(lambda request: httpx.Response(200, json={"items": 1})) as client, pytest.raises(ValueError):
        api.fetch_plays(1, client=client)


def test_redirects_are_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/old"):
            return httpx.Response(307, headers={"Location": "https://example.test/new"})
        return httpx.Response(200, json={"ok": True})

    with _client(handler) as client:
        response = api.fetch_json("site", "old", client=client)
    assert response.payload == {"ok": True}


def test_plays_follow_every_page() -> None:
    pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        pages.append(page)
        assert request.url.params["limit"] == "1000"
        assert "/leagues/all/events/7/competitions/7/plays" in request.url.path
        return httpx.Response(200, json={"pageCount": 2, "items": [{"id": page}]})

    with _client(handler) as client:
        response = api.fetch_plays(7, client=client)
    assert pages == ["1", "2"]
    assert response.payload == [{"id": "1"}, {"id": "2"}]


def test_plays_pagination_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "MAX_PAGES", 2)
    with (
        _client(lambda request: httpx.Response(200, json={"pageCount": 99, "items": [{}]})) as client,
        pytest.raises(RuntimeError, match="pagination exceeded"),
    ):
        api.fetch_plays(7, client=client)


@pytest.mark.parametrize("league", ["../etc", "ENG.1", "eng.1/../x", "", "e", "eng.1?x=1"])
def test_league_slugs_are_validated_before_any_request(league: str) -> None:
    with pytest.raises(ValueError, match="invalid ESPN league slug"):
        api.fetch_standings(league)


def test_other_inputs_are_validated() -> None:
    with pytest.raises(ValueError, match="OpenLigaDB"):
        api.fetch_openligadb_table("bl1/../x", 2025)
    with pytest.raises(ValueError, match="positive"):
        api.fetch_roster("eng.1", 0)
    with pytest.raises(ValueError, match="positive"):
        api.fetch_summary(True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="dates"):
        api.fetch_scoreboard("eng.1", "20250101-20250131")


def test_query_parameters_for_each_endpoint() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[] if "openligadb" in str(request.url) else {"matches": []})

    with _client(handler) as client:
        api.fetch_team_schedule("eng.1", 360, 2025, fixtures=True, client=client)
        api.fetch_statistics("eng.1", 2015, client=client)
        api.fetch_athlete_stats(253989, "uefa.champions", client=client)
        api.fetch_openligadb_matches("bl1", 2025, 10, client=client)
    assert seen[0].url.params["fixture"] == "true" and seen[0].url.params["season"] == "2025"
    assert seen[1].url.path.endswith("/eng.1/statistics") and seen[1].url.params["season"] == "2015"
    assert seen[2].url.host == "site.web.api.espn.com"
    assert seen[2].url.params["league"] == "uefa.champions"
    assert str(seen[3].url) == "https://api.openligadb.de/getmatchdata/bl1/2025/10"


def test_polite_interval_spaces_request_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOCCER_MIN_REQUEST_INTERVAL", "0.5")
    sleeps: list[float] = []
    monkeypatch.setattr(api.time, "sleep", sleeps.append)
    with _client(lambda request: httpx.Response(200, json={"events": []})) as client:
        api.fetch_scoreboard("eng.1", "20261101", client=client)
        api.fetch_scoreboard("eng.1", "20261102", client=client)
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 0.5
    monkeypatch.setenv("SOCCER_MIN_REQUEST_INTERVAL", "not-a-number")
    assert api._min_interval(api.SOURCES["site"]) == api.SOURCES["site"].min_interval


def test_deadline_is_enforced() -> None:
    with (
        _client(lambda request: httpx.Response(200, json={})) as client,
        pytest.raises(TimeoutError, match="exceeded"),
    ):
        api.fetch_json("site", "x", client=client, deadline=0.0)
