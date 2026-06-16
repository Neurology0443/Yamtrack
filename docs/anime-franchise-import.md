# Anime franchise import

## Product behavior

When a user tracks a MAL anime, this fork can discover missing MAL anime entries from the same franchise and create library entries for them. Imports are profile-based so Yamtrack can expand useful continuity without blindly importing every related MAL entry. Profile decisions are built from the normalized snapshot; see `docs/anime-franchise-snapshot.md` for the shared snapshot model.

## Simple user flow

```text
User tracks a MAL anime
      ↓
Import scan runs
      ↓
Missing franchise entries are discovered
      ↓
Entries are created as Planning
      ↓
Notification is sent when enabled
      ↓
Future scans keep monitoring the franchise
```

The import system is designed to reduce manual searching while keeping automatically added entries easy to review.

## Important: UI grouping is not import selection

UI grouping and import selection are intentionally independent.

An entry can appear in a visible franchise section without being imported automatically. Likewise, import profiles are not required to mirror UI sections.

UI grouping optimizes detail-page readability. Import profiles optimize which missing entries are useful enough to create in a user's library.

## Import flow

```text
Existing user MAL anime
 -> due seed selection
 -> snapshot build (see `docs/anime-franchise-snapshot.md`)
 -> profile selection
 -> missing entry creation
 -> scan-state update
 -> notifications
 -> optional cache warmup
```

Execution surfaces:

- management command `python manage.py import_anime_franchise`;
- Celery task `Import anime franchise`;
- optional Beat schedule entry `auto_import_anime_franchise`.

## When to use each profile

### `continuity`

- Recommended default profile.
- Imports main continuity entries.
- Best balance between usefulness and avoiding noise.

### `satellites`

- Adds selected side content around the main continuity.
- More aggressive than `continuity`.
- Useful when users want side stories, alternatives, or selected spin-offs.
- Short non-`tv_special` single-episode satellites are allowed only when their local `prequel`/`sequel` branch is fully known and has runtimes of at least 15 minutes.


### `complete`

- Maximum franchise coverage.
- Combines `continuity` and `satellites`.
- Useful for users who want the broadest automatic coverage.

All automatically imported entries are created with the `Planning` status.

Users remain responsible for moving imported entries to another status when they decide to start watching them.

## Profiles

### `continuity`

- Seed mode: all eligible library MAL anime entries.
- Continuity mode: transitive continuity component.
- Selects IDs from `snapshot.continuity_component`.
- Excludes MAL media types `cm` and `pv`.
- Excludes entries with runtime `<= 15` minutes when runtime is known.
- Excludes targets of normalized `summary` relations.

### `satellites`

- Seed mode: canonical roots only, based on known scan-state component root.
- Satellites mode: direct-only.
- Included relation types: `spin_off`, `alternative_version`, `side_story`.
- Excludes MAL media types `cm` and `pv`.
- `tv_special` requires known runtime greater than 15 minutes.
- Other targets require known runtime at least 15 minutes.
- For non-`tv_special` targets, single-episode entries with runtime `<= 30` minutes are treated as short satellite candidates.
- Short satellite candidates are accepted only when their local `prequel`/`sequel` branch is fully available in the snapshot.
- Every entry in that local branch must have a known runtime of at least 15 minutes.
- If the local branch contains a missing node, unknown runtime, or runtime below 15 minutes, the candidate is excluded.

### `complete`

- Union of `continuity` and `satellites`.
- Fingerprint payload includes both profile selections and the union IDs.

## Seed selection

`AnimeImportStateService.select_due_seeds()` considers existing `Anime` rows where:

- source is MAL;
- media type is anime;
- status is `Planning`, `In progress`, or `Completed`.

Optional filters:

- `--user-id` limits users;
- `--limit` caps selected due seeds;
- `--full-rescan` bypasses next-scan due checks.

Canonical-only profiles use known `component_root_mal_id` from previous scan state to avoid scanning satellite profiles from every library entry.

## Scan state

`AnimeImportScanState` is keyed logically by user, seed MAL ID, and profile. It stores:

- last result fingerprint;
- last scanned/success/error timestamps;
- consecutive stable scan count;
- consecutive error count;
- next scan timestamp;
- canonical component root;
- last component size.

Success behavior:

- changed fingerprint: reset stable scans and scan again sooner;
- unchanged fingerprint: increment stable scans and increase delay;
- stable delays include deterministic jitter and cap at a long interval.

Error behavior:

- increment error count;
- exponential backoff up to 24 hours;
- deterministic jitter to avoid synchronized retries.

## Entry creation

For each selected missing MAL ID:

- fetch minimal MAL anime metadata;
- create or reuse the shared `Item` row;
- create an `Anime` row for the user;
- default status is `Planning`;
- `_skip_hot_priority` is set to avoid recursive hot-priority import triggers from the importer-created row.

Creation happens in a transaction. A dry run counts planned creations without writing entries or scan-state successes.

## Notifications

Created entries call the existing entry-added notification hook after transaction commit. Notification delivery still follows the existing events/notification subsystem behavior and user configuration.

## Cache warmup after import

```text
Import creates entries
 -> transaction commit
 -> cache warm task scheduled
 -> detail page can later use prebuilt franchise payload
```

The importer schedules one forced cache warm build per component root per run. Warmup bypasses freshness checks because the user's library changed, but still uses queue locks to avoid duplicate enqueues.

## Commands

The checked-in Compose services are `yamtrack` and `redis`.

```bash
docker compose exec yamtrack python manage.py import_anime_franchise --profile continuity --dry-run
docker compose exec yamtrack python manage.py import_anime_franchise --profile continuity
docker compose exec yamtrack python manage.py import_anime_franchise --profile satellites --limit 10
docker compose exec yamtrack python manage.py import_anime_franchise --profile complete --full-rescan --refresh-cache
docker compose exec yamtrack python manage.py import_anime_franchise --profile continuity --user-id 1
```

## Settings

| Setting | Purpose |
| --- | --- |
| `ANIME_FRANCHISE_IMPORT_AUTOMATION_ENABLED` | Enables or disables scheduled franchise import automation. |
| `ANIME_FRANCHISE_IMPORT_AUTOMATION_INTERVAL_MINUTES` | Beat interval between automatic import runs. |
| `ANIME_FRANCHISE_IMPORT_AUTOMATION_PROFILE` | Profile used by the scheduled import task, such as `continuity`, `satellites`, or `complete`. |
| `ANIME_FRANCHISE_IMPORT_AUTOMATION_REFRESH_CACHE` | Tells scheduled imports whether MAL/provider cache should be refreshed during import. |
| `ANIME_FRANCHISE_IMPORT_AUTOMATION_FULL_RESCAN` | Forces scheduled imports to ignore due times and rescan eligible seeds. |
| `ANIME_FRANCHISE_IMPORT_AUTOMATION_LIMIT` | Maximum number of due seeds processed per scheduled run when configured. |
| `MAL_RATE_LIMIT_PER_MINUTE` | Controls MAL provider request rate to avoid hitting API limits. |

## Failure behavior

- The Celery import task uses lock key `anime-franchise-import:<profile>` and skips if the same profile is already running.
- Per-seed errors are counted and recorded in scan state when not dry-running.
- A failed seed does not abort the whole import run.
- Cache warmup scheduling errors are counted separately from entry creation errors.
