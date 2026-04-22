# Architecture Overview

This fork uses a **snapshot-first architecture** for MAL anime franchise behavior.

The snapshot is canonical. UI grouping and import are separate projections on top of that same snapshot.

## Scope

- Applies only to MAL anime franchise behavior (`source=mal`, `media_type=anime`).
- UI grouping and import each have their own projection path.
- This document describes the **currently active path** in app runtime.

## Stable vocabulary used in docs

- **Principal / active path**: code executed by current UI grouping flow.
- **Structural-only**: assembly/ordering utilities that do not make business placement decisions.
- **Compatibility layer**: shape translation for integration with existing view/template contracts.
- **Integration + presentation enrichment**: view-level assembly and display metadata work.
- **Transitional / legacy**: historical behavior still present in repository but not the main grouping engine.

## Layer map

## 1) Provider + graph discovery (principal)

- `src/app/providers/mal.py`
- `src/app/services/anime_franchise_graph.py`

Responsibilities:

- fetch MAL data,
- normalize relation signals,
- build franchise graph inputs for snapshot construction.

## 2) Canonical franchise snapshot (principal)

- `src/app/services/anime_franchise_snapshot.py`

`AnimeFranchiseSnapshot` is the canonical domain object used by both projections. Current fields used by UI/import logic include:

- `continuity_component`
- `series_line`
- `direct_anchors`
- `direct_candidates`
- `promoted_continuity_candidates` (UI-only promoted transitive non-TV continuity projection)
- `canonical_root_media_id`
- `fallback_anchor_media_id`
- `has_series_line`

## 3) UI projection (principal)

- Facade: `src/app/services/anime_franchise.py` (`AnimeFranchiseService`)
- Pipeline: `src/app/services/anime_franchise_ui/__init__.py` (`AnimeFranchiseUiPipeline`)
- Fixed series builder: `src/app/services/anime_franchise_ui/series.py` (`SeriesBuilder`)
- Candidate assembly: `src/app/services/anime_franchise_ui/assembler.py` (`UiCandidateAssembler`)
- Rule engine: `src/app/services/anime_franchise_ui/engine.py` (`RulePipeline`)
- Rule packs: `src/app/services/anime_franchise_ui/rules/*.py`
- Section compilation: `src/app/services/anime_franchise_ui/layout.py` (`LayoutCompiler`, structural-only)
- Payload adaptation: `src/app/services/anime_franchise_ui/adapter.py` (`ViewModelAdapter`, compatibility layer)

Current active preset order (from `anime_franchise_ui/presets/default.py`):

1. `base_facts`
2. `base_placement`
3. `relation_rules`
4. `secondary_refinement_rules`
5. `anchor_rules`
6. `format_rules`
7. `section_rules`

Notes on the added refinement phase:

- `relation_rules` performs coarse section classification first.
- `secondary_refinement_rules` then refines coarse secondary placement:
  - long TV spin-offs (runtime > 40 minutes) move from `related_series` to `spin_offs`,
  - `alternative_version` / `alternative_setting` move to `alternatives`,
  - TV `side_story` entries are reclassified from `specials` to `related_series` before format filtering.
- Section order is intentionally `spin_offs`, then `alternatives`, then residual `related_series`.
- `alternatives` ordering is rule-driven with candidate metadata (`section_sort_rank`), and layout applies only a generic structural sort when that metadata exists.
- `related_series` remains the residual fallback for related entries that do not match refinement rules.

## 4) Import projection (principal, separate from UI projection)

- `src/app/services/anime_franchise_import_profiles.py`
- `src/app/services/anime_franchise_import.py`
- `src/app/services/anime_import_state.py`

Responsibilities:

- import profile behavior,
- profile-driven selection logic,
- incremental scan-state/backoff.

This reuses the snapshot model but is not part of the UI rendering path.

## 5) App delivery / integration

### UI integration + presentation enrichment

- `src/app/views.py` (`media_details`)
- `src/app/anime_franchise_footer.py`
- `src/templates/app/media_details.html`

Current integration behavior:

- calls `AnimeFranchiseService` to get pipeline payload,
- rebuilds page context into the `anime_franchise` block expected by template,
- adds `series_label` to series entries,
- enriches section entries for footer labels/badges,
- passes prepared context to template rendering.

Template role is presentation (looping/display), not placement business logic.

### Import automation / scheduling / notifications

- `src/app/tasks.py`
- `src/app/schedules.py`
- `src/config/settings.py`
- `src/events/notifications.py`
- `src/events/tasks.py`

## UI flow (active path)

```text
app/providers/mal.py
   -> app/services/anime_franchise_graph.py
   -> app/services/anime_franchise_snapshot.py
   -> app/services/anime_franchise.py (AnimeFranchiseService)
   -> app/services/anime_franchise_ui/__init__.py (AnimeFranchiseUiPipeline)
      -> SeriesBuilder (fixed Series from snapshot.series_line)
      -> UiCandidateAssembler
      -> RulePipeline (ordered packs with overrides)
      -> LayoutCompiler (structural-only)
      -> ViewModelAdapter (compatibility shape)
   -> app/views.py (integration + presentation enrichment)
   -> app/anime_franchise_footer.py
   -> templates/app/media_details.html
```

## Import flow (separate projection)

```text
app/providers/mal.py
   -> app/services/anime_franchise_graph.py
   -> app/services/anime_franchise_snapshot.py
   -> app/services/anime_franchise_import_profiles.py
   -> app/services/anime_franchise_import.py
   -> app/services/anime_import_state.py
   -> app/tasks.py / management command / schedules+settings
```

## Legacy note

Some older UI grouping concepts may still exist historically in the repository or tests, but they are not the principal runtime path for MAL anime franchise UI grouping.

When updating behavior, treat the `AnimeFranchiseService -> AnimeFranchiseUiPipeline` path as the source of truth.
