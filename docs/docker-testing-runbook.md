# Docker testing runbook

The checked-in Compose services are `yamtrack` and `redis`. The PostgreSQL Compose variant adds `db` and still uses `yamtrack` for Django commands.

This is the Docker equivalent of the complete matrix in [testing runbook](testing-runbook.md). Keep the module families aligned with that file.

## Global tests

```bash
docker compose exec yamtrack python manage.py test
```

## Franchise grouping and snapshot

```bash
docker compose exec yamtrack python manage.py test app.tests.services.test_anime_franchise app.tests.services.test_anime_franchise_graph app.tests.services.test_anime_franchise_snapshot app.tests.services.test_anime_franchise_ui_pipeline app.tests.services.test_anime_franchise_context app.tests.test_anime_franchise_footer app.tests.views.test_media_details
```

## Franchise import and automation

```bash
docker compose exec yamtrack python manage.py test app.tests.services.test_anime_franchise_import_profiles app.tests.services.test_anime_franchise_import_build_session app.tests.services.test_anime_import_state app.tests.test_anime_franchise_import app.tests.test_import_anime_franchise_command app.tests.test_schedules app.tests.test_tasks
```

## Franchise cache and provider metadata

```bash
docker compose exec yamtrack python manage.py test app.tests.services.test_anime_franchise_cache app.tests.services.test_anime_franchise_cache_builder app.tests.services.test_anime_franchise_scoped_payload app.tests.test_anime_franchise_cache_warmer app.tests.test_item_image_sync
```

## Franchise maintenance and discovery notifications

```bash
docker compose exec yamtrack python manage.py test app.tests.services.test_anime_franchise_maintenance_cadence app.tests.services.test_anime_franchise_maintenance_scan app.tests.test_anime_franchise_discovery app.tests.test_manual_anime_franchise_task events.tests.test_notification events.tests.test_tasks
```

## Anime Series View

```bash
docker compose exec yamtrack python manage.py test app.tests.services.test_anime_series_view app.tests.services.test_anime_series_view_projection app.tests.services.test_anime_series_view_franchise_refresh app.tests.services.test_anime_series_view_refresh_queue app.tests.services.test_anime_series_view_refresh_triggers app.tests.test_anime_series_view_import_integration app.tests.test_anime_series_view_task app.tests.test_rebuild_anime_series_view_command app.tests.views.test_anime_series_view
```

## MAL release-date notifications

```bash
docker compose exec yamtrack python manage.py test events.tests.test_anime_release_date_notifications events.tests.test_notification events.tests.test_tasks
```

## Logs and runtime checks

```bash
docker compose logs -f yamtrack
docker compose logs -f redis
docker compose exec redis redis-cli keys '*anime*franchise*'
docker compose exec yamtrack celery -A config inspect active
```

This repository does not define separate `web`, `worker`, or `beat` services in the checked-in Compose files.
