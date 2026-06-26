# Anime franchise maintenance

Autonomous franchise maintenance keeps tracked MAL anime franchise data fresh without relying on page visits or import runs.

Related docs: [architecture overview](architecture-overview.md), [franchise cache](anime-franchise-cache.md), [franchise import](anime-franchise-import.md), [Anime Series View](anime-series-view.md), [debugging runbook](anime-franchise-debugging-runbook.md), and [operational commands](operational-commands.md).

## Product behavior

The autonomous maintenance scanner:

- runs in the background through Celery Beat as `Scan MAL anime franchise maintenance`;
- ensures persistent maintenance scan state exists for eligible tracked MAL anime;
- selects a bounded batch of due state rows;
- builds one canonical franchise snapshot per processed seed with a shared build session;
- rebuilds the user-agnostic detail-page franchise cache payload;
- processes discovery state for newly visible missing franchise entries;
- can queue franchise discovery notifications for eligible new entries after the
  user's discovery baseline;
- refreshes Anime Series View memberships when configured or when structure changes;
- records success, errors, component root, fingerprint, and the next scan time.

It is operational maintenance for existing tracked MAL anime. It is not import automation and it does not directly create missing `Anime` rows.

## Why this maintenance exists

Page visits and imports are not enough:

- users may not open old detail pages;
- MAL can change related-anime relations after an item was cached;
- new sequels, specials, movies, alternatives, or spin-offs can appear;
- Anime Series View memberships can become stale;
- discovery notifications need a reliable background observation path;
- large franchise rebuilds must stay out of the request path.

Maintenance provides that background observation path while keeping detail-page requests fast.

## Execution surfaces

```text
Celery task:
Scan MAL anime franchise maintenance

Management command:
python manage.py scan_mal_anime_franchise_maintenance --limit 10 --force
```

The Celery task respects `ANIME_FRANCHISE_MAINTENANCE_SCAN_ENABLED`. When disabled, it returns a skipped result.

The management command runs the same `AnimeFranchiseMaintenanceScanService`. `--force` only hides the disabled-setting warning for manual runs. It does not mean “scan every state immediately”. `--limit` controls the due-state batch size for that run.

## Scan state lifecycle

`AnimeFranchiseMaintenanceScanState` stores one row per user and seed MAL anime ID.

| Field | Meaning |
| --- | --- |
| `user` | User whose library contains the tracked MAL anime. |
| `seed_mal_id` | Tracked MAL anime ID used as the maintenance seed. |
| `component_root_mal_id` | Last resolved canonical component root for the seed. Blank until a successful scan resolves it. |
| `next_scan_at` | Due time used by the scanner. |
| `last_scanned_at` | Last time the state was attempted or covered. |
| `last_success_at` | Last successful maintenance observation. |
| `last_error_at` | Last critical or partial failure time. |
| `last_change_at` | Last time the maintenance fingerprint or root changed. |
| `last_result_fingerprint` | Last maintenance fingerprint for root, discovery-visible data, and tracked member coverage. |
| `last_error` | Short error text for the last failure. |
| `consecutive_stable_scans` | Successful scans since the last detected change. |
| `consecutive_error_count` | Consecutive failures used for retry backoff. |

Uniqueness:

```text
one state per user + seed_mal_id
```

Indexes support:

- due lookup by `next_scan_at`;
- root lookup by `(user, component_root_mal_id)`;
- seed lookup by `(user, seed_mal_id)`.

## First-run initial spread

The first maintenance run creates missing states for eligible tracked MAL anime. Initial `next_scan_at` values are spread across `ANIME_FRANCHISE_MAINTENANCE_INITIAL_SPREAD_HOURS`, which defaults to `24` hours.

This avoids scanning every tracked seed immediately after deployment.

Example:

```text
tracked_seeds_seen: 94
states_created: 94
due_selected: 2
processed: 2
succeeded: 2
errors: 0
```

Many states can be created while only a few are due immediately. That is expected and healthy.

## Due selection and batch size

```text
BATCH_SIZE limits selected due seed states.
It does not limit the number of franchise members that can be covered by one processed seed.
```

Example:

```text
due_selected: 2
processed: 2
with_success: 12
```

Meaning:

```text
Two seeds were processed.
Those two seeds covered twelve tracked member states.
```

Do not document batch size as “maximum members per franchise”.

## Per-seed processing

```text
process seed
    ├─ build snapshot
    ├─ compute component root
    ├─ compute discovery fingerprint
    ├─ collect tracked member media IDs
    ├─ build maintenance fingerprint
    ├─ rebuild UI cache
    ├─ process discovery
    ├─ refresh Series View when needed
    └─ update state
```

`AnimeFranchiseMaintenanceService` uses one shared `AnimeFranchiseBuildSession`. Cache rebuild, discovery, and Series View refresh can therefore reuse MAL metadata hydrated inside the same operation.

## Franchise member coverage

After a seed succeeds, tracked members from the same canonical franchise snapshot are covered:

- member states get the component root, fingerprint, success timestamps, and next scan time;
- duplicate root work is avoided during the same scan;
- repeated scans of every season in a franchise are avoided;
- a single processed seed can move many tracked member states forward.

## Success cadence

| Profile | Trigger | Next scan window |
| --- | --- | --- |
| `HOT` | changed, root changed, currently airing, upcoming, future start | 6h to 36h |
| `WARM` | unknown end date or recent franchise | 24h to 3d |
| `COOL` | mature franchise | 3d to 10d |
| `COLD` | old franchise | 10d to 21d |
| `DEEP_COLD` | old, stable, complete, no unknown dates, not truncated | 21d to 30d |

`HOT` is intentionally fast for active or future franchises. `WARM` covers recent or incomplete information. `COOL` and `COLD` reduce work for older franchises. `DEEP_COLD` requires enough stable scans and old data.

Deterministic jitter avoids synchronized scans. Root-based schedule keys keep a franchise together while seed micro-jitter avoids exact same-minute spikes.

## Error behavior

Critical errors mark the state as failed or partially failed:

- `last_error` and `last_error_at` are recorded;
- `consecutive_error_count` increases;
- the next retry uses exponential backoff based on `ANIME_FRANCHISE_MAINTENANCE_ERROR_RETRY_HOURS`;
- retry delay is capped at seven days;
- locks prevent concurrent maintenance runs.

## Metadata refresh invalidation

MAL metadata refresh can detect strong relation changes and complement scheduled maintenance.

When old and new related-anime edges differ for strong relations:

- known canonical franchise payloads are marked stale;
- forced cache rebuilds can be scheduled;
- relevant maintenance scan states can be nudged due soon;
- missing payloads are reported as missing, but cannot be invalidated.

Strong relations include continuity relations and franchise-structure relations such as `alternative_setting`, `alternative_version`, and `spin_off`.

See [franchise cache](anime-franchise-cache.md) and [architecture overview](architecture-overview.md) for the cache invalidation flow.

## Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `ANIME_FRANCHISE_MAINTENANCE_SCAN_ENABLED` | `False` | Enables the Celery Beat maintenance scan entry. |
| `ANIME_FRANCHISE_MAINTENANCE_SCAN_INTERVAL_MINUTES` | `60` | Beat interval for the maintenance task. |
| `ANIME_FRANCHISE_MAINTENANCE_SCAN_BATCH_SIZE` | `10` | Number of due seed states selected per scan. |
| `ANIME_FRANCHISE_MAINTENANCE_INITIAL_SPREAD_HOURS` | `24` | Spread window for first-run state creation. |
| `ANIME_FRANCHISE_MAINTENANCE_REFRESH_CACHE` | `True` | Whether maintenance refreshes MAL provider cache while building snapshots. |
| `ANIME_FRANCHISE_MAINTENANCE_LOCK_MINUTES` | `360` | Lock lifetime for one maintenance task run. |
| `ANIME_FRANCHISE_MAINTENANCE_ERROR_RETRY_HOURS` | `12` | Base retry interval for failed states before exponential backoff. |
| `ANIME_FRANCHISE_MAINTENANCE_REFRESH_SERIES_VIEW_ON_CHANGE` | `True` | Refresh Series View when the maintenance fingerprint changes. |
| `ANIME_FRANCHISE_MAINTENANCE_REFRESH_SERIES_VIEW_ON_SUCCESS` | `False` | Optionally refresh Series View after every successful maintenance scan. |
| `ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MIN_AGE_YEARS` | `15` | Minimum age before deep-cold cadence can apply. |
| `ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MIN_STABLE_SCANS` | `8` | Stable success count needed for deep-cold cadence. |
| `ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MIN_CHANGE_AGE_DAYS` | `180` | Minimum time since last change before deep-cold cadence can apply. |
| `ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MIN_DAYS` | `21` | Minimum deep-cold scan window. |
| `ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MAX_DAYS` | `30` | Maximum deep-cold scan window. |

Compatibility settings that still exist in settings:

| Setting | Default | Note |
| --- | --- | --- |
| `ANIME_FRANCHISE_MAINTENANCE_TARGET_SWEEP_HOURS` | `24` | Legacy compatibility setting. The current adaptive cadence path uses profile windows instead. |
| `ANIME_FRANCHISE_MAINTENANCE_USE_STABLE_BACKOFF` | `False` | Legacy compatibility setting. Do not enable unless the code path is intentionally reintroduced. |
| `ANIME_FRANCHISE_MAINTENANCE_MAX_STABLE_BACKOFF_DAYS` | `30` | Legacy compatibility setting for the old stable-backoff path. |

## Commands

The checked-in Compose service is `yamtrack`. Some deployments may split web, worker, and beat into separate services.

Inspect settings:

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
]:
    print(f"{name}:", getattr(settings, name))
print("beat_entry_exists:", bool(entry))
print("beat_entry:", entry)
PY
```

Inspect logs:

```bash
docker compose logs --since=90m yamtrack | grep -Ei "Scan MAL anime franchise maintenance|anime franchise maintenance|Scheduler: Sending due task|succeeded|failed|error" || true
```

DB summary:

```bash
docker compose exec -T yamtrack python manage.py shell <<'PY'
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
PY
```

Due states:

```bash
docker compose exec -T yamtrack python manage.py shell <<'PY'
from django.utils import timezone
from app.models import AnimeFranchiseMaintenanceScanState

for state in AnimeFranchiseMaintenanceScanState.objects.filter(next_scan_at__lte=timezone.now()).order_by("next_scan_at")[:20]:
    print(state.id, state.user_id, state.seed_mal_id, state.component_root_mal_id or "-", state.next_scan_at, state.last_success_at)
PY
```

Error states:

```bash
docker compose exec -T yamtrack python manage.py shell <<'PY'
from app.models import AnimeFranchiseMaintenanceScanState

for state in AnimeFranchiseMaintenanceScanState.objects.exclude(last_error="").order_by("-last_error_at")[:20]:
    print(state.id, state.user_id, state.seed_mal_id, state.last_error_at, state.consecutive_error_count, state.last_error[:200])
PY
```

Next state:

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

Manual scan:

```bash
docker compose exec -T yamtrack python manage.py scan_mal_anime_franchise_maintenance --limit 10 --force
```

## Healthy output examples

Healthy first scan:

```text
states_created: 94
due_selected: 2
processed: 2
succeeded: 2
errors: 0
```

Healthy DB summary after a scan:

```text
total_states: 94
due_now: 0
with_success: 12
pending_first_success: 82
with_error: 0
```

`pending_first_success` is normal after the first state-creation pass because initial spread intentionally defers most seeds.

`due_now` can remain greater than zero when backlog exceeds the batch size or when another state becomes due immediately after the scan.

## Troubleshooting

| Symptom | Meaning | First check |
| --- | --- | --- |
| `total_states=0` | first scan not run, disabled setting, no eligible anime, or Beat not running | settings and logs |
| `due_now>0` after scan | state became due after the scan or backlog exceeded batch | `next_scan_at` and Beat time |
| `with_error>0` | one or more states failed | error state list |
| many `root=-` | states not processed yet or unresolved root | `last_success_at` |
| `with_success` jumps faster than `processed` | one seed covered multiple tracked members | root grouping |
| Beat entry missing | scan disabled or settings not visible in Beat process | Django settings in runtime container |
| task skipped `already_running` | lock is active | logs and lock timeout |
