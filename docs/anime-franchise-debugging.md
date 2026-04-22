# Anime Franchise Grouping Debugging Runbook

This runbook targets the **current** MAL anime franchise UI grouping system.

It is organized by practical debug steps and keeps host/Docker workflows aligned.

## 1) Preconditions and scope

- Scope: MAL anime detail pages only (`source=mal`, `media_type=anime`).
- Feature flag: `ANIME_FRANCHISE_GROUPING_ENABLED=True`.
- Repo layout: `manage.py` is under `src/`.
- Active grouping path:
  `AnimeFranchiseService -> AnimeFranchiseUiPipeline -> SeriesBuilder -> UiCandidateAssembler -> RulePipeline -> LayoutCompiler -> ViewModelAdapter -> views.py`.

## 2) Targeted tests (fast confidence pass)

### Host

```bash
cd src
python manage.py test app.tests.services.test_anime_franchise_ui_pipeline
python manage.py test app.tests.services.test_anime_franchise
python manage.py test app.tests.services.test_anime_franchise_snapshot
python manage.py test app.tests.views.test_media_details
```

### Docker

```bash
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test app.tests.services.test_anime_franchise_ui_pipeline"
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test app.tests.services.test_anime_franchise"
docker compose exec yamtrack sh -lc "cd /yamtrack && python manage.py test app.tests.views.test_media_details"
```

## 3) Inspect principal service payload (adapter output)

Use this to inspect what the modern pipeline returns before view enrichment:

```bash
cd src
python manage.py shell
```

```python
from pprint import pprint
from app.services.anime_franchise import AnimeFranchiseService

payload = AnimeFranchiseService().build("5114")
print("root:", payload.root_media_id, payload.display_title)
print("series entries:", [entry["media_id"] for entry in payload.series["entries"]])

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

## 4) Inspect view-level context shaping (post-adapter)

The view currently rebuilds `anime_franchise` context and enriches entries.

Quick checks in `media_details` response context:

- `series_label` exists on series entries,
- section entries include footer presentation fields,
- `related_anime` removed from legacy related block when grouping is enabled.

Tip: use `app.tests.views.test_media_details` as baseline assertions for this layer.

## 5) Inspect internal placement trace (pipeline-level)

`placement_trace` is internal candidate metadata. It is not part of the final template payload.

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
    trace = candidate.metadata.get("placement_trace")
    if trace:
        print(candidate.media_id, trace)
```

Interpretation:

- `kind="initial"`: first section assignment.
- `kind="override"`: later pack changed section.

## 6) Rule-order troubleshooting and overrides

Current ordered packs:

1. `base_facts`
2. `base_placement`
3. `relation_rules`
4. `anchor_rules`
5. `format_rules`
6. `section_rules`

Current behavior:

- not global first-match-wins,
- later packs can override `section_key`,
- `section_rules` is metadata-only.

If a candidate lands in an unexpected section:

1. inspect `relation_types` and `metadata["relation_facts"]`,
2. inspect `placement_trace` transitions,
3. verify anchor flags (`has_series_line_origin`, `has_root_origin`),
4. verify format gates (`cm`, `pv`, and section-specific exclusions).

## 7) Fallback no-series-line verification

Expected current behavior:

- `snapshot.has_series_line == False`,
- `Series` block empty,
- fallback/root anchor still drives candidate gathering,
- fallback placement (`related_series`) used only when no earlier rule assigned section.

Use `app.tests.services.test_anime_franchise_snapshot` + `test_anime_franchise_ui_pipeline` when adjusting this behavior.

## 8) Relation normalization check

When relation labels look wrong, verify normalization quickly:

```python
from app.providers import mal
print(mal.normalize_relation_type("Side Story"))
print(mal.normalize_relation_type("full-story"))
```

Also run:

```bash
cd src
python manage.py test app.tests.services.test_anime_franchise -k normalize_relation
```

## 9) Graph extraction / snapshot check

If anchors or continuity are suspicious, inspect snapshot fields directly:

```python
from app.services.anime_franchise_snapshot import AnimeFranchiseSnapshotService

snapshot = AnimeFranchiseSnapshotService().build("5114")
print("has_series_line:", snapshot.has_series_line)
print("canonical_root_media_id:", snapshot.canonical_root_media_id)
print("fallback_anchor_media_id:", snapshot.fallback_anchor_media_id)
print("series_line:", [node.media_id for node in snapshot.series_line])
print("direct_anchors:", [node.media_id for node in snapshot.direct_anchors])
print("direct_candidates:", len(snapshot.direct_candidates))
```

## 10) Legacy related de-duplication check

When grouping is enabled, page related items should not duplicate franchise items via `related_anime`.

Run:

```bash
cd src
python manage.py test app.tests.views.test_media_details -k related_anime
```

## 11) Cache and refresh checks

For stale grouping output:

- compare normal build vs `refresh_cache=True` path at service/snapshot level,
- run snapshot cache tests:

```bash
cd src
python manage.py test app.tests.services.test_anime_franchise_snapshot -k cache
```

## 12) Suggested troubleshooting order

1. Reproduce with targeted test(s).
2. Inspect snapshot semantics.
3. Inspect pipeline payload (adapter output).
4. Inspect `placement_trace` for overrides.
5. Inspect view-level enrichment/output shaping.
6. Confirm template is only displaying provided context.
7. Validate cache freshness if behavior appears inconsistent.
