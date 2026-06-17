# Anime franchise debugging

The full debugging guide lives in `docs/anime-franchise-debugging-runbook.md`.

This file is kept as a stable alias for older links and includes the cache alias audit used to diagnose direct/alias conflicts.

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
    if payload:
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
'
```
