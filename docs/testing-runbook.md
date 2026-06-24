# Testing Runbook (fork features)

This runbook is the quick reference for franchise grouping/import and notifications.

## Test modules to run

- `app.tests.services.test_anime_franchise`
- `app.tests.services.test_anime_franchise_snapshot`
- `app.tests.services.test_anime_series_view_projection`
- `app.tests.services.test_anime_franchise_ui_pipeline`
- `app.tests.services.test_anime_franchise_import_profiles`
- `app.tests.services.test_anime_import_state`
- `app.tests.views.test_media_details`
- `app.tests.test_anime_franchise_import`
- `app.tests.test_import_anime_franchise_command`
- `app.tests.test_schedules`
- `app.tests.test_tasks`
- `events.tests.test_notification`
- `events.tests.test_tasks`

## Host commands

From repo root:

```bash
cd src
python manage.py test app.tests.services.test_anime_franchise
python manage.py test app.tests.services.test_anime_franchise_snapshot
python manage.py test app.tests.services.test_anime_series_view_projection
python manage.py test app.tests.services.test_anime_franchise_ui_pipeline
python manage.py test app.tests.services.test_anime_franchise_import_profiles
python manage.py test app.tests.services.test_anime_import_state
python manage.py test app.tests.views.test_media_details
python manage.py test app.tests.test_anime_franchise_import
python manage.py test app.tests.test_import_anime_franchise_command
python manage.py test app.tests.test_schedules
python manage.py test app.tests.test_tasks
python manage.py test events.tests.test_notification
python manage.py test events.tests.test_tasks
```

Optional grouped run:

```bash
cd src
python manage.py test \
  app.tests.services.test_anime_franchise \
  app.tests.services.test_anime_franchise_snapshot \
  app.tests.services.test_anime_series_view_projection \
  app.tests.services.test_anime_franchise_ui_pipeline \
  app.tests.services.test_anime_franchise_import_profiles \
  app.tests.services.test_anime_import_state \
  app.tests.views.test_media_details \
  app.tests.test_anime_franchise_import \
  app.tests.test_import_anime_franchise_command \
  app.tests.test_schedules \
  app.tests.test_tasks \
  events.tests.test_notification \
  events.tests.test_tasks
```

## Docker commands

```bash
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test app.tests.services.test_anime_franchise"
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test app.tests.services.test_anime_franchise_snapshot"
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test app.tests.services.test_anime_series_view_projection"
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test app.tests.services.test_anime_franchise_ui_pipeline"
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test app.tests.services.test_anime_franchise_import_profiles"
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test app.tests.services.test_anime_import_state"
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test app.tests.views.test_media_details"
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test app.tests.test_anime_franchise_import"
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test app.tests.test_import_anime_franchise_command"
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test app.tests.test_schedules"
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test app.tests.test_tasks"
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test events.tests.test_notification"
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test events.tests.test_tasks"
```

## When to run which tests

- Changed grouping graph/snapshot/assembler/rules/UI profile/UI pipeline:
  - run service tests (including `app.tests.services.test_anime_series_view_projection` for Anime Series View grouping/projection semantics and `app.tests.services.test_anime_franchise_ui_pipeline` for promoted continuity + section placement flow) + `test_media_details`.
  - when changing Series View relation semantics, also verify the alternative-separation tests, weak-reroot safety tests, and parent/full-story reroot priority tests in `test_anime_series_view_projection`.
- Changed import profiles/state/task/schedule/command:
  - run import/state/task/schedule/command tests.
- Changed entry-added notification behavior:
  - run `events.tests.test_notification` and `events.tests.test_tasks`.

## Async MAL anime franchise payload cache checks

From repo root, run the targeted async franchise cache suite with `uv`:

```bash
uv run --directory . python src/manage.py test \
  app.tests.services.test_anime_franchise_cache \
  app.tests.services.test_anime_franchise_context \
  app.tests.test_tasks.BuildMALAnimeFranchisePayloadTaskTests \
  app.tests.views.test_media_details \
  app.tests.services.test_anime_franchise_snapshot
```

Run lint for the affected files:

```bash
uv run --directory . ruff check \
  src/app/services/anime_franchise_cache.py \
  src/app/services/anime_franchise_context.py \
  src/app/services/anime_franchise_graph.py \
  src/app/services/anime_franchise_snapshot.py \
  src/app/tasks.py \
  src/app/views.py \
  src/app/tests/services/test_anime_franchise_cache.py \
  src/app/tests/services/test_anime_franchise_context.py \
  src/app/tests/test_tasks.py \
  src/app/tests/views/test_media_details.py
```
