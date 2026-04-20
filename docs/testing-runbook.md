# Testing Runbook (fork features)

This runbook is the quick reference for franchise grouping/import and notifications.

## Test modules to run

- `app.tests.services.test_anime_franchise`
- `app.tests.services.test_anime_franchise_snapshot`
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

- Changed grouping graph/snapshot/rules/UI profile:
  - run service tests + `test_media_details`.
- Changed import profiles/state/task/schedule/command:
  - run import/state/task/schedule/command tests.
- Changed entry-added notification behavior:
  - run `events.tests.test_notification` and `events.tests.test_tasks`.

## Optional manual grep checks

Use grep commands that ignore bytecode cache directories to reduce noise:

```bash
grep -R --exclude-dir=__pycache__ "PATTERN" -n src/app/services src/app/tests || true
```
