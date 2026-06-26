# Architecture overview

## Scope

This fork is scoped to MAL anime franchise handling:

- MAL anime only.
- Anime detail pages for grouping and display.
- Anime-only Series View layout.
- Import automation and autonomous maintenance for tracked MAL anime.
- MAL anime start-date notifications.

Non-MAL anime providers and other media types keep upstream Yamtrack behavior.

The goal is to keep request rendering stable while provider fetching, graph normalization, UI placement, import selection, cache delivery, discovery, maintenance, and notification state evolve independently.

## Current architecture

```text
                         MyAnimeList
                             │
                             ▼
                 ┌──────────────────────┐
                 │ MAL provider          │
                 │ src/app/providers/mal │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │ MAL metadata cache    │
                 │ providers/mal_cache   │
                 └──────────┬───────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ AnimeFranchiseBuildSession                                   │
│ short-lived operation scope                                  │
│ shared MAL hydration + refresh_cache policy                  │
│ anime_franchise_build_session.py                             │
│                                                              │
│        ┌────────────────────────────────────┐                │
│        │ AnimeFranchiseGraphBuilder          │                │
│        │ relation graph + normalized edges   │                │
│        │ anime_franchise_graph.py            │                │
│        └─────────────────┬──────────────────┘                │
│                          │                                   │
│                          ▼                                   │
│        ┌────────────────────────────────────┐                │
│        │ AnimeFranchiseSnapshotService       │                │
│        │ builds canonical franchise snapshot │                │
│        │ anime_franchise_snapshot.py         │                │
│        └─────────────────┬──────────────────┘                │
│                          │                                   │
│                          ▼                                   │
│        ┌────────────────────────────────────┐                │
│        │ AnimeFranchiseSnapshot              │                │
│        │ canonical franchise truth           │                │
│        └────────────────────────────────────┘                │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
          ┌────────────────────────────────────┐
          │ Consumers / projections             │
          │ use the snapshot, and coordinated   │
          │ operations may reuse session        │
          │ hydration context                   │
          └────────────────┬───────────────────┘
                           │
          ┌────────────────┼────────────────┬────────────────┬────────────────┐
          ▼                ▼                ▼                ▼                ▼
   ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
   │ UI cache      │ │ Discovery    │ │ Import       │ │ Series View  │ │ Maintenance  │
   │ detail page   │ │ notifications│ │ Planning     │ │ memberships  │ │ scan state   │
   └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
```

### How to read this diagram

- The MAL provider and MAL metadata cache are the metadata source layer.
- `AnimeFranchiseBuildSession` is the short-lived operation scope, not the canonical franchise state.
- `AnimeFranchiseGraphBuilder` builds normalized relation graph data from hydrated MAL metadata inside that scope.
- `AnimeFranchiseSnapshotService` creates the canonical franchise snapshot.
- `AnimeFranchiseSnapshot` is the canonical franchise truth produced inside that operation scope.
- The arrow exits the session envelope because coordinated consumers may reuse the session hydration context, but their franchise truth remains the snapshot.
- UI cache, discovery, import, Series View, and maintenance are projections or consumers of the same snapshot.
- These consumers should not blindly copy each other's policies. UI placement is not import selection, and Series View grouping is not detail-page layout.

## Shared build session

`AnimeFranchiseBuildSession` owns per-operation hydration. It memoizes MAL anime payloads for one operation and creates graph builders and snapshot services that share that hydration context.

This matters when one operation has several consumers. Import and maintenance can reuse the same build session for snapshot, cache, discovery, and Anime Series View work. Import-created entries can additionally initialize MAL release-date state when metadata is available.

The session has operation-local freshness rules:

- `refresh_cache=True` asks the MAL provider path to refresh provider cache data;
- stale-allowed and normal fetch levels are tracked inside the session;
- the session ends with the task, command, or service call.

## Provider cover synchronization

Fresh provider metadata can also update the global `Item.image` field through `item_image_sync` (`app/services/item_image_sync.py`). The service owns the rule for when a provider image may update `Item.image`.

```text
MAL provider/cache refresh
        │
        ▼
fresh image candidate
        │
        ▼
item_image_sync
        │
        ▼
global Item.image
```

Rules:

- this is metadata hygiene, not franchise structure;
- it targets global base `Item` rows, not per-user rows;
- automatic MAL paths currently target MAL anime base rows with no season or episode number;
- empty images, `IMG_NONE`, and identical images are skipped;
- missing or placeholder `Item.image` values can be filled;
- MAL anime refreshes may replace older MAL images;
- non-MAL providers do not overwrite an existing different image;
- bulk sync deduplicates candidates, and the last normalized candidate wins for the same source, media type, and media ID;
- failures are best-effort in background refresh and maintenance paths.

## Runtime flows

### Detail page

```text
User opens MAL anime detail page
        │
        ▼
load complete franchise cache / alias
        │
        ├─ fresh payload  → enrich for current user → render
        ├─ stale payload  → render stale payload → queue refresh
        ├─ missing payload → fallback related anime → queue build
        └─ invalid payload → fallback related anime → queue rebuild
```

Rules:

- The detail page must not synchronously build large franchises on cache miss.
- The cached payload is user-agnostic.
- User-specific status, progress, current-entry context, local media image, and display checks are added at request time.
- Helper enrichment uses the centralized `item_image_sync` rule when local user/media data is enriched for rendering.

### Manual add

```text
User manually adds MAL anime
        │
        ▼
transaction commit
        │
        ▼
Process manual MAL anime franchise
        │
        ├─ shared build session
        ├─ snapshot
        ├─ force/update UI cache
        └─ refresh Anime Series View
```

Rules:

- Manual add should make the detail page and Series View coherent quickly.
- Manual add does not process discovery notifications.
- Queue locks avoid duplicate work for the same user/media operation.

### Background cache build

```text
Build MAL anime franchise payload
        │
        ▼
shared build session
        │
        ▼
snapshot
        │
        ▼
UI projection
        │
        ▼
serialize user-agnostic payload
        │
        ▼
save canonical payload + aliases + metadata
```

Rules:

- `force_cache_rebuild` bypasses the alias shortcut for cache writing.
- `refresh_cache` controls MAL provider freshness.
- Truncated builds avoid unsafe alias replacement.

### Import automation

```text
Import anime franchise
        │
        ▼
select due seeds
        │
        ▼
shared build session + snapshot
        │
        ▼
profile selection
        │
        ├─ continuity
        ├─ satellites
        └─ complete
        │
        ▼
create missing Anime rows as Planning
        │
        ├─ entry-added notification
        ├─ cache warmup
        ├─ discovery processing
        └─ Series View refresh
```

Rules:

- Import creates missing user library entries.
- Import profile selection is not UI placement.
- Imported entries default to `Planning`.
- Import-created rows set `_skip_hot_priority` to avoid recursive hot-priority behavior.
- Import-created rows initialize release-date state when metadata is available.

### Autonomous maintenance

```text
Celery Beat every N minutes
        │
        ▼
Scan MAL anime franchise maintenance
        │
        ▼
ensure missing maintenance states
        │
        ▼
select due states up to batch size
        │
        ▼
process each seed
        │
        ├─ shared build session
        ├─ canonical snapshot
        ├─ forced UI cache rebuild
        ├─ discovery processing
        ├─ Series View refresh when needed
        └─ scan-state update + next_scan_at
```

Rules:

- Maintenance keeps existing tracked MAL anime franchise data fresh.
- Maintenance is not import automation.
- Maintenance does not directly create missing `Anime` rows.
- Maintenance can discover newly visible franchise entries and notify through discovery.
- Maintenance can sync fresh MAL snapshot images into `Item.image` when `refresh_cache=True`.
- One processed seed can cover multiple tracked member states in the same franchise.
- Batch size limits selected due seed states, not franchise size.

See [anime-franchise-maintenance.md](anime-franchise-maintenance.md).

### Metadata refresh invalidation

```text
Refresh MAL anime metadata
        │
        ▼
compare old/new related_anime edges
        │
        ▼
strong relation changed?
        │
        ├─ mark canonical franchise payload stale
        ├─ schedule forced cache rebuild
        └─ nudge known maintenance states due soon
```

Rules:

- Only strong relation changes trigger franchise invalidation.
- Continuity relations count.
- Franchise-structure relations such as `alternative_setting`, `alternative_version`, and `spin_off` count.
- Missing payloads are tracked as missing but cannot be invalidated.
- Refresh MAL anime metadata also attempts best-effort cover sync after a successful MAL refresh.
- `mark_media_due_soon()` must not delay a scan that is already sooner.

### Anime Series View

```text
Anime list Series layout
        │
        ▼
read AnimeSeriesViewMembership rows
        │
        ▼
group by root_media_id
        │
        ▼
render franchise cards
```

Rules:

- `media_list` must stay DB-only.
- No MAL provider call, snapshot build, cache build, DB write, or Celery scheduling belongs in Series View rendering.
- Refresh work belongs to triggers, tasks, rebuild commands, import, and maintenance.

See [anime-series-view.md](anime-series-view.md).

### MAL anime release-date notifications

```text
MAL metadata["details"]["start_date"]
        │
        ▼
AnimeReleaseDateScanState
        │
        ▼
detect first date / precision increase / date change
        │
        ▼
AnimeReleaseDateNotificationDelivery
        │
        ▼
Apprise notification
```

Rules:

- The release-date notification scanner watches MAL start-date values.
- It is separate from franchise maintenance.
- It is separate from `send_release_notifications`.
- It is separate from AniList calendar/event notifications.

See [anime-release-date-notifications.md](anime-release-date-notifications.md).

## Core concepts

- **Franchise graph**: hydrated MAL anime nodes plus normalized relation edges. Built by `AnimeFranchiseGraphBuilder` from MAL metadata and direct neighbors.
- **Canonical franchise snapshot**: normalized deterministic representation around one seed. Built by `AnimeFranchiseSnapshotService`.
- `continuity_component`: nodes reached by the graph builder for the franchise continuity component.
- `series_line`: ordered TV-only continuity line derived from prequel/sequel direction and dates. This feeds the fixed UI `Series` block.
- `direct_anchors`: nodes used for direct secondary candidate discovery.
- `direct_candidates`: direct relations from anchors after excluding entries already in the TV series line.
- `promoted_continuity_candidates`: non-TV prequel/sequel chains promoted from the series line.
- `canonical_root_media_id`: stable root used for scan state and canonical cache payloads.
- `fallback_anchor_media_id`: root media ID used for anchoring no-series-line layouts.

## Persistent state models

| Model | Scope | Purpose |
| --- | --- | --- |
| `AnimeSeriesViewMembership` | per user + media | DB read model for Anime Series View |
| `AnimeImportScanState` | per user + seed + profile | import automation due state |
| `AnimeFranchiseMaintenanceScanState` | per user + seed | autonomous maintenance due state |
| `AnimeFranchiseDiscoveryState` | per user + root | discovery baseline and fingerprint |
| `AnimeFranchiseDiscoveredEntry` | per user + root + discovered media | visible discovered entries and notification state |
| `AnimeReleaseDateScanState` | global per MAL anime item | start-date scan state |
| `AnimeReleaseDateNotificationDelivery` | per user + transition | release-date notification dedupe |

Dedicated docs explain the operational fields for [maintenance](anime-franchise-maintenance.md), [import](anime-franchise-import.md), [Series View](anime-series-view.md), and [release-date notifications](anime-release-date-notifications.md).

## Delivery layer

Celery tasks:

- `Build MAL anime franchise payload`;
- `Process manual MAL anime franchise`;
- `Import anime franchise`;
- `Refresh MAL anime metadata`;
- `Refresh Anime Series View franchise projection`;
- `Scan MAL anime release dates`;
- `Scan MAL anime franchise maintenance`.

Beat schedule helpers:

- `auto_import_anime_franchise` from `build_anime_franchise_import_schedule()`;
- `scan_mal_anime_release_dates` from `build_anime_release_date_scan_schedule()`;
- `scan_mal_anime_franchise_maintenance` from `build_anime_franchise_maintenance_schedule()`.

Event/release notifications use the existing `Send release notifications` task for calendar `Event` rows. That task is not the MAL start-date scanner.

## Where to find the main files

| Area | Files |
| --- | --- |
| Provider metadata | `src/app/providers/mal.py`, `src/app/providers/mal_cache.py` |
| Shared build session | `src/app/services/anime_franchise_build_session.py` |
| Graph and snapshot | `src/app/services/anime_franchise_graph.py`, `src/app/services/anime_franchise_snapshot.py` |
| Detail-page cache | `src/app/services/anime_franchise_cache.py`, `src/app/services/anime_franchise_cache_builder.py`, `src/app/services/anime_franchise_context.py`, `src/app/services/anime_franchise_scoped_payload.py` |
| Import | `src/app/services/anime_franchise_import.py`, `src/app/services/anime_import_state.py`, `src/app/management/commands/import_anime_franchise.py` |
| Maintenance | `src/app/services/anime_franchise_maintenance.py`, `src/app/services/anime_franchise_maintenance_scan.py`, `src/app/services/anime_franchise_maintenance_cadence.py`, `src/app/management/commands/scan_mal_anime_franchise_maintenance.py` |
| Metadata invalidation | `src/app/services/anime_franchise_continuity_invalidation.py` |
| Discovery | `src/app/services/anime_franchise_discovery.py`, `src/events/notifications.py` |
| Series View | `src/app/services/anime_series_view.py`, `src/app/services/anime_series_view_projection.py`, `src/app/services/anime_series_view_franchise_refresh.py`, `src/app/services/anime_series_view_refresh_triggers.py`, `src/app/management/commands/rebuild_anime_series_view.py` |
| Views and templates | `src/app/views.py`, `src/templates/app/media_details.html`, `src/templates/app/media_list.html`, `src/templates/app/components/anime_series_groups.html`, `src/templates/app/components/anime_series_group_card.html` |
| Release dates | `src/events/services/anime_release_date_notifications.py`, `src/events/tasks.py` |
| Tasks and schedules | `src/app/tasks.py`, `src/app/schedules.py`, `src/config/settings.py` |

## Settings

Important settings groups:

- franchise cache: cache TTL, freshness window, aliases, queue locks, task locks, max nodes, schema version;
- import automation: enabled flag, interval, profile, refresh-cache flag, full-rescan flag, limit;
- autonomous maintenance: scan enabled flag, interval, batch size, initial spread, refresh-cache flag, lock timeout, error retry, Series View refresh flags, deep-cold thresholds;
- release-date notifications: enabled flag, scan interval, batch size, minimum refresh interval, error retry, max backoff, lock timeout;
- MAL provider rate limiting.

Use [operational commands](operational-commands.md) to inspect the runtime values in a container.

## Design rules

- Snapshot is the canonical franchise source.
- UI, import, cache, discovery, Series View, and maintenance are separate consumers.
- Build sessions are per-operation and are not a global cache.
- UI placement is not import selection.
- Complete franchise cache stores no user-specific data.
- Detail page may render stale payload while refreshing.
- Series View reader must stay DB-only.
- No MAL provider call, snapshot build, cache build, DB write, or Celery scheduling belongs in `media_list` rendering.
- Maintenance batch size limits seed states, not franchise member coverage.
- Release-date scanner is not franchise maintenance.
- `send_release_notifications` is not the MAL release-date scanner.

## Related docs

- [Anime franchise cache](anime-franchise-cache.md)
- [Anime franchise import](anime-franchise-import.md)
- [Anime franchise maintenance](anime-franchise-maintenance.md)
- [Anime Series View](anime-series-view.md)
- [MAL anime release-date notifications](anime-release-date-notifications.md)
- [Anime franchise debugging runbook](anime-franchise-debugging-runbook.md)
- [Operational commands](operational-commands.md)
