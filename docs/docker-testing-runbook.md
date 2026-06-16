# Docker testing runbook

The checked-in Compose services are `yamtrack` and `redis`. The PostgreSQL Compose variant adds `db` and still uses `yamtrack` for Django commands.

## Global tests

```bash
docker compose exec yamtrack python manage.py test
```

## Targeted franchise tests

```bash
docker compose exec yamtrack python manage.py test app.tests.services.test_anime_franchise
docker compose exec yamtrack python manage.py test app.tests.services.test_anime_franchise_snapshot
docker compose exec yamtrack python manage.py test app.tests.services.test_anime_franchise_ui_pipeline
```

## Cache tests

```bash
docker compose exec yamtrack python manage.py test app.tests.services.test_anime_franchise_cache
docker compose exec yamtrack python manage.py test app.tests.services.test_anime_franchise_context
docker compose exec yamtrack python manage.py test app.tests.services.test_anime_franchise_scoped_payload
docker compose exec yamtrack python manage.py test app.tests.test_anime_franchise_cache_warmer
```

## Import tests

```bash
docker compose exec yamtrack python manage.py test app.tests.services.test_anime_franchise_import_profiles
docker compose exec yamtrack python manage.py test app.tests.test_anime_franchise_import
docker compose exec yamtrack python manage.py test app.tests.test_import_anime_franchise_command
```

## View and task tests

```bash
docker compose exec yamtrack python manage.py test app.tests.views.test_media_details
docker compose exec yamtrack python manage.py test app.tests.test_tasks
```

## Logs and runtime checks

```bash
docker compose logs -f yamtrack
docker compose logs -f redis
docker compose exec redis redis-cli keys '*anime*franchise*'
docker compose exec yamtrack celery -A config inspect active
```

This repository does not define separate `web`, `worker`, or `beat` services in the checked-in Compose files.
