# Changelog

All notable changes to this project are documented here.

## 0.3.0 (2026-11-25)

- Speaks VGI protocol 3.4: require vgi-python `>=0.55.2,<0.56`; uv.lock re-locked. This release
  needs Haybarn 2.0.1 (or stock DuckDB 2.0 with `INSTALL vgi FROM query_farm`): Haybarn 2.0.0
  loads a 3.3 `vgi` extension that cannot attach it.
- SQL tests run on haybarn-unittest 2.0.1rc3.
- `serve` extra is `vgi-python[http,oauth]`; the Docker image installs it, so the image runs in
  Orchard hosted mode (`VGI_ORCHARD_HOSTED=1` with VGI_JWT_ISSUER, VGI_JWT_AUDIENCE,
  VGI_JWT_JWKS_URI and VGI_SIGNING_KEY). The HEALTHCHECK uses `HEAD /health`, which stays
  anonymous in hosted mode.

## [Unreleased]

## 0.2.2 (2026-11-16)

- Bump vgi-python to 0.52.2.
- Requires Python 3.14 (CI, Docker image and tooling moved to 3.14).
- CI runs the SQL tests over stdio, launch and HTTP transports.

## [0.2.1]

- Docs link to upstream sources (VGI183): the catalog documentation now links the data providers it reads.
- Docs give an overview, not a function list (VGI173): the catalog doc_llm now describes coverage,
  sources and how slugs, seasons, event_id and athlete_id tie the objects together instead of naming
  every table and function.

## [0.2.0]

- Speaks VGI protocol 3.3 (vgi-python 0.51); requires the current VGI DuckDB extension, 3.2
  extensions are incompatible. Table scans stay callable as functions (they are listed in the
  schema functions too).
- vgi-lint gates move to vgi-lint-check 2.5.0 (2.2.0 cannot attach 3.3 workers).

## [0.1.0]

- First release: a read-only `soccer` catalog for VGI protocol 3.2 (vgi-python 0.50).
- Tables: `leagues`, `current_standings`, `current_matches`, `current_stat_leaders`.
- ESPN-backed functions: `standings`, `scoreboard`, `schedule`, `team_schedule`, `teams`,
  `roster`, `stat_leaders`, `player_stats`, and the per-match `match_summary`,
  `match_team_stats`, `match_player_stats`, `match_key_events`, `match_commentary` and
  `match_plays` (with expected goals).
- Open-data functions: `world_cup_matches` and `world_cup_goals` (openfootball, CC0) and
  `bundesliga_table` and `bundesliga_matches` (OpenLigaDB).
- Polite HTTP client: honest User-Agent, per-source pacing, bounded retries with
  `Retry-After`, an in-process cache honoring `Cache-Control`, and base-URL overrides for
  hermetic tests.
- Hermetic Haybarn end-to-end test, live smoke tests, vgi-lint 2.2.0 structural and
  executing gates, container image and trusted-publishing workflow.
