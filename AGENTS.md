# Codex Cloud execution policy

GitHub Actions is the integration authority. Codex Cloud is a targeted development
loop and must not attempt to reproduce the complete GitHub CI.

## Targeted validation

- Prepare the minimal required environment once before using `uv run --no-sync`:

  ```bash
  # tests
  uv sync --locked --no-default-groups --group test

  # lint
  uv sync --locked --only-group lint

  # tests + lint when both are needed
  uv sync --locked --no-default-groups --group test --group lint
  ```

  Use `uv run --no-sync` for the following commands and reruns. Never use
  `--no-sync` as an implicit assumption that a suitable environment already exists.
- Start with the existing tests closest to the changed files or behavior. Prefer
  deterministic, hermetic tests and a specific test or file over a whole app suite.
- For targeted Django tests that need a database, use `--nomigrations` when applying
  the complete migration graph makes the sandbox unstable:

  ```bash
  uv run --no-sync pytest <targeted-tests> --nomigrations -q
  ```

- Only add `--reuse-db` to accelerate reruns when the schema has not changed:

  ```bash
  uv run --no-sync pytest <targeted-tests> --nomigrations --reuse-db -q
  ```

- Neither `--nomigrations` nor a reused database validates the real migration path.
  After model or migration changes, leave that validation to GitHub Actions.
- Run `uv run --no-sync python src/manage.py check`. When models or migrations are
  involved, also run `uv run --no-sync python src/manage.py makemigrations --check`.
- Run targeted Ruff and djLint checks when the changed files warrant them.
- For template validation, use `djlint --lint` on the relevant scope. Do not
  introduce a repository-wide `djlint --check src/templates` gate without an
  explicit template-format baseline migration.
- Network-mocked provider or integration tests remain eligible; decide from their
  actual dependencies, not their directory name.

## Leave to GitHub Actions

Do not run the full Django suite with migrations and `--parallel`, download or run
Playwright/browser integration, run Docker smoke tests or CodeQL, access or publish
GHCR images, or deliberately make live MAL/TMDB/IGDB/Hardcover/other-provider calls
from Codex Cloud. Tests requiring a real browser or provider connectivity belong to
GitHub Actions.

Never modify, disable, skip, or weaken a valid GitHub test merely because the Codex
sandbox cannot execute it. Do not alter historical tests to make them artificially
sandbox-compatible.

## Reporting

Report every validation with exactly one honest status:

- **PASS** — the command was actually executed and succeeded.
- **FAIL** — the command was actually executed and failed.
- **NOT RUN / ENVIRONMENT LIMITATION** — the command was not executed because of
  sandbox, network, browser, Docker, or resource limits.

Never report an environment limitation as a successful test.
