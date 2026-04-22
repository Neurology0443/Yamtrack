# Anime Franchise Import

This document covers profile-based franchise import, incremental scan state, hot-priority behavior, and automation.

## Import flow

```text
mal.py
 -> anime_franchise_graph.py
 -> anime_franchise_snapshot.py
 -> anime_franchise_import_profiles.py
 -> anime_franchise_import.py
 -> anime_import_state.py
 -> Celery task / management command / schedule
```

## Core services

- `anime_franchise_import_profiles.py`: chooses IDs from snapshot per profile.
- `anime_franchise_import.py`: orchestrates due seed selection, creation, and state updates.
- `anime_import_state.py`: persists incremental scan schedule and backoff.

## Import profiles

### `continuity`

- Selects continuity component (`prequel/sequel` transitive set).
- Excludes media types `cm` and `pv`.
- Excludes targets referenced by `summary` relations.
- Applies runtime heuristic (`runtime > 15` when runtime exists).

Default profile values:

- `seed_mode`: `all_library`
- `continuity_mode`: `transitive`
- `satellites_mode`: `none`
- `component_root_mode`: `canonical_component_root`
- `ignored_media_types`: `{"cm", "pv"}`
- `min_runtime_minutes`: `15`

### `satellites`

- Direct-only satellites from `direct_candidates`.
- Does **not** consume `promoted_continuity_candidates` (UI-only projection).
- No additional transitive expansion is applied for satellites selection.
- Eligible relations: `spin_off`, `alternative_version`, `side_story`.
- Explicitly excludes `parent_story`.
- Excludes `cm` and `pv`.
- Applies runtime/episode heuristics:
  - `tv_special` requires runtime and must be `> 15`.
  - non-`tv_special` entries require known runtime.
  - non-`tv_special` entries reject runtime `< 15`.
  - non-`tv_special` one-shot entries reject `episode_count == 1` and runtime `<= 30`.
- Seed mode is `canonical_only` (seed must be known canonical root).

Default profile values:

- `seed_mode`: `canonical_only`
- `continuity_mode`: `none`
- `satellites_mode`: `direct_only`
- `component_root_mode`: `canonical_component_root`
- `ignored_media_types`: `{"cm", "pv"}`
- `include_relation_types`: `{"spin_off", "alternative_version", "side_story"}`
- `min_runtime_minutes`: `15`

### `complete`

- Union of `continuity` and `satellites` selections.
- Continues to inherit `satellites` direct-only behavior from `direct_candidates` only.

Default profile values:

- `seed_mode`: `all_library`
- `continuity_mode`: `transitive`
- `satellites_mode`: `direct_only`
- `component_root_mode`: `canonical_component_root`

## Scan state model

`AnimeImportScanState` persists per `(user, seed_mal_id, profile_key)`:

- `next_scan_at`
- `last_result_fingerprint`
- `consecutive_stable_scans`
- `consecutive_error_count`
- `component_root_mal_id`
- plus timestamps (`last_scanned_at`, `last_success_at`, `last_error_at`, `last_change_at`).

`AnimeImportStateService` handles:

- due seed selection (`select_due_seeds`),
- deterministic fingerprinting,
- success/error recording with backoff and jitter,
- `mark_due_now()` for immediate scheduling.

### Incremental behavior

- Changed result fingerprint => short delay (base 6h).
- Stable fingerprint => increasing delay (base 12h, exponential up to 14 days).
- Errors => exponential backoff up to 24h base (plus jitter).

## Hot-priority behavior on save

`Anime.save()` marks MAL anime seeds due immediately when:

- a MAL anime entry is newly created, **or**
- status changes to `In progress` or `Completed`.

It calls `AnimeImportStateService.mark_due_now()` for all import profiles.

## Entry creation and notifications

Import creation path (`anime_franchise_import.py`):

- creates missing MAL anime entries (`Anime` + `Item`),
- marks `_skip_hot_priority=True` during import-created save to avoid recursive reprioritization,
- queues `notify_entry_added_after_commit(...)`.

This keeps import and manual creation aligned with the same notification flow.

## Execution surfaces

### Celery task

- `app/tasks.py` task `import_anime_franchise`.
- Uses cache lock key `anime-franchise-import:{profile}`.
- Skips run when another run for same profile is active.

### Django command

- `python manage.py import_anime_franchise --profile ...`
- Supports `--dry-run`, `--full-rescan`, `--limit`, `--refresh-cache`, `--user-id`.

### Scheduler and settings

- `app/schedules.py` builds optional beat entry.
- `config/settings.py` controls:
  - `ANIME_FRANCHISE_IMPORT_AUTOMATION_ENABLED`
  - `ANIME_FRANCHISE_IMPORT_AUTOMATION_INTERVAL_MINUTES`
  - `ANIME_FRANCHISE_IMPORT_AUTOMATION_PROFILE`
  - `ANIME_FRANCHISE_IMPORT_AUTOMATION_REFRESH_CACHE`
  - `ANIME_FRANCHISE_IMPORT_AUTOMATION_FULL_RESCAN`
  - `ANIME_FRANCHISE_IMPORT_AUTOMATION_LIMIT`
