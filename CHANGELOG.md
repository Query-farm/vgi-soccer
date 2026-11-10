# Changelog

All notable changes to this project are documented here.

## [Unreleased]

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
