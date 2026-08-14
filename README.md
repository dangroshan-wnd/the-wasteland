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

Start in a project's README and run its commands from that project directory unless the README says
otherwise. Repository-level GitHub Actions live under `.github/workflows/` and use path filters so a
project runs only its own checks.

Large raw inputs, downloaded media, credentials, local environments, and generated artifacts stay
untracked. Never place real secrets in project configuration or workflow files.
