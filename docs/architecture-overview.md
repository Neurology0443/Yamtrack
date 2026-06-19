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
├── UI Projection
├── Import Projection
└── Cache Projection
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
- Celery task `Scan MAL anime release dates` checks a bounded batch of due
  start-date states.
- Beat schedule entry `auto_import_anime_franchise` exists only when import automation is enabled.
- `views.py` enriches cached payloads with current-user data at render time.
- `media_details.html` renders prepared context and should not classify entries.

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
