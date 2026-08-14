# Career Page Snapshots

Career Page Snapshots is a small, production-style data engineering project that collects complete job-board observations from configured company career sites and stores each company snapshot in Postgres.

V1 uses Python 3.12, Prefect 3, Postgres, Alembic, pytest, Ruff, uv, Docker, and GitHub Actions.
Development runs are manual and use local Docker Postgres. Production runs on Prefect Managed
infrastructure, pulls the exact committed Wasteland code, and writes to Neon PostgreSQL. Its
smoke-tested schedule runs daily at 9 PM America/New_York.

## Architecture

```mermaid
flowchart LR
    C[companies.yml] --> F[Prefect ingestion flow]
    F --> A[Four source adapters]
    A --> N[Validated normalized inventories]
    N --> P[Idempotent Postgres writer]
    P --> LD[(Local Postgres landing table)]
    P --> LP[(Neon production landing table)]
    LD --> D[Citadel dbt source]
    LP --> D
    G[Public Wasteland repository] --> M[Prefect Managed runtime]
    M --> F
```

Configuration is validated before dispatch. Prefect then collects each company independently and
writes an immutable, versioned JSONB snapshot through parameterized Psycopg SQL. Alembic owns the
landing table definition. [The Citadel](https://github.com/dangroshan-wnd/the-citadel) declares that
table as a dbt source without claiming analytical models that do not exist yet.

The completed V1 implementation records are retained with the standalone project notes in the
Athenaeum.

## Prerequisites and setup

- Git, Docker Desktop, and Python 3.12
- `uv` 0.10.7 (the same version used by CI and the Docker build)
- PowerShell for the examples below; equivalent environment commands work in other shells

From the Wasteland repository root, enter this project before running the commands below:

```powershell
Set-Location .\pj__career-page-snapshots
```

Create the locked development environment:

```powershell
uv sync --locked --dev
.\.venv\Scripts\Activate.ps1
```

Create `.env` manually because V1 intentionally does not track an example environment file. Use
URL-safe credentials so the password can be embedded in Postgres URLs without extra encoding:

```dotenv
APP_ENV=dev
COMPANIES_FILE=companies.yml
HTTP_TIMEOUT_SECONDS=30
POSTGRES_DB=career_page_snapshots_dev
POSTGRES_USER=career_page_snapshots
POSTGRES_PASSWORD=replace-with-a-url-safe-local-password
POSTGRES_PORT=5432
DATABASE_URL=postgresql://career_page_snapshots:replace-with-a-url-safe-local-password@127.0.0.1:5432/career_page_snapshots_dev
TEST_DATABASE_URL=postgresql://career_page_snapshots:replace-with-a-url-safe-local-password@127.0.0.1:5432/career_page_snapshots_test
NEON_DATABASE_URL=postgresql://production-user:replace-with-neon-password@your-neon-host/production-db?sslmode=require
```

`.env` is ignored by Git. `NEON_DATABASE_URL` is a local setup convenience and is never read by the
production flow directly. Production deployment metadata contains only
`DATABASE_URL_SECRET_BLOCK=neon-database-url`; the running flow loads that Prefect Secret into
process memory and validates it without placing the URL in deployment job variables. Local runs
continue to use `DATABASE_URL`. Both environments use the fixed `landing` schema; application code
does not switch database behavior based on `APP_ENV`.

## Initial company selection

The following four companies are the definitive V1 scope:

| Company | Adapter | Slug | Canonical public source |
| --- | --- | --- | --- |
| Netflix | Eightfold | `netflix` | `https://explore.jobs.netflix.net/api/apply/v2/jobs?domain=netflix.com` |
| Kalshi | Greenhouse | `kalshi` | `https://boards-api.greenhouse.io/v1/boards/kalshi/jobs?content=true` |
| Google | Google Careers | `google` | `https://www.google.com/about/careers/applications/jobs/results` |
| Palantir | Lever (global) | `palantir` | `https://api.lever.co/v0/postings/palantir?mode=json` |

These companies exercise four distinct V1 source paths. Kalshi's Greenhouse board-list response includes the full board in one response when `content=true`; that endpoint does not expose board-list pagination. Palantir has a large board and its Lever endpoint supports bounded `skip`/`limit` pagination. Netflix exposes a paginated Eightfold candidate-site JSON endpoint, including a separate detail route when descriptions are available. Google exposes server-rendered, paginated careers search results. V1 requires a complete public job inventory for every successful company collection; descriptions remain optional. Live endpoint availability was manually checked during setup but will not be part of the deterministic test suite.

Meta, NVIDIA, and Microsoft are noted V2 candidates only. V1 will not implement, prototype, configure, or test their source integrations. In particular, Meta-specific GraphQL retrieval, Workday support for NVIDIA, Microsoft source handling, and Playwright/browser automation remain out of scope.

If an active endpoint disappears, first confirm that the company has not changed its careers platform, host, or board identifier. An unavailable or incomplete source must produce a company-level collection failure rather than an empty or partial snapshot. Parser tests must continue to use committed fixtures rather than depending on the live companies.

## Configuration

Runtime configuration is loaded from environment variables, with a local `.env` file supported for
development. A Postgres DSN is required: local execution supplies `DATABASE_URL`, while production
supplies `DATABASE_URL_SECRET_BLOCK` naming a Prefect Secret retrieved only inside the running
process. `APP_ENV` accepts `dev` or `prod`, `HTTP_TIMEOUT_SECONDS` must be greater than zero and no
more than 300, and `COMPANIES_FILE` defaults to `companies.yml`. Relative company-file paths are
resolved from the process working directory; deployments that start elsewhere must provide an
explicit path.

Company configuration is validated before collection begins. Every entry requires a nonempty `name`, a supported `scraper`, and a source `slug`. Lever entries may set `region` to `global` or `eu`. Eightfold entries also require `careers_host` and `domain` as DNS names without a URL scheme or path. The Google adapter owns its official source URL and requires the `google` slug. Unknown fields, duplicate case-normalized company names, duplicate `(scraper, slug)` identities, empty lists, and lists of 10 or more companies are rejected.

The configured company name is its stable V1 history identity. Changing capitalization alone is rejected as a duplicate within one file; changing the stored name between runs starts a separate history and should be treated as a deliberate migration.

## Collection contract

Every adapter returns one validated, all-or-nothing `CollectionResult`. Jobs require a source ID, title, HTTP(S) URL, and JSON-compatible raw source record. `location` and `department` are collections so multi-valued source data is retained; descriptions are optional. Duplicate external IDs, malformed required jobs, non-JSON raw data, nonsequential page metadata, or a mismatch between the source-reported count and collected jobs invalidates the company collection.

Persisted JSONB uses a versioned envelope containing `schema_version`, `job_count`, source identity and canonical URL, bounded page/retrieval metadata, and normalized jobs with their raw records. A valid source response reporting zero jobs produces a successful empty envelope. Network retry policy is limited to transport failures, HTTP 408/429, and 5xx responses with bounded attempts and exponential backoff; ordinary 4xx responses and deterministic configuration or parsing failures are not retried.

## V1 source adapters

- Greenhouse collects Kalshi's complete board from the documented public board-list endpoint with `content=true` and verifies `meta.total`.
- Lever collects Palantir using bounded `skip`/`limit` pagination until a short or empty terminal page. Repeated pages and duplicate job IDs fail the collection.
- Eightfold collects Netflix using bounded `start`/`num` pagination and requires the reported count
  to remain stable and match the final unique inventory. If count/order drift proves the live board
  changed mid-read, it restarts the complete inventory once. Per-job detail enrichment is disabled
  in V1, so descriptions are populated only when present in inventory results.
- Google Careers parses the official server-rendered result cards, numeric detail IDs, displayed
  locations, result ranges, and sequential next-page links. It requires every page to continue the
  prior range and the final unique job count to match the reported total. A successful response that
  temporarily lacks the results document gets one bounded same-page retry; structural job/count
  errors remain hard failures. The retained raw payload is a bounded structured representation of
  each rendered card rather than the full presentation HTML.

Paginated adapters pause briefly between successful pages and record their page size/cursor and delay metadata. All safety bounds, repeated-page detection, count checks, and parser failures protect the all-or-nothing snapshot rule. Live sources are used only for explicit smoke checks; deterministic pytest runs use sanitized committed fixtures.

## Local Postgres

Local development uses the official `postgres:17.10-bookworm` image, bound only to `127.0.0.1`, with a health check and the named `career-page-snapshots-postgres-dev-data` volume. PostgreSQL 17 remains supported through 2029, while the exact minor/image distribution is pinned for reproducibility.

After creating `.env`, start the service:

```powershell
docker compose up -d postgres
docker compose ps
docker compose logs postgres
```

Open `psql` inside the running container using the configured user and database:

```powershell
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

The application and Alembic commands use the same `DATABASE_URL` from `.env`. `POSTGRES_PORT`
defaults to `5432`; if it is changed, update the port in `DATABASE_URL` and `TEST_DATABASE_URL` to
match.

Stop and recreate the container without deleting stored development data:

```powershell
docker compose down
docker compose up -d postgres
```

Do not add `--volumes` to `docker compose down` unless the development database is intentionally being discarded. The official image applies `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` only when initializing an empty data directory. Changing them in `.env` does not rewrite credentials inside an existing named volume.

### Sync Neon snapshots locally

With the virtual environment activated, copy all production landing snapshots into local Postgres:

```powershell
python sync_neon.py
```

The script reads `DATABASE_URL` and `NEON_DATABASE_URL` from `.env`, starts the Compose Postgres
service, upgrades the local schema, and copies snapshots in batches. Existing
`(company_name, collection_key)` rows are skipped, so running it repeatedly imports only missing
snapshots. Neon is read-only during this operation. As a write-safety check, the destination must
use `localhost`, `127.0.0.1`, or `::1`, and its database name must end with `_dev`.

Use `python sync_neon.py --help` for the optional batch-size and Docker-start controls.

## Database migrations

Alembic reads `DATABASE_URL` from the process environment and uses Psycopg 3. Load the local value from `.env` in PowerShell, apply all migrations, and inspect the current revision:

```powershell
$env:DATABASE_URL = (Get-Content .env | Where-Object { $_ -like 'DATABASE_URL=*' }).Split('=', 2)[1]
uv run alembic upgrade head
uv run alembic current
Remove-Item Env:DATABASE_URL
```

The initial migration creates `landing.career_page_snapshots` with UUID identity, source/company identifiers, an aware capture timestamp, nonnegative job count, JSONB payload, and idempotent `(company_name, collection_key)` uniqueness. It also creates company/capture-time and capture-time indexes. Downgrade removes only the table and its indexes; it intentionally preserves the `landing` schema because the schema may predate this project or contain unrelated objects.

Migration upgrade/downgrade verification is destructive and must use the dedicated disposable
database named by `TEST_DATABASE_URL`. Its database name must end with `_test` or the test refuses
to run. Create the test database once, then run the marked suite:

```powershell
docker compose exec postgres sh -c 'createdb -U "$POSTGRES_USER" career_page_snapshots_test'
$env:TEST_DATABASE_URL = (Get-Content .env | Where-Object { $_ -like 'TEST_DATABASE_URL=*' }).Split('=', 2)[1]
uv run pytest -m integration
Remove-Item Env:TEST_DATABASE_URL
```

The default `uv run pytest` command continues to exclude integration tests.

Initialize or upgrade the dedicated Neon production database by temporarily mapping the local
setup value to the application's standard variable:

```powershell
$env:DATABASE_URL = (Get-Content .env | Where-Object { $_ -like 'NEON_DATABASE_URL=*' }).Split('=', 2)[1]
uv run alembic upgrade head
uv run alembic current
uv run career-page-snapshots-check
Remove-Item Env:DATABASE_URL
```

This operation is additive at the current revision: it creates the `landing` schema, snapshot
table, indexes, uniqueness constraint, and Alembic version record when they do not already exist.
Do not run migration downgrade against Neon production.

Run the complete deterministic quality and offline metadata checks:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest -m "not integration"
uv run career-page-snapshots-deployment validate
```

Live adapter checks are deliberately outside pytest because public inventories and presentation
markup change.

## Manual development run

With Postgres healthy and Alembic at `head`, run the non-destructive readiness checks:

```powershell
uv run career-page-snapshots-check
```

Then run all configured companies through the unscheduled Prefect flow:

```powershell
uv run career-page-snapshots
```

The command prints a structured summary. Each successful company writes one row to
`landing.career_page_snapshots`; a failed company is listed under `failures` without preventing
other companies from completing. Inspect the newest stored observations with:

```sql
SELECT company_name, captured_at, job_count, source_url
FROM landing.career_page_snapshots
ORDER BY captured_at DESC, company_name;
```

The first complete V1 development run on August 12, 2026 successfully persisted all four
configured sources. Live job counts are intentionally not documented as fixed expectations because
company inventories change continuously.

## Application container

Build the locked runtime image and run a credential-free import smoke test:

```powershell
docker build -t career-page-snapshots:dev .
docker run --rm career-page-snapshots:dev python -c "import career_page_snapshots"
```

The image contains only runtime dependencies, the installed application, and `companies.yml`. It
runs as a non-root user and defaults to the `career-page-snapshots` command. `.env`, tests, local
Prefect state, and repository metadata are excluded from the build context.

The optional Compose `app` profile supplies a container-network database URL using the `postgres`
service name and internal port `5432`; it does not use the host's published Postgres port. Use a
URL-safe local development password, then run readiness or ingestion inside the Compose network:

```powershell
docker compose --profile app run --rm app career-page-snapshots-check
docker compose --profile app run --rm app career-page-snapshots
```

These commands use the local `.env` only at runtime. Docker does not copy that file into the image.

## Prefect Managed production deployment

`prefect.yaml` defines one runnable deployment named `production`. Prefect Managed supplies the
runtime, clones the public Wasteland repository at the exact commit registered by CI, installs the
pinned runtime set from `pj__career-page-snapshots/requirements-prod.txt`, changes into that
subdirectory, and injects production configuration. The deployment allows manual runs, and its
`daily-9pm-eastern` schedule is active. Activation followed a successful production run and direct
Neon verification on August 12, 2026. The Managed job uses Prefect's official
`prefect-client:3-python3.12` image so the interpreter remains compatible with the project's Python
3.12 contract; it does not use the repository's custom Dockerfile.

The contract uses these Prefect Cloud resources:

- Managed work pool: `career-page-snapshots-managed`
- Secret block containing the Neon URL: `neon-database-url`

The public repository requires no GitHub credential for cloning. The Neon URL must include TLS
configuration such as `sslmode=require`. Create its Secret block in the Prefect Cloud UI under
Blocks. Deployment configuration must name the Secret block rather than template its value into a
job variable; do not copy the value into `prefect.yaml`, GitHub Actions, logs, or commits.

Validate the YAML structure and flow import completely offline:

```powershell
uv run career-page-snapshots-deployment validate
```

Regenerate the production dependency export after changing `pyproject.toml` or `uv.lock`:

```powershell
$env:UV_CACHE_DIR = (Resolve-Path .uv-cache).Path
uv export --locked --no-dev --no-editable --no-header --no-hashes --format requirements.txt --output-file requirements-prod.txt
```

For GitHub Actions registration, add repository secrets `PREFECT_API_URL` and `PREFECT_API_KEY`.
The workflow creates the Managed work pool if necessary and runs `prefect deploy --all --no-prompt`.
The API key should belong to a Prefect service account with only the workspace access required to
manage this deployment, work pool, and runs.

Production activation sequence:

1. Initialize Neon with `alembic upgrade head` and pass `career-page-snapshots-check`.
2. Create the Neon Prefect Secret block and the two GitHub Actions repository secrets.
3. Run the deployment workflow manually with `deploy=true`, or push a deployment-related change to
   `main`.
4. In Prefect Cloud, run `career-page-snapshots/production` manually.
5. Query Neon and verify one new row for Netflix, Kalshi, Google, and Palantir, with plausible
   non-partial job counts and no company failures in the Prefect result.
6. Activate the `daily-9pm-eastern` schedule in version-controlled YAML and redeploy. This was
   completed after the successful August 12, 2026 smoke test; future changes must preserve the
   code/UI match.

Docker and Compose remain supported for local development; no custom image or container registry
is used by the Prefect Managed production path.

## Failure and idempotency behavior

Application/company configuration failures occur before dispatch and fail the flow. After dispatch,
collection, parsing, and persistence failures are isolated to their company. Successful companies
still persist, and the flow returns a Prefect `Completed` state whose structured status is
`completed_with_errors`; this also applies when every company fails.

Each flow run establishes one aware UTC `captured_at` and uses its Prefect flow-run ID as the
`collection_key` for every company. Task retries preserve both values. The database uniqueness rule
on `(company_name, collection_key)` makes repeated writes safe: a conflict returns the first stored
observation without updating it. Empty but valid boards persist with `job_count = 0`; incomplete or
malformed inventories never persist.

## Adding another supported company

1. Confirm the company uses one of the four implemented public adapters and manually verify its
   stable source identifier and global-inventory behavior.
2. Add one validated entry to `companies.yml`. Treat `name` as permanent history identity; renaming
   it starts a new history.
3. Add or update sanitized fixtures and deterministic adapter tests when the source exposes a shape
   not already covered.
4. Run the quality suite, readiness check, and one explicit live flow. Verify its newest landing row
   and JSONB `job_count` before merging.

Do not silently substitute another company or persist a partial board when a source is difficult.

## CI and deployment registration

Changes under this Wasteland subproject run locked Ruff checks, deterministic unit tests, disposable
Postgres migration/persistence integration tests, offline Prefect deployment validation, and an
application-image smoke test; they require no external database or Prefect credentials. The
separate main-branch workflow validates the runnable production contract and verifies that
`requirements-prod.txt` still matches `uv.lock`. It ensures the Managed work pool exists and
registers the deployment when both `PREFECT_API_URL` and `PREFECT_API_KEY` exist, skips cleanly on
automatic pushes without them, and fails a manually requested deployment when they are missing.

## Troubleshooting

- **Docker cannot find its engine:** start Docker Desktop and wait for its Linux engine to become
  ready before running `docker compose`.
- **Host port 5432 is unavailable or forbidden:** choose an unused `POSTGRES_PORT` such as `55432`
  and update both local database URLs to the same port. Containers still use port `5432` internally.
- **Authentication fails after editing `.env`:** Postgres initialization variables apply only to an
  empty named volume. Either restore the original values, alter the existing role password, or
  intentionally recreate the disposable development volume.
- **Readiness says the table is missing:** load `DATABASE_URL` and run `uv run alembic upgrade head`.
- **A public source fails:** inspect the company-level error, confirm the official source has not
  changed platform/host/identifier, and update the adapter plus sanitized fixtures. Never interpret
  an unavailable or structurally changed board as a valid empty inventory.
- **Integration tests refuse to run:** set `TEST_DATABASE_URL` to a dedicated disposable database
  whose name ends in `_test`; the guard intentionally rejects dev and prod targets.
- **Prefect cannot clone GitHub:** confirm the Wasteland repository is public and the registered
  commit SHA exists.
- **Prefect cannot connect to Neon:** confirm `neon-database-url` contains the complete URL with TLS,
  the Neon branch is active, and any Neon network restrictions allow Prefect Managed outbound
  traffic.
- **A push validates but does not deploy:** configure the repository's `PREFECT_API_URL` and
  `PREFECT_API_KEY` Actions secrets, then run the deployment workflow manually with `deploy=true`.

## Intentional V1 boundaries

- Definitive companies are Netflix, Kalshi, Google, and Palantir. Meta, NVIDIA, and Microsoft are
  V2 candidates only.
- No Workday, Meta-specific GraphQL, Microsoft-specific integration, or Playwright/browser
  automation exists in V1.
- Prefect Managed, the production work-pool contract, public Wasteland pull, Neon secret injection,
  and the active 9 PM Eastern schedule are configured.
- No custom production image, registry publishing workflow, persistent Prefect worker, or locally
  exposed production database exists.
- The Citadel declares the landing source only. `staging.stg_job_postings`,
  `marts.job_postings_history`, and derived history fields remain documented follow-up work there.

## Next production milestones

1. Complete the one-time Prefect/Neon setup, verify a manual Managed run, and commit schedule
   activation.
2. Add run-state and per-company success/failure alerting, including detection of the flow's
   structured `completed_with_errors` result.
3. Build `staging.stg_job_postings` from the versioned landing JSONB source, with explicit identity
   and reinstated-posting semantics before starting the history mart.
