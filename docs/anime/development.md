# Developing Anime

General Yamtrack setup is documented in the [main development guide](../development.md).
This page only covers the conventions that are specific to the Anime subsystem
and this fork.

## Fork organization

The `dev` branch follows upstream `dev` and does not receive work that is specific
to this fork. The fork's integration and reference branch is `main`.

Fork-specific changes normally start from `main` and return to `main` through a
pull request. Feature and fix pull requests are normally squash-merged. An
upstream sync from `dev` to `main` keeps a merge commit so the upstream integration
remains visible in the repository history.

## Database compatibility

Anime changes must continue to work with both SQLite and PostgreSQL. Use the
Django ORM for database access. Do not add SQL or behavior tied to one database
unless there is an explicit need and suitable coverage for both backends.

## Anime migrations

A schema change owned by Anime creates a migration in `src/anime/migrations/`.
Anime migration numbers are independent from the numbers used by other Yamtrack
applications.

Once a migration has been merged or distributed, it is part of the project's
history. Do not rewrite it just to make it cleaner. Create a new migration for the
next schema change.

## How changes are validated

Continuous integration groups validation by what it checks:

```text
Application tests
├── SQLite
└── PostgreSQL

Real provider tests
└── external provider connectivity

Additional checks
├── lint
├── security analysis
└── Docker build
```

The application tests run with SQLite and PostgreSQL. This checks that application
behavior does not depend on which supported database is selected. Lint, security,
and image-build workflows provide separate checks around the application tests.

## External provider tests

Tests that deliberately contact services such as MAL or Open Library are run
separately. This makes it easier to tell the difference between a Yamtrack
regression and a temporary problem with an external service.

These tests use the `live_provider` Django tag. They are separate from the
SQLite/PostgreSQL matrix, but they remain blocking checks. A failure must still be
investigated.

Reserve `@tag("live_provider")` for a test that intends to check a real external
provider over the network. If network access is accidental and is not the point of
the test, mock that provider boundary instead.

## Common validation commands

After completing the general setup, these commands cover common Anime checks:

```bash
uv run python src/manage.py check
uv run python src/manage.py makemigrations --check
uv run python src/manage.py test anime
```

GitHub Actions remains the integration authority for SQLite/PostgreSQL
compatibility and real external provider checks.
