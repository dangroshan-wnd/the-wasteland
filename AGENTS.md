# Working in The Wasteland

Data ingestion, collection, and experiments. Each project is a `pj__*` folder
with its own dependencies, tests, and operating notes. This repo is **public**.

## Start here

- Read [README.md](README.md) for the project list, then the README of the
  `pj__*` project you are changing. Run commands from that project's folder
  unless its README says otherwise.
- [databases.yml](databases.yml) lists the databases on the local `dgdb`
  Postgres cluster: one per project that owns Postgres.
- Shared conventions: [home/docs/standards.md](../home/docs/standards.md).

## Rules

- This repo owns landing and raw writes. Transformations, dbt models, and
  tests on that data belong in [the-citadel](../the-citadel).
- Keep each project's changes inside its own `pj__*` folder. CI in
  `.github/workflows/` uses path filters so each project runs only its own
  checks. Keep those filters correct when you add a project.
- Keep raw inputs, downloaded media, local environments, generated files, and
  credentials out of Git. The repo is public.

## TODO

- [Dan: add any rules for the whole repo, such as how to add a new `pj__*`
  project or which projects are dormant.]
