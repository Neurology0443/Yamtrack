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

## Rebuild Anime Series View

Use dry-run first, then run the write command when the planned changes look correct:

```bash
docker compose exec yamtrack python manage.py rebuild_anime_series_view --all-users --dry-run
docker compose exec yamtrack python manage.py rebuild_anime_series_view --all-users
docker compose exec yamtrack python manage.py rebuild_anime_series_view --user-id 1 --dry-run
docker compose exec yamtrack python manage.py rebuild_anime_series_view --user-id 1 --limit 20 --dry-run
```

## Inspect Anime Series View memberships

Count tracked, projected, and unprojected MAL anime for one user:

```bash
docker compose exec yamtrack python manage.py shell -c "from app.models import Anime, AnimeSeriesViewMembership, Sources; tracked=set(Anime.objects.filter(user_id=1, item__source=Sources.MAL.value).values_list('item__media_id', flat=True)); projected=set(AnimeSeriesViewMembership.objects.filter(user_id=1, media_id__in=tracked).values_list('media_id', flat=True)); print({'tracked': len(tracked), 'projected': len(projected), 'unprojected': len(tracked-projected)})"
```

List memberships by root when a franchise appears split or merged incorrectly:

```bash
docker compose exec yamtrack python manage.py shell -c "from app.models import AnimeSeriesViewMembership; from collections import defaultdict; rows=AnimeSeriesViewMembership.objects.filter(user_id=1).order_by('root_media_id','media_id').values_list('root_media_id','media_id','display_title','group_kind','projection_version'); roots=defaultdict(list); [roots[root].append((media,title,kind,version)) for root,media,title,kind,version in rows]; [print(root, members) for root,members in roots.items()]"
```

## Autonomous franchise maintenance

The checked-in Compose service is `yamtrack`, but some deployments may split web, worker, and beat into separate services. In the all-in-one image, nginx, gunicorn, celery worker, and celery beat may run inside the same container under supervisord.

### Inspect maintenance settings

```bash
docker compose exec -T yamtrack python manage.py shell <<'PY'
from django.conf import settings

entry = settings.CELERY_BEAT_SCHEDULE.get("scan_mal_anime_franchise_maintenance")
for name in [
    "ANIME_FRANCHISE_MAINTENANCE_SCAN_ENABLED",
    "ANIME_FRANCHISE_MAINTENANCE_SCAN_INTERVAL_MINUTES",
    "ANIME_FRANCHISE_MAINTENANCE_SCAN_BATCH_SIZE",
    "ANIME_FRANCHISE_MAINTENANCE_INITIAL_SPREAD_HOURS",
    "ANIME_FRANCHISE_MAINTENANCE_REFRESH_CACHE",
    "ANIME_FRANCHISE_MAINTENANCE_LOCK_MINUTES",
    "ANIME_FRANCHISE_MAINTENANCE_ERROR_RETRY_HOURS",
    "ANIME_FRANCHISE_MAINTENANCE_REFRESH_SERIES_VIEW_ON_CHANGE",
    "ANIME_FRANCHISE_MAINTENANCE_REFRESH_SERIES_VIEW_ON_SUCCESS",
    "ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MIN_AGE_YEARS",
    "ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MIN_STABLE_SCANS",
    "ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MIN_CHANGE_AGE_DAYS",
    "ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MIN_DAYS",
    "ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MAX_DAYS",
]:
    print(f"{name}:", getattr(settings, name))
print("beat_entry_exists:", bool(entry))
print("beat_entry:", entry)
PY
```

### Inspect maintenance logs

```bash
docker compose logs --since=90m yamtrack | grep -Ei "Scan MAL anime franchise maintenance|anime franchise maintenance|Scheduler: Sending due task|succeeded|failed|error" || true
```

### Full DB summary

```bash
docker compose exec -T yamtrack python manage.py shell <<'PY'
from django.db.models import Count
from django.utils import timezone
from app.models import AnimeFranchiseMaintenanceScanState

now = timezone.now()
qs = AnimeFranchiseMaintenanceScanState.objects.all()
print({
    "total_states": qs.count(),
    "due_now": qs.filter(next_scan_at__lte=now).count(),
    "with_success": qs.filter(last_success_at__isnull=False).count(),
    "pending_first_success": qs.filter(last_success_at__isnull=True).count(),
    "with_error": qs.exclude(last_error="").count(),
})
print("by_root:")
for row in qs.values("component_root_mal_id").annotate(count=Count("id")).order_by("-count")[:20]:
    print(row["component_root_mal_id"] or "-", row["count"])
PY
```

### Due states

```bash
docker compose exec -T yamtrack python manage.py shell <<'PY'
from django.utils import timezone
from app.models import AnimeFranchiseMaintenanceScanState

for state in AnimeFranchiseMaintenanceScanState.objects.filter(next_scan_at__lte=timezone.now()).order_by("next_scan_at")[:20]:
    print(state.id, state.user_id, state.seed_mal_id, state.component_root_mal_id or "-", state.next_scan_at, state.last_success_at)
PY
```

### Error states

```bash
docker compose exec -T yamtrack python manage.py shell <<'PY'
from app.models import AnimeFranchiseMaintenanceScanState

for state in AnimeFranchiseMaintenanceScanState.objects.exclude(last_error="").order_by("-last_error_at")[:20]:
    print(state.id, state.user_id, state.seed_mal_id, state.last_error_at, state.consecutive_error_count, state.last_error[:200])
PY
```

### Inspect branch-root preservation candidates

Use this read-only diagnostic when a tracked local franchise branch appears to be covered by a parent root and you want to confirm whether the maintenance scanner currently recognizes it as a branch-root candidate. It only reads maintenance scan state and does not trigger scans.

```bash
docker compose exec -T yamtrack python manage.py shell <<'PY'
from collections import defaultdict

from app.models import AnimeFranchiseMaintenanceScanState
from app.services.anime_franchise_maintenance_scan import AnimeFranchiseMaintenanceScanService

service = AnimeFranchiseMaintenanceScanService()

user_ids = set(
    AnimeFranchiseMaintenanceScanState.objects
    .values_list("user_id", flat=True)
    .distinct()
)

branch_candidates_by_user = service._branch_root_candidate_seed_ids_by_user(
    user_ids=user_ids
)

print("branch_root_candidates:")
for user_id, seed_ids in sorted(branch_candidates_by_user.items()):
    print(f"user={user_id}", sorted(seed_ids, key=lambda value: int(value) if str(value).isdigit() else str(value)))

print()
print("states_by_root:")
for user_id in sorted(user_ids):
    groups = defaultdict(list)
    for state in (
        AnimeFranchiseMaintenanceScanState.objects
        .filter(user_id=user_id)
        .order_by("component_root_mal_id", "seed_mal_id")
    ):
        root = state.component_root_mal_id or "-"
        groups[root].append(state.seed_mal_id)

    print(f"user={user_id}")
    for root, seeds in sorted(groups.items(), key=lambda item: item[0]):
        print(" ", root, sorted(seeds, key=lambda value: int(value) if str(value).isdigit() else str(value)))
PY
```

### Next state

```bash
docker compose exec -T yamtrack python manage.py shell <<'PY'
from app.models import AnimeFranchiseMaintenanceScanState

state = AnimeFranchiseMaintenanceScanState.objects.order_by("next_scan_at").first()
if state:
    print(state.id, state.user_id, state.seed_mal_id, state.component_root_mal_id or "-", state.next_scan_at)
else:
    print("no maintenance states")
PY
```

### Manual scan

```bash
docker compose exec -T yamtrack python manage.py scan_mal_anime_franchise_maintenance --limit 10 --force
```

## Inspect MAL cover synchronization

Compare the local `Item.image` with the MAL metadata cache image. Local dev may use `docker-compose.dev.yml` and `yamtrack-dev`, but these commands use the checked-in `yamtrack` service name.

```bash
docker compose exec -T yamtrack python manage.py shell <<'PY'
from django.core.cache import cache
from app.models import Item, MediaTypes, Sources
from app.providers import mal_cache

media_id = "30831"
item = Item.objects.filter(
    source=Sources.MAL.value,
    media_type=MediaTypes.ANIME.value,
    media_id=media_id,
    season_number__isnull=True,
    episode_number__isnull=True,
).first()
payload = cache.get(mal_cache.get_anime_cache_key(media_id))

print({
    "media_id": media_id,
    "item_image": item.image if item else None,
    "cache_image": payload.get("image") if payload else None,
})
PY
```

Trigger a metadata refresh for one MAL anime:

```bash
docker compose exec -T yamtrack python manage.py shell <<'PY'
from app.tasks import refresh_mal_anime_metadata

print(refresh_mal_anime_metadata("30831"))
PY
```

Run one due maintenance scan manually:

```bash
docker compose exec -T yamtrack python manage.py scan_mal_anime_franchise_maintenance --limit 1 --force
```
