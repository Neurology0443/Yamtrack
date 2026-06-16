# Anime franchise cache

## Product behavior

Large MAL franchises should not be rebuilt during the detail-page request. The page can render a prepared franchise payload, and refreshes happen in the background when data is stale, missing, or invalid.

## Why this cache exists

Franchise graph hydration can require multiple MAL calls and relation walks. The complete franchise cache moves that work to Celery so the web request remains responsive and predictable.

## Cache lifecycle

The complete franchise cache has two jobs:

1. serve a ready-to-render franchise payload to the detail page;
2. move expensive franchise rebuilds to background tasks.

A normal lifecycle looks like this:

```text
detail page opened
 -> cache lookup by current media ID
 -> direct payload or canonical alias resolved
 -> payload validated
 -> request-specific user data added
 -> page rendered
```

When the payload is missing, stale, or invalid, the page does not block on a full rebuild. It keeps the normal related-anime fallback when needed and schedules a background task.

## What happens when a page is opened

```text
User opens anime detail page
        ↓
Resolve cache key
        ↓
Load payload
```

The page then follows the cache state for that media ID:

```text
Fresh payload
    ↓
Render page

Stale payload
    ↓
Render page
    ↓
Queue refresh

Missing payload
    ↓
Fallback related anime
    ↓
Queue build

Invalid payload
    ↓
Fallback related anime
    ↓
Queue rebuild
```

A fresh payload renders immediately. A stale payload still renders, then refreshes in the background when cooldowns and locks allow it. Missing or invalid payloads do not block the request; the normal related-anime fallback remains visible for that request while a build or rebuild is queued.

## Payload contract

Complete franchise payloads must be:

- user-agnostic;
- JSON-safe;
- schema-versioned;
- free of `Item`, `BasicMedia`, ORM objects, user IDs, current-user status/progress, and rendered HTML;
- enriched with user-specific data only when read for a request.

The cache writer validates payload shape and rejects user-specific or non-JSON-safe values.

## What is stored vs enriched

Stored in cache:

- franchise structure;
- media IDs;
- titles;
- relation metadata;
- section keys and ordering;
- schema/cache metadata.

Added only during request rendering:

- current user status;
- progress;
- user-specific item data;
- current-entry markers;
- footer display helpers that depend on the current page/user context;
- opportunistic image updates when Yamtrack has a more recent or more complete local image than the cached franchise payload.

The franchise cache stores a user-agnostic payload. Some display data can still be improved at request time.

For example, Series entries may reuse a more recent image already known by Yamtrack instead of continuing to display an older image embedded in the cached franchise payload.

This enrichment improves visual consistency without requiring a full franchise rebuild.

This separation allows the same cached franchise payload to be reused safely for different users.

## Canonical payload

A franchise can be stored under one canonical root. The canonical media ID is usually the first entry in the fixed `Series` line, falling back to `canonical_root_media_id` or the seed when needed.

Canonical storage avoids duplicating the same complete franchise payload under every related media ID.

## Canonical aliases

Aliases are lightweight keys from selected media IDs to the canonical payload. They are useful when a user opens an OVA, movie, or main-story extra and should still get the full canonical franchise payload.

Important constraints:

- aliases do not change UI placement;
- aliases point only to IDs allowed by `extract_aliasable_media_ids()`;
- currently aliasable IDs are fixed `Series` entries and `continuity_extras` entries;
- truncated payloads skip unsafe aliasing;
- invalid aliases are ignored and cleaned up by normal lookup behavior.

Example:

If the canonical franchise payload is stored under the first TV entry, opening a main-story OVA can still resolve to that canonical payload through `mal_anime_franchise_alias_<ova_id>`.

The alias only changes cache lookup. It does not move the OVA into a different UI section.

Example flow:

```text
Canonical TV entry
    ↓
stores canonical franchise payload

Main-story movie / OVA
    ↓
alias key
    ↓
resolves to the same canonical franchise payload
```

This lets related main-story pages reuse the complete franchise view without duplicating the payload. The alias still does not change UI placement.

Alias resolution only decides which cached franchise view is loaded. The loaded view still uses the section placement produced by the UI grouping pipeline.

Import profiles never use cache aliases for selection decisions.

## Stale-while-refresh

A cached payload can be valid but no longer fresh.

Freshness and storage TTL are different:

- `ANIME_FRANCHISE_CACHE_FRESH_DAYS` controls when a valid payload should be refreshed.
- `ANIME_FRANCHISE_CACHE_TTL_DAYS` controls how long Redis/cache keeps the payload before it disappears.

This allows Yamtrack to keep rendering a known-good franchise while refreshing it in the background.

Current behavior:

```text
fresh hit
 -> render cached payload

stale hit
 -> render cached payload
 -> schedule background refresh when cooldown/locks allow

miss
 -> keep normal related-anime fallback for this request
 -> schedule background build

invalid payload
 -> ignore cached payload
 -> keep fallback visible
 -> record metadata/error when applicable
 -> schedule rebuild when cooldown/locks allow

build error
 -> record error metadata
 -> preserve previous valid payload when available
```

In practice, stale-while-refresh means users should not lose a working franchise page just because the cache needs to be updated.

Example timeline:

```text
Day 0
  payload is built and cached

Day 45
  page opens
  payload is still fresh
  page renders immediately

Day 120
  page opens
  payload is valid but stale
  page still renders immediately
  background refresh is queued

User result
  the page stays usable while Yamtrack refreshes the franchise
```

The exact timing depends on `ANIME_FRANCHISE_CACHE_FRESH_DAYS` and `ANIME_FRANCHISE_CACHE_TTL_DAYS`.

## Warmup

After import-created entries commit, `schedule_mal_anime_franchise_cache_warm()` queues a forced build for the component root. Warmup:

- bypasses freshness checks;
- still uses `:queue_lock`;
- is executed by the same `Build MAL anime franchise payload` task;
- uses `:task_lock` in the worker to avoid concurrent builds.

## Detail-page behavior

- `load_payload_for_media()` resolves direct payloads and aliases.
- Valid payloads are prepared with current-user data by `prepare_anime_franchise_context()`.
- Stale payloads can render and queue refresh.
- Misses and invalid payloads keep the normal related-anime fallback visible for that request.
- Non-displayable payloads do not hide the fallback.

## Failure behavior

- Queue lock prevents duplicate enqueues for the same ID.
- Task lock prevents concurrent worker builds for the same ID.
- `mark_attempt()` updates metadata before a build.
- `mark_error()` records failure metadata and preserves previous successful payload data.
- Invalid build output is not saved as the active payload.
- Truncated builds can save scoped payloads but avoid unsafe canonical alias replacement.

## Redis keys

Exact key helpers in `anime_franchise_cache.py`:

- Payload: `mal_anime_franchise_<media_id>`
- Metadata: `mal_anime_franchise_<media_id>:meta`
- Alias: `mal_anime_franchise_alias_<media_id>`
- Alias index: `mal_anime_franchise_<canonical_media_id>:aliases`
- Queue lock: `mal_anime_franchise_<media_id>:queue_lock`
- Task lock: `mal_anime_franchise_<media_id>:task_lock`
- Import task lock: `anime-franchise-import:<profile>`

## Commands

```bash
docker compose exec redis redis-cli keys '*anime*franchise*'
docker compose exec redis redis-cli get mal_anime_franchise_34161
docker compose exec redis redis-cli get mal_anime_franchise_34161:meta
docker compose exec redis redis-cli get mal_anime_franchise_alias_34428
docker compose exec redis redis-cli get mal_anime_franchise_34161:aliases
docker compose exec redis redis-cli del mal_anime_franchise_34161 mal_anime_franchise_34161:meta mal_anime_franchise_34161:aliases
docker compose exec redis redis-cli del mal_anime_franchise_alias_34428
docker compose exec yamtrack python manage.py shell -c "from app.tasks import build_mal_anime_franchise_payload; build_mal_anime_franchise_payload.delay('34161')"
```

## Settings

| Setting | Purpose |
| --- | --- |
| `ANIME_FRANCHISE_CACHE_TTL_DAYS` | Redis/cache lifetime for payload and metadata keys. After this, the cached entry can disappear. |
| `ANIME_FRANCHISE_CACHE_ALIASES_ENABLED` | Enables alias keys from selected media IDs to the canonical franchise payload. |
| `ANIME_FRANCHISE_CACHE_FRESH_DAYS` | Logical freshness window. Older valid payloads can still render, but should trigger background refresh. |
| `ANIME_FRANCHISE_BUILD_COOLDOWN_HOURS` | Minimum delay before scheduling another normal rebuild after a recent build attempt/success. |
| `ANIME_FRANCHISE_RETRY_AFTER_ERROR_HOURS` | Minimum delay before retrying a rebuild after an error. |
| `ANIME_FRANCHISE_QUEUE_LOCK_MINUTES` | Temporary lock that prevents duplicate build tasks from being queued for the same media ID. |
| `ANIME_FRANCHISE_TASK_LOCK_MINUTES` | Worker-side lock that prevents concurrent builds for the same media ID. |
| `ANIME_FRANCHISE_MAX_NODES` | Maximum franchise graph size to hydrate before treating the build as truncated/scoped. Values `<= 0` are treated as unlimited by the graph builder. |
| `ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION` | Payload schema version. Changing it invalidates incompatible cached payload shapes. |
