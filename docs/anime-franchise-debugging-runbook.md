# Anime franchise debugging runbook

## Preconditions

- Confirm the page is a MAL anime detail page.
- Confirm `ANIME_FRANCHISE_GROUPING_ENABLED=True`.
- Confirm the checked-in Compose service names are `yamtrack` and `redis`.
- Legacy cached payloads may still contain `series_label`; it is not current product behavior.

## Fast diagnosis

| Symptom | First place to check |
| --- | --- |
| Entry appears in the wrong section | `placement_trace` / UI rule packs |
| `Series` is missing or wrong | Snapshot `series_line` |
| Franchise root looks wrong | Snapshot `canonical_root_media_id` |
| Related entry is missing from grouping | Snapshot candidates, then `placement_trace` |
| Entry was imported unexpectedly | Import profile selection |
| Entry was not imported | Import profile selection and scan state |
| Page shows fallback related anime only | Cache payload/meta and displayability checks |
| Page differs from service payload | Request context enrichment |
| Badge or tooltip is wrong | Request context / `anime_franchise_footer.py` |
| Series image looks outdated | Request context enrichment and local media image lookup |
| MAL anime cover stays stale after metadata refresh | MAL cache payload image, `Item.image`, and `item_image_sync` rule |
| Maintenance scan refreshed cache but cover did not change | `ANIME_FRANCHISE_MAINTENANCE_REFRESH_CACHE`, snapshot node image, non-critical maintenance errors |
| Season/episode row image did not change | Expected for provider image sync; only base no-season/no-episode `Item` rows are targeted |
| Alias page misses the franchise cache | Alias key and canonical payload validity |
| Cache does not refresh | Queue/task locks and error cooldown metadata |
| Anime list Series View is empty or incomplete | `AnimeSeriesViewMembership` / rebuild command / `unprojected_count` |
| Franchise appears split into multiple Series View cards | `AnimeSeriesViewProjectionBuilder` root/component/boundaries |
| Old/remake continuity incorrectly merged | `alternative_version` boundary rules |
| Series View rebuild triggers MAL 504 | provider cache completeness / rebuild by batches / sleep between seeds |
| Local branch root appears swallowed by a parent maintenance root | Maintenance scan state branch-root candidates and `component_root_mal_id` groups |

Most franchise display bugs fall into one of four layers: snapshot facts, UI placement, cache delivery, or request rendering. Start with the layer that owns the symptom.

Quick route:

```text
Wrong franchise structure?
  -> inspect snapshot first

Wrong section?
  -> inspect grouping rules and placement_trace

Wrong imports?
  -> inspect import profiles and scan state

Wrong cache behavior?
  -> inspect cache payload, metadata, aliases, locks, and cooldowns

Wrong badge / image / tooltip?
  -> inspect request-time rendering enrichment
```

## Fast targeted tests

```bash
python manage.py test app.tests.services.test_anime_franchise
python manage.py test app.tests.services.test_anime_franchise_snapshot
python manage.py test app.tests.services.test_anime_franchise_ui_pipeline
python manage.py test app.tests.services.test_anime_franchise_cache
python manage.py test app.tests.services.test_anime_franchise_import_profiles
python manage.py test app.tests.views.test_media_details
python manage.py test app.tests.test_tasks
python manage.py test app.tests.test_item_image_sync
```

Docker equivalents:

```bash
docker compose exec yamtrack python manage.py test app.tests.services.test_anime_franchise_ui_pipeline
docker compose exec yamtrack python manage.py test app.tests.services.test_anime_franchise_cache
docker compose exec yamtrack python manage.py test app.tests.views.test_media_details
```


## Inspect Anime Series View

Run a dry-run rebuild before writing memberships:

```bash
docker compose exec yamtrack python manage.py rebuild_anime_series_view --all-users --dry-run
docker compose exec yamtrack python manage.py rebuild_anime_series_view --user-id 1 --limit 20 --dry-run
```

Count tracked, projected, and unprojected MAL anime for one user:

```bash
docker compose exec yamtrack python manage.py shell -c "from app.models import Anime, AnimeSeriesViewMembership, Sources; tracked=set(Anime.objects.filter(user_id=1, item__source=Sources.MAL.value).values_list('item__media_id', flat=True)); projected=set(AnimeSeriesViewMembership.objects.filter(user_id=1, media_id__in=tracked).values_list('media_id', flat=True)); print({'tracked': len(tracked), 'projected': len(projected), 'unprojected': len(tracked-projected)})"
```

List memberships grouped by root:

```bash
docker compose exec yamtrack python manage.py shell -c "from app.models import AnimeSeriesViewMembership; from collections import defaultdict; rows=AnimeSeriesViewMembership.objects.filter(user_id=1).order_by('root_media_id','media_id').values_list('root_media_id','media_id','display_title','group_kind','projection_version'); roots=defaultdict(list); [roots[root].append((media,title,kind,version)) for root,media,title,kind,version in rows]; [print(root, members) for root,members in roots.items()]"
```

Find stale memberships for media no longer tracked by the user:

```bash
docker compose exec yamtrack python manage.py shell -c "from app.models import Anime, AnimeSeriesViewMembership, Sources; tracked=set(Anime.objects.filter(user_id=1, item__source=Sources.MAL.value).values_list('item__media_id', flat=True)); stale=AnimeSeriesViewMembership.objects.filter(user_id=1).exclude(media_id__in=tracked).values_list('media_id','root_media_id'); print(list(stale))"
```

Inspect the projection produced from one seed:

```bash
docker compose exec yamtrack python manage.py shell -c "from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService; from app.services.anime_series_view_projection import AnimeSeriesViewProjectionBuilder; s=AnimeFranchiseSnapshotService().build('11757'); p=AnimeSeriesViewProjectionBuilder().build(s); print(p)"
```

## Debug branch-root maintenance preservation

Use this when a tracked seed should remain a local branch root but appears to be covered by a parent franchise root. Check maintenance scan state for the affected user: if another tracked state resolves to that seed as `component_root_mal_id`, that seed should appear in branch-root candidates and should not be duplicate-covered by the parent scan.

This preservation is DB-local and known-state based. It protects branch roots already represented in maintenance scan state; it does not infer unseen MAL branches during scheduling. The canonical feature explanation remains in `docs/anime-franchise-maintenance.md`.

```text
Healthy SAO-style shape:

11757 -> root 11757
36474 -> root 11757
42916 -> root 42916
50275 -> root 42916
```

Use the branch-root preservation candidate command in `docs/operational-commands.md` to print current candidates and `states_by_root` groups without triggering scans.

## Inspect service payload

Use the service path when you want the assembled UI payload without the cache layer:

```bash
python manage.py shell -c "from app.services.anime_franchise import AnimeFranchiseService; p=AnimeFranchiseService().build('34161'); print(p)"
```

In Docker:

```bash
docker compose exec yamtrack python manage.py shell -c "from app.services.anime_franchise import AnimeFranchiseService; p=AnimeFranchiseService().build('34161'); print(p)"
```

## Inspect snapshot

For field meanings and invariants, see `docs/anime-franchise-snapshot.md`.

```bash
python manage.py shell -c "from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService; s=AnimeFranchiseSnapshotService().build('34161'); print('root', s.root_node.media_id); print('canonical', s.canonical_root_media_id); print('series', [n.media_id for n in s.series_line]); print('direct', [(r.source_media_id,r.target_media_id,r.relation_type) for r in s.direct_candidates]); print('promoted', [(r.source_media_id,r.target_media_id,r.relation_type) for r in s.promoted_continuity_candidates])"
```

Check these fields first when the page looks wrong:

- `series_line`
- `direct_anchors`
- `direct_candidates`
- `promoted_continuity_candidates`
- `no_series_line_secondary_candidates`
- `root_story_parent_candidates`
- `canonical_root_media_id`
- `fallback_anchor_media_id`
- `has_series_line`

## Inspect rule placement

```bash
python manage.py shell -c "from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService; from app.services.anime_franchise_ui.assembler import UiCandidateAssembler; from app.services.anime_franchise_ui.engine import RulePipeline; from app.services.anime_franchise_ui.presets import DefaultUiPreset; from app.services.anime_franchise_ui.rule_types import RuleContext; s=AnimeFranchiseSnapshotService().build('34161'); c=UiCandidateAssembler().build(s); ctx=RuleContext(snapshot=s); RulePipeline(list(DefaultUiPreset)).run(candidates=c, context=ctx); print([(x.media_id,x.title,x.section_key,x.metadata.get('placement_trace')) for x in c])"
```

Use `placement_trace` to find the rule pack that moved a candidate. Later packs can override earlier placement.

## Inspect view context

Detail-page rendering uses cached payloads. If the service payload looks correct but the page does not:

1. Inspect cache payload and metadata.
2. Check whether the requested ID resolved through an alias.
3. Verify `prepare_anime_franchise_context()` can enrich the payload.
4. Check whether `has_displayable_franchise_entries()` returned false, leaving related-anime fallback visible.

## Inspect cache

Use this when:

- the page shows only fallback related anime;
- a franchise looks stale;
- an imported entry does not show a warmed franchise;
- an alias page does not resolve to the canonical franchise.

Check payload and metadata:

```bash
docker compose exec redis redis-cli keys '*anime*franchise*'
docker compose exec redis redis-cli get mal_anime_franchise_34161
docker compose exec redis redis-cli get mal_anime_franchise_34161:meta
```

Interpretation:

- payload key missing: the page should schedule a build;
- meta key has recent error: retry may wait for error cooldown;
- alias key missing: the media ID may not be aliasable, or the last build was truncated;
- alias exists but canonical payload is missing/invalid: lookup should ignore or clean it safely.

Schedule a rebuild:

```bash
docker compose exec yamtrack python manage.py shell -c "from app.tasks import build_mal_anime_franchise_payload; build_mal_anime_franchise_payload.delay('34161')"
```

Clear targeted payload keys:

```bash
docker compose exec redis redis-cli del mal_anime_franchise_34161 mal_anime_franchise_34161:meta mal_anime_franchise_34161:aliases
```

## Inspect aliases

```bash
docker compose exec redis redis-cli get mal_anime_franchise_alias_34428
docker compose exec redis redis-cli get mal_anime_franchise_34161:aliases
```

If an alias does not resolve:

- ensure aliases are enabled;
- verify the canonical payload is valid;
- verify the requested media ID is aliasable;
- check that the build was not truncated.


## Franchise payload cache alias audit

A healthy franchise cache state must not contain both a direct payload and an alias for the same MAL anime media id. `load_payload_for_media(media_id)` checks the direct payload first, so a stale direct payload would shadow an alias that should resolve to the canonical payload.

Run this compact audit from the repository root in Docker dev:

```bash
docker compose -f docker-compose.dev.yml exec yamtrack-dev python manage.py shell -c '
from django.core.cache import cache
from app.models import Item, MediaTypes, Sources
from app.services import anime_franchise_cache

media_ids = list(
    Item.objects.filter(
        source=Sources.MAL.value,
        media_type=MediaTypes.ANIME.value,
    ).values_list("media_id", flat=True).distinct()
)
conflicts = []
for media_id in media_ids:
    direct = cache.get(anime_franchise_cache.get_payload_key(media_id))
    alias = cache.get(anime_franchise_cache.get_alias_key(media_id))
    if direct and alias:
        conflicts.append(str(media_id))

print(f"checked_media_ids: {len(media_ids)}")
print(f"conflicts: {len(conflicts)}")
for media_id in conflicts:
    print(f"CONFLICT_DIRECT_AND_ALIAS {media_id}")
'
```

Expected result:

```text
conflicts: 0
```

State meanings:

- `DIRECT`: direct payload only.
- `ALIAS`: alias only.
- `MISS`: no payload and no alias.
- `CONFLICT_DIRECT_AND_ALIAS`: invalid; the direct payload would shadow alias resolution.

For an expanded inspection, include the canonical payload metadata behind aliases:

```bash
docker compose -f docker-compose.dev.yml exec yamtrack-dev python manage.py shell -c '
from django.core.cache import cache
from app.models import Item, MediaTypes, Sources
from app.services import anime_franchise_cache

for media_id in Item.objects.filter(
    source=Sources.MAL.value,
    media_type=MediaTypes.ANIME.value,
).values_list("media_id", flat=True).distinct():
    payload = cache.get(anime_franchise_cache.get_payload_key(media_id))
    alias = cache.get(anime_franchise_cache.get_alias_key(media_id))
    if payload and alias:
        print(
            media_id,
            "CONFLICT_DIRECT_AND_ALIAS",
            "direct_root=",
            payload.get("root_media_id"),
            "alias=",
            alias,
        )
    elif payload:
        print(
            media_id,
            "DIRECT",
            "covered=",
            payload.get("covered_media_ids", []),
            "aliasable=",
            payload.get("aliasable_media_ids", []),
        )
    elif alias:
        canonical_id = alias.get("canonical_media_id")
        canonical = cache.get(anime_franchise_cache.get_payload_key(canonical_id))
        print(
            media_id,
            "ALIAS ->",
            canonical_id,
            "covered=",
            (canonical or {}).get("covered_media_ids", []),
            "aliasable=",
            (canonical or {}).get("aliasable_media_ids", []),
        )
    else:
        print(media_id, "MISS")
'
```

## Inspect import scan state

```bash
python manage.py shell -c "from app.models import AnimeImportScanState; print(list(AnimeImportScanState.objects.values('user_id','seed_mal_id','profile_key','component_root_mal_id','next_scan_at','consecutive_stable_scans','consecutive_error_count')[:20]))"
```

Force a dry-run rescan for one user:

```bash
docker compose exec yamtrack python manage.py import_anime_franchise --profile continuity --dry-run --full-rescan --user-id 1
```

## Relation normalization quick check

```bash
python manage.py shell -c "from app.providers import mal; print(mal.normalize_relation_type('Full story')); print(mal.normalize_relation_type('Side story'))"
```

## Frequent cases

- **Empty franchise**: provider returned no usable relations or graph hydration failed.
- **Missing `Series`**: snapshot has no TV `series_line`.
- **Special/recap misplaced**: inspect normalized relation type, media type, runtime, and `placement_trace`.
- **Imported entry but cold page**: check cache warmup logs, queue lock, task lock, and worker availability.
- **Short satellite not imported**: inspect relation type, runtime, episode count, and local `prequel`/`sequel` branch completeness.
- **Alias miss**: inspect alias key and canonical payload validity.
- **Stale payload**: stale payload can still render; metadata should show a background refresh attempt if cooldown allows.
- **UI/import disagreement**: expected; UI sections and import profiles are separate projections.

### Wrong or stale Series image

Series images may be refreshed opportunistically during request rendering.

Compare:

- image data stored in the cached franchise payload;
- image currently available on the Yamtrack media entry.

A newer local image can be preferred without rebuilding the franchise payload. Fresh provider images may also update the global `Item.image` through `item_image_sync` before request-time enrichment displays that local image.

## Docker commands

```bash
docker compose logs -f yamtrack
docker compose logs -f redis
docker compose exec redis redis-cli keys '*anime*franchise*'
docker compose exec yamtrack python manage.py import_anime_franchise --profile continuity --dry-run
docker compose exec yamtrack python manage.py shell -c "from app.tasks import build_mal_anime_franchise_payload; build_mal_anime_franchise_payload.delay('34161')"
docker compose exec yamtrack celery -A config inspect active
```

## Inspect provider image synchronization

Use this when a MAL anime cover looks stale even though metadata or maintenance recently refreshed.

```bash
docker compose exec yamtrack python manage.py shell -c "from django.core.cache import cache; from app.models import Item, MediaTypes, Sources; from app.providers import mal_cache; media_id='30831'; item=Item.objects.filter(source=Sources.MAL.value, media_type=MediaTypes.ANIME.value, media_id=media_id, season_number__isnull=True, episode_number__isnull=True).first(); payload=cache.get(mal_cache.get_anime_cache_key(media_id)); print({'item_image': item.image if item else None, 'cache_image': payload.get('image') if payload else None})"
```

Interpretation:

- `cache_image` changed but `item_image` did not: check whether the path used `refresh_cache=True` and whether `item_image_sync` rejected the candidate;
- `item_image` is already equal to the provider image: no write is expected;
- image is blank or `IMG_NONE`: it should be ignored as a provider candidate;
- season/episode rows are intentionally not targeted.

## Inspect autonomous franchise maintenance

Use these commands when franchise pages, discovery notifications, cache payloads, or Anime Series View memberships appear stale even when users are not visiting detail pages.

### Inspect settings

```bash
docker compose exec -T yamtrack python manage.py shell <<'PY'
from django.conf import settings

entry = settings.CELERY_BEAT_SCHEDULE.get("scan_mal_anime_franchise_maintenance")

print("SCAN_ENABLED:", settings.ANIME_FRANCHISE_MAINTENANCE_SCAN_ENABLED)
print("SCAN_INTERVAL_MINUTES:", settings.ANIME_FRANCHISE_MAINTENANCE_SCAN_INTERVAL_MINUTES)
print("SCAN_BATCH_SIZE:", settings.ANIME_FRANCHISE_MAINTENANCE_SCAN_BATCH_SIZE)
print("INITIAL_SPREAD_HOURS:", settings.ANIME_FRANCHISE_MAINTENANCE_INITIAL_SPREAD_HOURS)
print("beat_entry_exists:", bool(entry))
print("beat_entry:", entry)
PY
```

### Inspect all-in-one container processes

```bash
docker compose exec -T yamtrack ps aux
```

Some deployments run `nginx`, `gunicorn`, `celery worker`, and `celery beat` inside one container under `supervisord`. Other deployments may split web, worker, and beat into separate services.

### Logs

```bash
docker compose logs --since=90m yamtrack | grep -Ei "Scan MAL anime franchise maintenance|anime franchise maintenance|Scheduler: Sending due task|succeeded|failed|error" || true
```

### DB summary

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

### Troubleshooting

| Symptom | Meaning | First check |
| --- | --- | --- |
| `total_states=0` | first scan not run, disabled setting, Beat missing, or no eligible anime | settings and logs |
| `due_now>0` after scan | state became due after Beat or backlog exceeded batch | `next_scan_at` and logs |
| `with_error>0` | state failure | error state section |
| many `root=-` | not processed yet or unresolved root | `last_success_at` |
| `with_success` jumps faster than `processed` | one seed covered multiple tracked members | root grouping |
| task skipped `already_running` | maintenance lock active | task logs and lock timeout |
