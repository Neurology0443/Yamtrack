# Anime Franchise Grouping Debugging Runbook

This runbook documents practical commands for debugging MAL anime franchise grouping in host or Docker environments.

## 1) Preconditions

- Scope: MAL anime detail pages only.
- Feature flag: `ANIME_FRANCHISE_GROUPING_ENABLED=True`.
- Host repo layout: `manage.py` is under `src/`.

## 2) Targeted tests

### Host

```bash
cd src
python manage.py test app.tests.services.test_anime_franchise_ui_pipeline
python manage.py test app.tests.services.test_anime_franchise
python manage.py test app.tests.views.test_media_details
```

### Docker

```bash
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test app.tests.services.test_anime_franchise"
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test app.tests.views.test_media_details"
```

## 3) Inspect service payload shape

```bash
cd src
python manage.py shell
```

```python
from pprint import pprint
from app.services.anime_franchise import AnimeFranchiseService

payload = AnimeFranchiseService().build("5114")
print("root:", payload.root_media_id, payload.display_title)
print("series:", [entry["media_id"] for entry in payload.series["entries"]])
for section in payload.sections:
    print(section["key"], section["title"], len(section["entries"]))
    pprint([
        {
            "media_id": entry["media_id"],
            "anime_media_type": entry.get("anime_media_type"),
            "relation_type": entry.get("relation_type"),
            "linked_index": entry.get("linked_series_line_index"),
            "badges": entry.get("badges", []),
        }
        for entry in section["entries"]
    ])
```

## 4) Inspect internal placement trace (pipeline-level)

`placement_trace` is internal metadata on candidates during pipeline execution; it is not exposed in final adapter payload.

```python
from app.services.anime_franchise_ui import AnimeFranchiseUiPipeline
from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService
from app.services.anime_franchise_ui.rule_types import RuleContext

snapshot = AnimeFranchiseSnapshotService().build("5114")
pipeline = AnimeFranchiseUiPipeline()
candidates = pipeline.candidate_assembler.build(snapshot)
context = RuleContext(snapshot=snapshot)
pipeline.rule_pipeline.run(candidates=candidates, context=context)

for candidate in candidates:
    if candidate.metadata.get("placement_trace"):
        print(candidate.media_id, candidate.metadata["placement_trace"])
```

## 5) Validate fallback behavior when `series_line` is empty

Expected behavior:

- `Series` is empty.
- Root/seed is used as fallback anchor for direct candidates.
- Section fallback (`related_series`) applies only if no earlier rule classified the candidate.

## 6) Rule-order troubleshooting

Packs are executed in this order:

1. `base_facts`
2. `base_placement`
3. `relation_rules`
4. `anchor_rules`
5. `format_rules`
6. `section_rules`

Placement is not global first-match-wins: later packs may override `section_key`, and those changes are recorded in `placement_trace`.
