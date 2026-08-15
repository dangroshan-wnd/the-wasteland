# The Wasteland

The shared home for data ingestion, collection, and focused experimental projects. Each substantial
project is isolated in a `pj__*` directory with its own dependencies, tests, and operating notes.

## Projects

- [`pj__career-page-snapshots/`](pj__career-page-snapshots/) collects complete company job-board
  snapshots into Postgres and deploys through Prefect Managed.
- [`pj__fantasy-football-ingestion/`](pj__fantasy-football-ingestion/) owns Underdog and Pro
  Football Reference landing-data ingestion plus related data-transfer utilities.
- [`pj__biotechnology/`](pj__biotechnology/) contains biotechnology experiments.
- [`pj__flock-league/`](pj__flock-league/) contains Flock League media tooling and derived analysis.
- [`pj__rosalind/`](pj__rosalind/) contains tested Rosalind bioinformatics exercises.
- [`pj__captains-log/`](pj__captains-log/) owns the Captain's Log journal tables
  (`captains_log.landing.entries`, `captains_log.landing.processor_heartbeats`)
  as local Postgres DDL, then empty publish to Neon.

## Database names

[`naming.yml`](naming.yml) is the convention, not a table list. A `pj__*` folder
maps to `database.landing.<table>`:

- strip `pj__`, hyphens to underscores → `{project}`
- Neon / prod database: `{project}`
- local database: `{project}_dev`
- schema: `landing`

Example: `pj__captains-log` → `captains_log.landing.entries` (local db
`captains_log_dev`). Table names stay in each project's SQL. `python -m unittest
tests.test_naming` checks the mapping.

Start in a project's README and run its commands from that project directory unless the README says
otherwise. Repository-level GitHub Actions live under `.github/workflows/` and use path filters so a
project runs only its own checks.

Large raw inputs, downloaded media, credentials, local environments, and generated artifacts stay
untracked. Never place real secrets in project configuration or workflow files.
