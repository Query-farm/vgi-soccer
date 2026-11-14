# Soccer notebooks

[01 · A level score can still have a winner](01_scores_goals_and_shootouts.ipynb) uses the complete 2022 men's World Cup from openfootball (CC0). It separates 90-minute scores, cumulative extra-time scores and shoot-out kicks, reconciles the worker's match and goal tables, and compares all matches with knockout matches (including third place).

## Run from this directory alone

Install [uv](https://docs.astral.sh/uv/) and use Python 3.13 or 3.14 (the worker is explicitly pinned to 3.13). Internet access is needed initially for packages, the VGI extension and the tagged worker. No local worker source, global Jupyter kernel, credentials or build is required.

```sh
cd notebooks
uv sync --locked
uv run --locked python execute.py
uv run --locked python execute.py --parameters '{"ROUND_SCOPE":"knockout"}' --output-dir validation/knockout
uv run --locked python execute.py --parameters '{"DATA_MODE":"live"}' --output-dir validation/live
uv run --locked python -m ipykernel install --user --name vgi-soccer-notebooks --display-name 'Python (vgi-soccer notebooks)'
```

Open the notebook in Jupyter using that kernel and this directory as cwd. Parameters and analytical SQL stay visible; implementation cells carry portable folding metadata. Restart and Run All after edits. `execute.py` uses its own environment's temporary kernel, writes atomically only on success, rejects unknown parameters and requires a separate destination for overrides. Experiment copies include branding, recordings, helper, runner, constraints and lock.

The literal ATTACH runs `uvx --python 3.13 --from git+https://github.com/Query-farm/vgi-soccer.git@v0.2.0 --constraints worker-constraints.txt vgi-soccer`. Tag v0.2.0 resolves to `2a1d05265979246de2e0add699411eb06e84e278`; uv caches it. Tested with Haybarn 2.0.0rc11, SDK 0.51.0/RPC 0.53.1 and Arrow 25.0.1. Upgrades require changing the visible pin/constraints and rerunning both default and experiment; root dependencies are untouched.

## Provenance and boundaries

`recordings/worldcup-2022.json` is the unchanged actual [openfootball 2022 response](https://raw.githubusercontent.com/openfootball/worldcup.json/master/2022/worldcup.json), captured 2026-11-14 at 10:22:21 UTC; manifest records its SHA256 and byte count. The [upstream repository](https://github.com/openfootball/worldcup.json) publishes this historical collection under CC0. Match dates and kickoff strings are local source labels, not UTC timestamps. The capture timestamp is UTC and is not a match timestamp.

Default replay routes the real worker's supported `SOCCER_OPENFOOTBALL_URL` override to `recorded_api.py`. Only `/2022/worldcup.json` and one successful fetch are allowed. Both worker table functions share the worker's five-minute HTTP cache; each is materialized once, before local DataFrame reads. `ROUND_SCOPE` filters local data and never changes request coverage. This is a complete fixed tournament request, not an unbounded catalog request controlled by LIMIT.

Live mode performs that exact public read afresh, fails on errors or unexpected requests, and never uses a recording as fallback. It writes its actual body, SHA256, receive timestamp and request audit under ignored `artifacts/`. The historical source can be corrected later. No ESPN or OpenLigaDB endpoints are called. Goal-event names are not normalized into player identities; no scorer ranking is attempted. Penalty goals during play count as goals; shoot-out kicks do not. Extra-time columns are cumulative scores, not additional goals. A knockout winner includes the third-place match winner and does not always mean advancement.

Validation logs, extracted charts, experiments and runtime artifacts are ignored. The main notebook retains successful embedded outputs. See [STANDARD.md](STANDARD.md).

## Repository validation

The unchanged source passes 108 offline tests (97.12% coverage), including a real Haybarn end-to-end test, Ruff lint/format, isolated entrypoints, wheel/sdist build and Twine checks, and a runtime dependency audit with no known vulnerabilities. Structural metadata passes at 98/100, L1: two existing informational VGI809 possible-relationship findings; no errors or warnings. Broad live ESPN examples are not run; this notebook's one-read openfootball live path is validated separately. Docker's CI image smoke test could not run because the local Docker Desktop daemon reports that it is unable to start; no daemon or unrelated container was restarted.
