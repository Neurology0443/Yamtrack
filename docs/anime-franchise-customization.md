# Anime franchise customization

## Understanding ownership

A franchise change should start by identifying which layer owns the behavior.

```text
Snapshot
    ↓
UI Projection
Import Projection
Cache Projection
    ↓
Rendering
```

The snapshot describes the franchise facts. UI grouping decides how those facts are shown on a detail page. Import profiles decide which missing entries should be created. Cache code decides how prepared payloads are stored and refreshed. Rendering turns prepared context into HTML.

A change should normally affect one main layer. If it appears to require several layers, verify that the behavior truly belongs in each of them.

## Before changing behavior

When changing franchise behavior:

1. Identify the owning layer.
2. Change that layer only when possible.
3. Update the targeted tests for that layer.
4. Update documentation when product behavior or operational behavior changes.

Most fragile changes happen when a fix is applied in a downstream layer instead of the layer that owns the behavior.

## Changing franchise facts

Change franchise facts when the base model of the franchise is wrong before UI, import, or cache policy runs. This includes canonical root selection, continuity discovery, relation normalization, series-line calculation, direct candidate discovery, and promoted continuity candidates.

The main files are:

- `src/app/services/anime_franchise_graph.py` for graph hydration and relation walking;
- `src/app/services/anime_franchise_snapshot.py` for canonical franchise facts and derived snapshot fields;
- `src/app/providers/mal.py` when normalized MAL relation semantics are wrong.

For field definitions and invariants, see `docs/anime-franchise-snapshot.md`.

## Changing page grouping

Page grouping controls where franchise entries appear on the anime detail page. It consumes snapshot facts but does not change them.

Visible grouping can include:

- Series
- Main Story Extras
- Specials
- Related Series
- Alternatives
- Spin-offs

Typical changes include adding a visible section, moving entries between sections, adjusting relation rules, changing anchor gating, changing format/runtime filtering, or changing rule-pack order.

The main files are:

- `src/app/services/anime_franchise_ui/rules/` for placement, refinement, filtering, and metadata policy;
- `src/app/services/anime_franchise_ui/presets/default.py` for rule-pack order;
- `src/app/services/anime_franchise_ui/assembler.py` when candidate facts/provenance are missing;
- `src/app/services/anime_franchise_ui/layout.py` for structural section grouping;
- `src/app/services/anime_franchise_ui/adapter.py` for compatibility-shaped output.

For the decision model, see `docs/anime-franchise-grouping.md`.

## Changing import behavior

Import behavior controls which missing franchise entries are automatically created in a user's library. New imported entries are created with the `Planning` status.

Import profiles are independent from UI grouping sections. A section being visible on the detail page does not automatically mean it should be imported.

Typical changes include profile selection, runtime thresholds, relation inclusion/exclusion, seed selection, full-rescan behavior, scan-state fingerprinting, and backoff/jitter.

The main files are:

- `src/app/services/anime_franchise_import_profiles.py` for profile selection policy;
- `src/app/services/anime_franchise_import.py` for import orchestration and entry creation;
- `src/app/services/anime_import_state.py` for due scans, fingerprints, backoff, and jitter;
- `src/app/tasks.py` for Celery import execution;
- `src/app/schedules.py` for Beat schedule construction.

For profile behavior and commands, see `docs/anime-franchise-import.md`.

## Changing cache behavior

Cache behavior controls how complete franchise payloads are stored, refreshed, reused, and delivered to detail pages.

The cache does not decide grouping behavior. The cache does not decide import behavior. It stores and delivers the result of those layers.

Typical changes include cache TTL, freshness, payload validation, canonical aliases, warmup, cooldowns, queue/task locks, and the serialization contract.

The main files are:

- `src/app/services/anime_franchise_cache.py` for payload keys, metadata, validation, freshness, aliases, and scheduling gates;
- `src/app/services/anime_franchise_cache_warmer.py` for after-import warmup scheduling;
- `src/app/services/anime_franchise_scoped_payload.py` for scoped/truncated payload handling;
- `src/app/services/anime_franchise_context.py` for request-time enrichment of cached payloads;
- `src/app/tasks.py` for background cache builds.

For cache lifecycle and settings, see `docs/anime-franchise-cache.md`.

## Changing rendering

Rendering turns prepared franchise data into page content. This layer is appropriate for labels, badges, tooltips, current-entry markers, and display-only template structure.

Franchise badges and relation tooltips are rendering helpers. They should explain already-classified entries, not classify them.

Rendering-time enrichment can also improve display data such as franchise entry images when fresher media information is already available locally.

Typical rendering changes include:

- labels;
- badges;
- tooltips;
- current-entry markers;
- display-only image enrichment;
- template display structure.

Rendering should not classify franchise entries. If placement is wrong, fix the snapshot facts or UI rule packs first.

The main files are:

- `src/app/services/anime_franchise_context.py` for request/user enrichment;
- `src/app/anime_franchise_footer.py` for footer labels, badges, and tooltips;
- `src/app/views.py` for orchestration of cache lookup and context preparation;
- `src/templates/app/media_details.html` for HTML rendering.

## Notifications

Entry-added notifications belong to the import flow. They are triggered after import-created entries commit, use the existing notification/event subsystem, and should not fire before transaction commit.

The main files are:

- `src/app/services/anime_franchise_import.py` for the import creation path;
- `src/events/notifications.py` for notification helpers;
- `src/events/tasks.py` for event task delivery;
- notification preference code/tests when delivery preferences change.

## Choosing the correct layer

| Goal | Layer |
| --- | --- |
| Change canonical franchise facts | Snapshot |
| Change continuity or series-line logic | Snapshot |
| Change section placement | UI grouping |
| Change section order or visibility | UI grouping / layout metadata |
| Change imported entries | Import profiles |
| Change imported entry status | Import creation path |
| Change scan cadence/backoff | Import state |
| Change cache TTL or freshness | Cache |
| Change canonical aliases | Cache |
| Change badges/tooltips/current markers | Rendering |
| Change entry-added notifications | Import / Events |

## Common change scenarios

| I want to... | Start with |
| --- | --- |
| Change canonical root behavior | Snapshot |
| Change continuity or `Series` entries | Snapshot + `SeriesBuilder` |
| Add a new visible section | UI grouping rules + section metadata |
| Move entries between sections | UI grouping rules |
| Change spin-off or alternative refinement | `secondary_refinement_rules.py` |
| Change which entries are imported | Import profiles |
| Change import scan timing | Import scan state / scheduler settings |
| Change cache TTL or freshness | Cache settings and cache service |
| Change cache alias policy | Cache alias helpers |
| Change badges, tooltips, or displayed images | Rendering/context enrichment |
| Change notifications for imported entries | Import flow / events |

Use this table as the first routing step. Once the owning layer is clear, use the sections below for the main files and tests.

## Common mistakes

### Fixing grouping in templates

Templates render prepared context. If placement is wrong, the fix usually belongs in rule packs or snapshot facts, not in `media_details.html`.

### Using UI sections for import decisions

UI sections are optimized for detail-page readability. Import profiles decide what should be created in a user library and should not blindly mirror visible sections.

### Fixing import behavior through UI rules

Import profiles and UI grouping are independent projections.

If imported entries are wrong, fix the import profile logic instead of changing section placement.

### Putting user data into cached payloads

Complete franchise cache payloads must stay user-agnostic. Status, progress, and current-user item data belong in request-time enrichment.

### Duplicating snapshot logic

If multiple layers need the same franchise fact, add it to the snapshot instead of recalculating it in UI, import, or cache code.

### Changing cache lookup to fix placement

Cache lookup decides which prepared payload is loaded. It should not be used to move entries between sections.

### Adding one-off view patches

Views orchestrate cache and context preparation. Placement policy belongs in the UI rule pipeline.

## Where to add tests

Snapshot changes should normally update:

- `src/app/tests/services/test_anime_franchise_snapshot.py`
- `src/app/tests/services/test_anime_franchise.py`

UI grouping changes should normally update:

- `src/app/tests/services/test_anime_franchise_ui_pipeline.py`

Import changes should normally update:

- `src/app/tests/services/test_anime_franchise_import_profiles.py`
- `src/app/tests/test_anime_franchise_import.py`
- `src/app/tests/test_import_anime_franchise_command.py`

Cache changes should normally update:

- `src/app/tests/services/test_anime_franchise_cache.py`
- `src/app/tests/services/test_anime_franchise_scoped_payload.py`
- `src/app/tests/services/test_anime_franchise_context.py`
- `src/app/tests/test_anime_franchise_cache_warmer.py`

Rendering, task, and view changes should normally update:

- `src/app/tests/views/test_media_details.py`
- `src/app/tests/test_anime_franchise_footer.py`
- `src/app/tests/test_tasks.py`

## Safe change checklist

- The owning layer is identified.
- Snapshot fields remain deterministic.
- UI/import/cache projections stay separate.
- Rule placement changes are covered by placement tests.
- Cache payload compatibility is considered.
- User-specific data is not written to complete franchise cache.
- Settings docs are updated if defaults/settings change.
- Runbook commands remain valid.

## Scoped detail payload rules

Detail-specific payloads are selected by ordered rules in `anime_franchise_scoped_payload.py`. The first valid rule result is saved under `mal_anime_franchise_scoped_<seed_id>` with `payload_role = "detail_scoped"`, `detail_payload_kind`, `rule_key`, `build_seed_media_id`, and `global_canonical_root_media_id`. Rules must not write Redis or include user-specific data.

## Detail-scoped rules

The detail-scoped rule system currently ships with one implemented rule:

- `non_tv_seed_to_tv_context_v1`, which produces `detail_payload_kind = "seed_context"` for supported non-TV seeds.

Do not add placeholder rules. New detail-scoped rules should only be introduced when they have distinct behavior and dedicated tests.
