# Architecture overview

## Scope

This fork is scoped to MAL anime franchise handling:

- MAL anime only.
- Anime detail pages for grouping and display.
- Import automation only for existing user library entries whose source is MAL anime.
- Non-MAL anime providers and other media types keep upstream Yamtrack behavior.

The goal is to keep the user-facing page stable while letting provider fetching, graph normalization, UI placement, import selection, and cache delivery evolve independently.

## High-level model

```text
MAL Provider
    ↓
Franchise Graph
    ↓
Franchise Snapshot
    ↓
├── Detail-page UI Projection
├── Anime Series View Projection
├── Import Projection
├── Cache Projection
└── Discovery / notification monitoring
```

The snapshot is the shared canonical state. UI, import, and cache code are separate projections of that state; none of those layers should copy another layer's policy blindly.

## Mental model

Think of the franchise snapshot as the single source of franchise truth.

```text
Snapshot
    ↓
├── UI grouping
├── Import selection
└── Cache payload
    ↓
Rendering
```

The snapshot describes what a franchise is. UI grouping, import selection, and cache delivery are independent consumers of that same snapshot.

This separation allows page layout, import automation, and cache delivery to evolve without changing franchise semantics.

## What this fork changes compared to upstream

Compared to upstream Yamtrack, this fork adds MAL anime franchise behavior on top of the existing tracker:

- clearer MAL anime franchise pages;
- automatic grouping of related MAL anime entries;
- anime-only Series View layout for grouping tracked MAL anime into franchise cards;
- persisted per-user AnimeSeriesViewMembership read model;
- asynchronous refresh of Series View memberships after add/import/delete;
- optional automatic import of useful missing franchise entries;
- persistent scan scheduling for franchise imports;
- complete franchise cache payloads for responsive detail pages;
- cache warmup after import-created entries;
- entry-added notifications for automatically imported anime;
- opt-in MAL anime start-date notifications;
- configurable MAL provider rate limiting.

These additions are scoped to MAL anime franchise behavior. Existing Yamtrack features for other media types and providers remain upstream-compatible.

## Core concepts

- **Franchise graph**: hydrated MAL anime nodes plus normalized relation edges. Built by `AnimeFranchiseGraphBuilder` from MAL metadata and direct neighbors.
- **Franchise snapshot**: normalized, deterministic representation around one seed. Built by `AnimeFranchiseSnapshotService`.
- `continuity_component`: nodes reached by the graph builder for the franchise continuity component.
- `series_line`: ordered TV-only continuity line derived from prequel/sequel direction and dates. This feeds the fixed UI `Series` block.
- `direct_anchors`: nodes used for direct secondary candidate discovery. Usually the full TV series line; for a non-TV root it can include the root too.
- `direct_candidates`: direct relations from anchors after excluding entries already in the TV series line.
- `promoted_continuity_candidates`: non-TV prequel/sequel chains promoted from the series line so transitive OVAs/movies can still be considered as main-story extras.
- `no_series_line_secondary_candidates`: secondary candidates used when the snapshot has no TV series line.
- `root_story_parent_candidates`: direct `full_story` links from a non-TV root to a TV parent.
- `canonical_root_media_id`: stable root used for scan state and canonical cache payloads. It is the first series-line item when available, otherwise the earliest continuity node.
- `fallback_anchor_media_id`: root media ID used for anchoring no-series-line layouts.
- `has_series_line`: boolean guard for UI and candidate assembly when no TV line exists.

## Main runtime flows

### Detail page

```text
media_details view
 -> load complete franchise cache / alias
 -> prepare request-specific context if payload is valid
 -> render media_details.html
 -> schedule background build on miss/stale/invalid when allowed
```

The view does not synchronously build a large franchise on a cache miss. It keeps the standard related-anime fallback for that request and asks Celery to build the full payload.

### Background cache build

```text
Build MAL anime franchise payload task
 -> graph build
 -> snapshot build
 -> UI projection
 -> serialize user-agnostic payload
 -> save canonical payload, metadata, and safe aliases
```

### Import automation

```text
Existing user MAL anime
 -> due seed selection
 -> snapshot build
 -> profile selection
 -> missing Item/Anime creation
 -> scan-state update
 -> entry-added notification
 -> cache warmup scheduling
```


### Anime list Series View

```text
Anime list Series View
 -> DB-filtered user anime queryset
 -> persisted AnimeSeriesViewMembership lookup
 -> group by root_media_id
 -> render anime_series_group_card.html
```

### MAL anime release-date notifications

```text
MAL metadata["details"]["start_date"]
 -> opportunistic metadata refresh / franchise import / bounded scan
 -> global AnimeReleaseDateScanState per MAL anime Item
 -> per-user transition delivery
 -> Apprise notification
```

This flow is deliberately independent from AniList `airingSchedule`, calendar
events, and episode release notifications. The dedicated scan considers only
actively tracked MAL anime with an eligible user, uses a recent MAL cache entry
before making a provider request, and applies cooldown, deterministic batching,
backoff, and jitter.

## UI projection

The UI projection builds the anime detail-page franchise layout:

- `Series` is fixed and comes only from `snapshot.series_line`.
- Secondary sections are rule-driven.
- Classification belongs in rule packs, not in templates.
- The adapter is a compatibility layer; it should not decide placement.

Current UI pipeline:

```text
AnimeFranchiseSnapshot
 -> SeriesBuilder
 -> UiCandidateAssembler
 -> RulePipeline
 -> LayoutCompiler
 -> ViewModelAdapter
```

## Import projection

The import projection also uses the snapshot, but it has its own policy:

- `continuity` imports continuity-component entries that pass format/runtime/summary filters.
- `satellites` imports selected direct spin-off, alternative-version, and side-story entries from canonical seeds.
- `complete` is the union of continuity and satellites.

Import profiles must not follow UI sections blindly. UI placement is about detail-page readability; import selection is about creating useful library entries without over-importing noise.

## Cache projection

The cache projection stores a complete, user-agnostic payload for detail pages:

- payload is JSON-safe and schema-versioned;
- no user status/progress, `Item`, `BasicMedia`, user IDs, or rendered HTML;
- stale payloads can still render while a refresh is queued;
- canonical aliases let aliasable media IDs resolve to one canonical payload;
- import-created entries schedule cache warmup after transaction commit.

## Delivery layer

- Celery task `Build MAL anime franchise payload` builds cache payloads.
- Celery task `Import anime franchise` runs import automation.
- Celery task `Refresh Anime Series View franchise projection` repairs persisted Series View memberships after add/delete/import triggers.
- Celery task `Scan MAL anime release dates` checks a bounded batch of due
  start-date states.
- Celery task `Refresh Anime Series View franchise projection` updates persisted memberships.
- Beat schedule entry `auto_import_anime_franchise` exists only when import automation is enabled.
- `views.py` enriches cached payloads with current-user data at render time.
- `media_details.html` renders prepared context and should not classify entries.
- `media_list` renders Anime Series View from DB-only memberships and does not build snapshots.

## Important code entry points

This section is a map for finding the files that carry the MAL anime franchise architecture. Update it whenever a new architectural boundary, read model, background task, or operational command is added.

### Request orchestration and rendering boundaries

- `src/app/views.py`: request boundary for `media_list`, `media_details`, manual tracking, and deletion. It should orchestrate services, not contain franchise placement rules.
- `src/templates/app/media_details.html`: renders the prepared MAL anime franchise context for detail pages.
- `src/templates/app/media_list.html`: owns the layout toggle and chooses the Series View container for anime lists.
- `src/templates/app/components/anime_series_groups.html`: renders paginated Series View groups and the preparation message for unprojected anime.
- `src/templates/app/components/anime_series_group_card.html`: renders one Series View card. It should stay presentation-only.
- `src/users/models.py`: owns user layout preferences, including the anime-only `series` layout choice.

### MAL provider metadata and Redis cache boundaries

- `src/app/providers/mal.py`: fetches and normalizes MAL anime metadata and relation data.
- `src/app/providers/mal_cache.py`: owns MAL anime detail metadata cache keys, freshness, stale refresh throttling, and sidecar metadata.
- `src/app/services/anime_franchise_cache.py`: owns complete MAL anime franchise payload cache keys, aliases, freshness, validation, queue locks, and task locks.
- `src/app/services/anime_franchise_context.py`: serializes user-agnostic cache payloads and enriches cached payloads with request-specific user data at render time.
- `src/app/services/anime_franchise_cache_warmer.py`: schedules forced cache rebuilds after import-created entries commit.

### Canonical franchise graph, snapshot, and detail-page UI projection

- `src/app/services/anime_franchise_graph.py`: hydrates MAL anime nodes and normalized relation edges with the configured node limit.
- `src/app/services/anime_franchise_snapshot.py`: builds the canonical franchise snapshot consumed by UI, import, cache, and Series View projection code.
- `src/app/services/anime_franchise.py`: compatibility facade from snapshot to detail-page UI payload.
- `src/app/services/anime_franchise_types.py`: shared graph and relation dataclasses used across franchise services.
- `src/app/services/anime_franchise_ui/`: detail-page UI projection pipeline. Placement rules belong here, not in views or templates.
- `src/app/services/anime_franchise_rules.py`: shared relation/format constants used by franchise grouping logic.
- `src/app/services/anime_franchise_ui_profile.py`: detail-page section/profile configuration.
- `src/app/services/anime_franchise_scoped_payload.py`: builds scoped non-canonical detail payloads from snapshots.

### Import automation and discovery state

- `src/app/services/anime_franchise_import.py`: orchestrates profile-based import runs, Item/Anime creation, scan-state updates, discovery, cache warmup, and Series View refresh triggers.
- `src/app/services/anime_franchise_import_profiles.py`: defines import profile policy; do not copy UI section policy blindly into import rules.
- `src/app/services/anime_import_state.py`: selects due user seeds and persists adaptive scan state for import automation.
- `src/app/services/anime_franchise_discovery.py`: persists user-visible franchise discovery candidates and queues discovery notifications.
- `src/app/services/anime_tracking.py`: shared helpers for checking tracked MAL anime entries.
- `src/app/management/commands/import_anime_franchise.py`: synchronous operational entry point for dry-run or manual profile imports.

### Series View database projection and migration

- `src/app/anime_series_view_constants.py`: shared Series View projection version, group kinds, and refresh modes.
- `src/app/services/anime_series_view_rules.py`: stable Series View business rules, groupable relations, root types, boundaries, and reroot priorities.
- `src/app/services/anime_series_view_projection.py`: pure projection builder that converts a franchise snapshot into a persistable franchise or singleton outcome.
- `src/app/services/anime_series_view_franchise_refresh.py`: materializes projections into per-user `AnimeSeriesViewMembership` rows and removes stale memberships safely.
- `src/app/services/anime_series_view_refresh_queue.py`: normalizes media IDs and builds queue de-duplication lock keys for refresh jobs.
- `src/app/services/anime_series_view_refresh_triggers.py`: schedules non-blocking refresh/delete work after surrounding transactions commit.
- `src/app/services/anime_series_view.py`: read-only Series View list reader. It must remain DB-only and must not call MAL, build snapshots, write cache, or schedule refreshes.
- `src/app/management/commands/rebuild_anime_series_view.py`: operational database backfill/repair command for existing users after Series View changes or projection-version changes.
- `src/app/models.py`: owns the persisted `AnimeSeriesViewMembership` read model and its uniqueness/indexing constraints.

### Background tasks, schedules, and release-date notifications

- `src/app/tasks.py`: Celery task entry points for franchise cache builds, franchise import, MAL metadata refresh, and Series View membership refresh.
- `src/app/schedules.py`: Celery Beat schedule helpers for automatic franchise imports and MAL anime release-date scans.
- `src/events/tasks.py`: Celery tasks for calendar reload, release notifications, MAL anime release-date scans, entry-added notifications, and franchise discovery notifications.
- `src/events/services/anime_release_date_notifications.py`: MAL anime start-date scan and notification service.
- `src/events/models.py`: event models plus MAL anime release-date scan/delivery state.
- `src/config/settings.py`: environment-backed settings for MAL API/cache, franchise cache, import automation, release-date scans, and operational limits.

## Settings

Documented settings currently present in `src/config/settings.py`. For setting behavior details, see the dedicated grouping/import/cache docs.

- `ANIME_FRANCHISE_GROUPING_ENABLED`
- `ANIME_FRANCHISE_CACHE_TTL_DAYS`
- `ANIME_FRANCHISE_CACHE_ALIASES_ENABLED`
- `ANIME_FRANCHISE_CACHE_FRESH_DAYS`
- `ANIME_FRANCHISE_BUILD_COOLDOWN_HOURS`
- `ANIME_FRANCHISE_RETRY_AFTER_ERROR_HOURS`
- `ANIME_FRANCHISE_QUEUE_LOCK_MINUTES`
- `ANIME_FRANCHISE_TASK_LOCK_MINUTES`
- `ANIME_FRANCHISE_MAX_NODES`
- `ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION`
- `ANIME_FRANCHISE_IMPORT_AUTOMATION_ENABLED`
- `ANIME_FRANCHISE_IMPORT_AUTOMATION_INTERVAL_MINUTES`
- `ANIME_FRANCHISE_IMPORT_AUTOMATION_PROFILE`
- `ANIME_FRANCHISE_IMPORT_AUTOMATION_REFRESH_CACHE`
- `ANIME_FRANCHISE_IMPORT_AUTOMATION_FULL_RESCAN`
- `ANIME_FRANCHISE_IMPORT_AUTOMATION_LIMIT`
- `MAL_RATE_LIMIT_PER_MINUTE`
- `ANIME_RELEASE_DATE_NOTIFICATIONS_ENABLED`
- `ANIME_RELEASE_DATE_SCAN_INTERVAL_HOURS`
- `ANIME_RELEASE_DATE_SCAN_BATCH_SIZE`
- `ANIME_RELEASE_DATE_SCAN_MIN_REFRESH_HOURS`
- `ANIME_RELEASE_DATE_SCAN_ERROR_RETRY_HOURS`
- `ANIME_RELEASE_DATE_SCAN_MAX_BACKOFF_DAYS`
- `ANIME_RELEASE_DATE_SCAN_LOCK_MINUTES`

## Related docs

- [Anime franchise snapshot](anime-franchise-snapshot.md)
- [Anime franchise grouping](anime-franchise-grouping.md)
- [Anime Series View](anime-series-view.md)
- [Anime franchise import](anime-franchise-import.md)
- [Anime franchise cache](anime-franchise-cache.md)
- [Anime release-date notifications](anime-release-date-notifications.md)

## Design rules

- Snapshot is the canonical franchise source.
- UI, import, and cache are separate projections.
- Rule packs own placement policy.
- Layout code owns structure and ordering.
- Adapter/context code owns compatibility and request enrichment.
- Views should orchestrate cache/context only, not patch placement.
- Templates render only.
- Complete franchise cache never stores user-specific data.
- Anime Series View reader must stay DB-only.
- No MAL provider call, snapshot build, cache build, or DB write belongs in `media_list` rendering.
