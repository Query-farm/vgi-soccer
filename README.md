<p align="center">
  <a href="https://query.farm/vgi/">
    <img src="https://raw.githubusercontent.com/Query-farm/vgi-kalshi/main/docs/vgi-logo.png" alt="Vector Gateway Interface logo" width="320">
  </a>
</p>

<h1 align="center">vgi-soccer</h1>

<p align="center">
  World football (soccer) tables, scores, match events, xG and player statistics as ordinary DuckDB tables.<br>
  A <strong>read-only</strong> <a href="https://query.farm/vgi/">VGI</a> worker, built by <a href="https://query.farm">🚜 Query.Farm</a>
</p>

<p align="center">
  <a href="https://github.com/Query-farm/vgi-soccer/actions/workflows/ci.yml"><img src="https://github.com/Query-farm/vgi-soccer/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/python-3.13%2B-3776AB.svg" alt="Python 3.13+">
  <a href="https://query.farm/vgi/"><img src="https://img.shields.io/badge/VGI-read--only-6f42c1.svg" alt="Read-only VGI worker"></a>
</p>

---

`vgi-soccer` answers football questions in SQL: league tables for the Premier
League, La Liga, the Bundesliga, Serie A, Ligue 1 and about 215 other
competitions; live scores and full-season fixtures; box scores, line-ups, key
events, commentary and play-by-play with expected goals (xG); squads,
leaderboards and player season lines. It also carries every men's World Cup
since 1930 and German league data from OpenLigaDB.

Data is fetched on demand when you query, cached briefly in memory, and never
stored or rehosted. No credentials are needed. See
[Data sources, terms and affiliation](#data-sources-terms-and-affiliation)
before you use it.

## Quick start

The worker is not published to PyPI. `uvx` runs the tagged release straight from
GitHub and caches it after the first use:

```bash
uvx --from git+https://github.com/Query-farm/vgi-soccer@v0.2.0 vgi-soccer --help
```

Launch Haybarn with the catalog pre-attached:

```bash
uvx haybarn-cli \
  -cmd "INSTALL vgi FROM community; LOAD vgi; ATTACH 'soccer' (TYPE vgi, LOCATION 'uvx --from git+https://github.com/Query-farm/vgi-soccer@v0.2.0 vgi-soccer');" \
  :memory:
```

Or attach it in an existing Haybarn session:

```sql
INSTALL vgi FROM community;
LOAD vgi;
ATTACH 'soccer' (
  TYPE vgi,
  LOCATION 'uvx --from git+https://github.com/Query-farm/vgi-soccer@v0.2.0 vgi-soccer'
);
```

To work on the source, run `uv lock --check --no-sources`, then
`uv sync --no-sources` and `uv run --no-sources vgi-soccer`.
The lockfile resolves every dependency from package registries, so no sibling
checkout is needed.

## Catalog surface

The `soccer.main` schema has four tables and eighteen parameterized table
functions. Each table also has an `all_*` backing scan.

| Kind | Objects |
| --- | --- |
| Tables | `leagues`, `current_standings`, `current_matches`, `current_stat_leaders` |
| Standings | `standings()`, `bundesliga_table()` |
| Fixtures and results | `scoreboard()`, `schedule()`, `team_schedule()`, `bundesliga_matches()` |
| Match detail | `match_summary()`, `match_team_stats()`, `match_player_stats()`, `match_key_events()`, `match_commentary()`, `match_plays()` |
| Teams and players | `teams()`, `roster()`, `stat_leaders()`, `player_stats()` |
| World Cup history | `world_cup_matches()`, `world_cup_goals()` |

Three conventions apply throughout:

- **Competitions** are identified by ESPN league slugs: `eng.1` (Premier League),
  `esp.1`, `ger.1`, `ita.1`, `fra.1`, `eng.2`, `ned.1`, `por.1`, `sco.1`,
  `uefa.champions`, `uefa.europa`, `fifa.world`, `eng.w.1` (WSL) and more.
  `SELECT * FROM soccer.main.leagues` lists all of them. Where a function needs
  a league, it defaults to `eng.1`.
- **Seasons** are start years. `season := 2015` means 2015-16, and `NULL` means
  the current season.
- **Arguments**: the leading identifier (team, athlete, event, year or season) is
  positional, and everything else is named (`league := 'esp.1'`).

## Usage

### League tables

```sql
-- Today's big-five tables
SELECT league_slug, rank, team_name, games_played, goal_difference, points
FROM soccer.main.current_standings
WHERE league_slug = 'eng.1'
ORDER BY rank;

-- Leicester City's 2015-16 title: 81 points
SELECT rank, team_name, wins, draws, losses, goal_difference, points, qualification
FROM soccer.main.standings(league := 'eng.1', season := 2015)
ORDER BY rank;

-- Group tournaments return one table per group
SELECT group_name, rank, team_name, points
FROM soccer.main.standings(league := 'fifa.world')
ORDER BY group_name, rank;
```

Knockout cups without a table, such as `eng.fa`, return no rows.

### Scores, fixtures and seasons

```sql
-- Everything being played today, in every competition
SELECT league_name, home_team_name, home_score, away_score, away_team_name, status_detail
FROM soccer.main.current_matches
ORDER BY kickoff;

-- One day in one league
SELECT kickoff, home_team_name, home_score, away_score, away_team_name, winner
FROM soccer.main.scoreboard(league := 'eng.1', match_date := DATE '2026-11-08');

-- A whole season (both calendar years are merged)
SELECT kickoff, home_team_name, home_score, away_score, away_team_name
FROM soccer.main.schedule(league := 'eng.1', season := 2025)
WHERE 'Arsenal' IN (home_team_name, away_team_name)
ORDER BY kickoff;

-- One club's results and remaining fixtures (Manchester United = 360)
SELECT kickoff, home_team_name, home_score, away_score, away_team_name, state
FROM soccer.main.team_schedule(360, league := 'eng.1')
ORDER BY kickoff;
```

`state` is `pre`, `in` or `post`. Scores are `NULL` before kick-off. `winner`
is `home`, `away` or `draw` once the match is finished.

### One match in depth

Every match row carries an `event_id`, which keys the `match_*` functions:

```sql
SELECT home_team_name, home_score, away_score, away_team_name,
       home_formation, away_formation, venue_name, attendance
FROM soccer.main.match_summary(401879240);

-- Goals in order, with scorer and assister
SELECT clock_display, team_name, player_name, secondary_player_name, event_type
FROM soccer.main.match_key_events(401879240)
WHERE scoring_play
ORDER BY sequence;

-- Box score, with completion rates computed from exact counts
SELECT team_name, possession_pct, shots, shots_on_target,
       round(100.0 * accurate_passes / passes, 1) AS pass_pct
FROM soccer.main.match_team_stats(401879240);

-- Expected goals (xG) per team from the play-by-play
SELECT team_id, round(sum(expected_goals), 2) AS xg
FROM soccer.main.match_plays(401879240)
WHERE expected_goals IS NOT NULL
GROUP BY team_id;
```

`match_player_stats()` returns line-ups and per-player numbers, and
`match_commentary()` returns ESPN's text commentary.

### Teams, squads and players

```sql
SELECT team_id, team_name FROM soccer.main.teams(league := 'esp.1');

SELECT position, jersey, player_name, age, citizenship
FROM soccer.main.roster(382, league := 'eng.1');

-- 2015-16 Golden Boot race
SELECT rank, player_name, team_name, goals, matches
FROM soccer.main.stat_leaders(league := 'eng.1', season := 2015)
WHERE category = 'goals'
ORDER BY rank;

-- Combine functions: 2023-24 top scorers with their club's final position
SELECT l.rank, l.player_name, l.team_name, l.goals, s.rank AS team_rank, s.points
FROM soccer.main.stat_leaders(league := 'eng.1', season := 2023) AS l
JOIN soccer.main.standings(league := 'eng.1', season := 2023) AS s USING (team_id)
WHERE l.category = 'goals'
ORDER BY l.rank
LIMIT 10;

-- Erling Haaland's Premier League seasons (athlete 253989)
SELECT season, team_name, starts, goals, assists, shots_on_target
FROM soccer.main.player_stats(253989, league := 'eng.1')
ORDER BY season;
```

`player_stats()` returns the seasons ESPN publishes, which is roughly the last
five. Goalkeepers also get clean sheets, saves and goals conceded.

### World Cup history and German leagues (open data)

```sql
SELECT round, team1, team2, team1_goals, team2_goals,
       team1_penalties, team2_penalties, winner
FROM soccer.main.world_cup_matches(2022)
WHERE group_name IS NULL
ORDER BY match_number;

SELECT team, count(*) AS goals
FROM soccer.main.world_cup_goals(2022)
GROUP BY team
ORDER BY goals DESC;

SELECT position, team_name, points FROM soccer.main.bundesliga_table(2025);
SELECT * FROM soccer.main.bundesliga_matches(2025, matchday := 34);
```

openfootball publishes player names as written by its contributors, and a few
are spelled inconsistently. For example, some 2022 goals are credited to
"Mbappé" and others to "Kylian Mbappé". Team-level aggregates are not affected.

## Data sources, terms and affiliation

**vgi-soccer is not affiliated with, endorsed by, or sponsored by ESPN, The Walt
Disney Company, FIFA, UEFA, the Premier League, or any other league, club or
competition.** All names are used only to identify the data. The worker includes
no logos or trademarks.

| Source | What it supplies | Terms |
| --- | --- | --- |
| ESPN `site.api.espn.com`, `site.web.api.espn.com`, `sports.core.api.espn.com` | Everything except the two open-data families below | Undocumented, unofficial endpoints subject to ESPN's and Disney's terms of use, which restrict automated access. ESPN can change or withdraw them at any time. |
| [openfootball/worldcup.json](https://github.com/openfootball/worldcup.json) | `world_cup_matches()`, `world_cup_goals()` | Public domain ([CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)). |
| [OpenLigaDB](https://www.openligadb.de) | `bundesliga_table()`, `bundesliga_matches()` | Community-maintained open football data. Follow OpenLigaDB's published terms. |

How the worker treats these sources:

- It fetches data only when a query asks for it. Responses are held in memory
  for the upstream's cache lifetime and never written to disk, republished or
  rehosted.
- It identifies itself honestly, as
  `User-Agent: vgi-soccer/<version> (+https://github.com/Query-farm/vgi-soccer)`.
- It paces itself. A process starts at most about one ESPN request per second
  and runs at most two upstream requests at once.

**You are responsible for complying with the upstream terms in your
jurisdiction and for your use case.** That includes whether commercial use,
redistribution of query results, or high-volume access is permitted. If ESPN's
terms do not allow your use, restrict yourself to the openfootball and
OpenLigaDB functions or do not use this worker.

## Production HTTP deployment

Use stdio when Haybarn can launch the worker locally. Use HTTP when the worker
must be shared across hosts. The production HTTP entry point refuses to start
without a stable signing key and either authentication or an explicit decision
to allow anonymous access:

```bash
export VGI_SIGNING_KEY='a-long-random-secret-shared-by-every-replica'
export VGI_BEARER_TOKENS='replace-with-a-random-token=haybarn'

uvx --from git+https://github.com/Query-farm/vgi-soccer@v0.2.0 vgi-soccer-http \
  --host 0.0.0.0 \
  --port 8000 \
  --cors-origins 'https://sql.example.com' \
  --log-format json
```

`vgi-soccer-http` disables the description pages and cross-origin access
unless you configure them. Terminate TLS at a trusted proxy or load balancer.
Every replica must receive the same `VGI_SIGNING_KEY`. Rotate it as a
coordinated deployment, because outstanding state tokens are signed with it.

The supported authentication options are:

- `VGI_BEARER_TOKENS`: comma-separated `token=principal` pairs.
- `VGI_JWT_ISSUER` and `VGI_JWT_AUDIENCE`: JWT/JWKS authentication.
- `VGI_PROXY_PROOF_MODE=require`, with the matching VGI proxy-proof settings,
  when a trusted proxy authenticates users.

`VGI_ALLOW_ANONYMOUS=1` permits a deliberately public service. Before you run
one, read the upstream terms above. Every replica also adds its own request
load on ESPN, so keep gateway rate limits in place. The health probe is
`GET /health`.

### Container

```bash
docker build -t vgi-soccer .
docker run --rm -p 8000:8000 \
  -e VGI_SIGNING_KEY='replace-with-a-stable-random-secret' \
  -e VGI_BEARER_TOKENS='replace-with-a-random-token=haybarn' \
  vgi-soccer
```

The image runs as an unprivileged user, emits JSON logs, disables the
interactive description pages, and includes a health check.

## Reliability and operations

Every outbound request goes through one small client in `vgi_soccer/api.py`,
which applies these rules:

- A 30-second timeout applies to each request, and a 120-second deadline to each
  logical fetch, including every page of a paged fetch.
- Each request is tried at most four times. HTTP 429 and transient 5xx
  responses are retried with exponential backoff and jitter, and `Retry-After`
  is honored up to a 30-second cap per retry. Redirects are followed.
- Request starts to the same upstream are spaced out: about one per second for
  ESPN, four per second for openfootball and two per second for OpenLigaDB.
  At most two requests run at once per process.
- Responses are cached in memory, keyed by URL and query string, for the
  origin's `Cache-Control: max-age`. Each source has a floor of 30 to 300
  seconds, `no-store` responses are never cached, and the cache holds at most
  128 entries. The same lifetime is forwarded to VGI clients as result-cache
  metadata.
- Gzip bodies served without a `Content-Encoding` header, a known ESPN quirk,
  are decoded.
- Successful request timings are logged at debug level. Retries and transport
  failures are logged as warnings.

These environment variables point the worker at other roots, for hermetic tests
only: `SOCCER_ESPN_SITE_URL`, `SOCCER_ESPN_WEB_URL`, `SOCCER_ESPN_CORE_URL`,
`SOCCER_OPENFOOTBALL_URL` and `SOCCER_OPENLIGADB_URL`.
`SOCCER_MIN_REQUEST_INTERVAL` overrides the pacing interval. Never set any of
them from untrusted input.

Known upstream behavior:

- ESPN rejects date ranges for soccer, so `schedule()` fetches the season's
  two calendar years and keeps the requested season.
- ESPN's leaderboard response labels itself with the current season even when
  you request a past one. The worker reports the season you asked for.
- Some competitions, such as `ger.w.1`, `ita.w.1` and most domestic cups, have no
  standings on ESPN, so `standings()` returns no rows for them. OpenLigaDB's
  `fbl1` covers the Frauen-Bundesliga table.
- During stoppage time ESPN holds the key-event and play clock at the end of
  the period (5400 seconds for every 90'+N event). Use `clock_display` for added
  minutes.
- ESPN's per-team penalty counts, goalkeeper `shotsFaced` and roster injury
  fields are empty or contradict the match's own events, so the worker leaves
  them out. To count converted penalties, filter `match_key_events()` on
  `event_type = 'penalty---scored'`.
- openfootball records many results as a bare `[team1, team2]` list instead of
  an `ft`/`ht` object, especially before 2006. The worker reads both forms.
  Half-time scores are `NULL` when only the bare list is given.

## Development and release checks

```bash
uv lock --check --no-sources
uv sync --no-sources
uv run --no-sources ruff check .
uv run --no-sources ruff format --check .
uv run --no-sources pytest
uv build
uvx twine check dist/*
uvx --no-sources --from vgi-lint-check==2.5.0 vgi-lint lint \
  'uv run --no-sources soccer_worker.py' \
  --no-execute --no-check-links --audit-waivers --fail-on warning
```

The offline suite runs against trimmed real responses in `tests/fixtures/`.
It covers parsing, every table function, the HTTP client, catalog metadata, the
read-only guard, packaging, and a hermetic Haybarn end-to-end test that serves
the fixtures from a local HTTP server. Live upstream smoke tests are opt-in with
`uv run pytest -m live`. They also run in a serialized scheduled workflow,
together with the executing vgi-lint pass that runs every catalog example.

Publishing is driven by releases. Create a GitHub release named `vX.Y.Z` that
matches the version in `pyproject.toml`. CI then builds, validates and attests
the wheel and sdist, attaches them to the release, and publishes a
multi-platform container image to `ghcr.io/query-farm/vgi-soccer`. The package is
not published to PyPI; install it from the release tag as shown in the quick
start.

---

Copyright 2026 Query Farm LLC - https://query.farm. Released under the [MIT License](LICENSE).
