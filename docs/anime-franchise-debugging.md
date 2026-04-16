# Anime Franchise Grouping Debugging Runbook

This runbook documents practical commands for debugging MAL anime franchise grouping in both Docker and host environments.

## 1) Preconditions

- Feature scope: MAL anime detail pages only.
- Feature flag: `ANIME_FRANCHISE_GROUPING_ENABLED=True`.
- Repository layout: `manage.py` is under `src/` on host.

## 2) Host-native workflow

From repository root:

```bash
python -m pip install -U -r requirements-dev.txt
cd src
python manage.py migrate
python manage.py runserver
```

Optional Redis for local cache behavior:

```bash
docker run -d --name redis -p 6379:6379 --restart unless-stopped redis:8-alpine
```

## 3) Docker-native workflow

The compose service is `yamtrack`.

Start stack:

```bash
docker compose up -d
```

View logs:

```bash
docker compose logs -f yamtrack
```

Open shell in app container:

```bash
docker compose exec yamtrack sh
```

In container shell (working directory is `/yamtrack`):

```bash
python manage.py shell
```

## 4) Targeted tests

### Host

```bash
cd src
python manage.py test app.tests.services.test_anime_franchise
python manage.py test app.tests.views.test_media_details
python manage.py test app.tests.services.test_anime_franchise app.tests.views.test_media_details
```

### Docker

```bash
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test app.tests.services.test_anime_franchise"
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test app.tests.views.test_media_details"
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test app.tests"
```

## 5) Inspect service output in Django shell

Host:

```bash
cd src
python manage.py shell
```

Then:

```python
from pprint import pprint
from app.services.anime_franchise import AnimeFranchiseService

vm = AnimeFranchiseService().build("5114")  # replace with target MAL anime id
print("root:", vm.root_media_id, vm.display_title)
print("series_line:", [entry["media_id"] for entry in vm.series_line_entries])
for section in vm.sections:
    print(section.key, len(section.entries))
    pprint([
        (
            entry["media_id"],
            entry.get("anime_media_type"),
            entry.get("relation_type"),
            entry.get("linked_series_line_index"),
        )
        for entry in section.entries
    ])
```

## 6) Validate fallback behavior when `series_line` is empty

Expected behavior:

- `Series` is empty.
- Seed is used only as an internal fallback anchor.
- Direct seed neighbors can still match direct-only rules.

Quick shell check:

```python
from app.services.anime_franchise import AnimeFranchiseService

vm = AnimeFranchiseService().build("<non-tv-seed-id>")
print(vm.series_line_entries)  # should be []
for section in vm.sections:
    print(section.key, [entry["media_id"] for entry in section.entries])
```

## 7) Verify MAL relation data and normalization

```python
from app.providers import mal

data = mal.anime("5114")
for rel in data.get("related", {}).get("related_anime", []):
    print(rel["media_id"], rel.get("relation_type"), rel["title"])

print(mal.normalize_relation_type("Side Story"))   # side_story
print(mal.normalize_relation_type("full-story"))   # full_story
```

## 8) Verify graph extraction

```python
from app.services.anime_franchise_graph import AnimeFranchiseGraphBuilder

graph = AnimeFranchiseGraphBuilder().build("5114")
print("nodes:", sorted(graph.keys()))
for node_id, node in graph.items():
    for rel in node.relations:
        print(node_id, "->", rel.target_media_id, rel.relation_type)
```

## 9) Validate legacy related de-duplication

With franchise grouping active on MAL anime details:

- `anime_franchise` must be present in context.
- `media.related.related_anime` must be removed.
- other legacy sections (for example `recommendations`) must remain.

This is covered by view tests in `app.tests.views.test_media_details`.

## 10) Cache checks

MAL anime cache key pattern:

- `mal_anime_<id>`

In shell:

```python
from django.core.cache import cache

cache.get("mal_anime_5114")
cache.delete("mal_anime_5114")
```

## 11) Rule priority troubleshooting

Matching order (first match wins):

1. `ignored`
2. `continuity_extras`
3. `specials`
4. `related_series`

If an entry disappears from UI, confirm it is not consumed by `ignored` first.
