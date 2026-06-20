# Operational commands

The checked-in Compose services are `yamtrack` and `redis`.

## Import dry-run

```bash
docker compose exec yamtrack python manage.py import_anime_franchise --profile continuity --dry-run
```

## Import by profile

```bash
docker compose exec yamtrack python manage.py import_anime_franchise --profile continuity
docker compose exec yamtrack python manage.py import_anime_franchise --profile satellites
docker compose exec yamtrack python manage.py import_anime_franchise --profile complete
```

## Full rescan

```bash
docker compose exec yamtrack python manage.py import_anime_franchise --profile complete --full-rescan
```

## Refresh MAL provider cache during import

```bash
docker compose exec yamtrack python manage.py import_anime_franchise --profile continuity --refresh-cache
```

## Limit by user or count

```bash
docker compose exec yamtrack python manage.py import_anime_franchise --profile satellites --user-id 1 --limit 10
```

## Rebuild the Anime Series View

```bash
docker compose exec yamtrack python manage.py rebuild_anime_series_view --user-id 1
docker compose exec yamtrack python manage.py rebuild_anime_series_view --all-users --dry-run
docker compose exec yamtrack python manage.py rebuild_anime_series_view --user-id 1 --media-id 36286 --refresh-cache
```

The command uses the same canonical projection refresh service as automatic
imports, manual MAL anime additions, and deletions.

## Schedule franchise cache rebuild

```bash
docker compose exec yamtrack python manage.py shell -c "from app.tasks import build_mal_anime_franchise_payload; build_mal_anime_franchise_payload.delay('34161')"
```

## Inspect Redis cache

```bash
docker compose exec redis redis-cli keys '*anime*franchise*'
docker compose exec redis redis-cli get mal_anime_franchise_34161
docker compose exec redis redis-cli get mal_anime_franchise_34161:meta
docker compose exec redis redis-cli get mal_anime_franchise_alias_34428
docker compose exec redis redis-cli get mal_anime_franchise_34161:aliases
```

## Delete targeted cache

```bash
docker compose exec redis redis-cli del mal_anime_franchise_34161 mal_anime_franchise_34161:meta mal_anime_franchise_34161:aliases
docker compose exec redis redis-cli del mal_anime_franchise_alias_34428
```

## Inspect settings

```bash
docker compose exec yamtrack python manage.py shell -c "from django.conf import settings; names=['ANIME_FRANCHISE_GROUPING_ENABLED','ANIME_FRANCHISE_IMPORT_AUTOMATION_ENABLED','ANIME_FRANCHISE_IMPORT_AUTOMATION_INTERVAL_MINUTES','ANIME_FRANCHISE_IMPORT_AUTOMATION_PROFILE','ANIME_FRANCHISE_IMPORT_AUTOMATION_REFRESH_CACHE','ANIME_FRANCHISE_IMPORT_AUTOMATION_FULL_RESCAN','ANIME_FRANCHISE_IMPORT_AUTOMATION_LIMIT','ANIME_FRANCHISE_CACHE_TTL_DAYS','ANIME_FRANCHISE_CACHE_ALIASES_ENABLED','ANIME_FRANCHISE_CACHE_FRESH_DAYS','ANIME_FRANCHISE_BUILD_COOLDOWN_HOURS','ANIME_FRANCHISE_RETRY_AFTER_ERROR_HOURS','ANIME_FRANCHISE_QUEUE_LOCK_MINUTES','ANIME_FRANCHISE_TASK_LOCK_MINUTES','ANIME_FRANCHISE_MAX_NODES','ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION','MAL_RATE_LIMIT_PER_MINUTE']; print({n:getattr(settings,n) for n in names})"
```

## Restart services

```bash
docker compose restart yamtrack
docker compose restart redis
```

If your deployment adds separate worker or beat services, restart those deployment-specific service names too. They do not exist in the checked-in Compose files.

## Logs

```bash
docker compose logs -f yamtrack
docker compose logs -f redis
```
