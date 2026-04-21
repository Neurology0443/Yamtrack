# Anime Franchise Grouping (MAL anime)

This document describes the real grouping pipeline used by the anime details page.

## Functional scope

- Enabled by `ANIME_FRANCHISE_GROUPING_ENABLED`.
- Applied only when `source=mal` and `media_type=anime` in `media_details`.
- Grouping output is injected as `anime_franchise` context and rendered by `media_details.html`.
- Import behavior is out of scope for this document.

## Pipeline and file map

1. **MAL provider data** (`app/providers/mal.py`).
2. **Graph normalization** (`app/services/anime_franchise_graph.py`).
3. **Canonical snapshot** (`app/services/anime_franchise_snapshot.py`).
4. **UI pipeline projection**
   - `app/services/anime_franchise_ui/series.py`
   - `app/services/anime_franchise_ui/assembler.py`
   - `app/services/anime_franchise_ui/presets/default.py`
   - `app/services/anime_franchise_ui/engine.py`
   - `app/services/anime_franchise_ui/layout.py`
   - `app/services/anime_franchise_ui/adapter.py`
5. **Facade service** (`app/services/anime_franchise.py`).
6. **View integration** (`app/views.py`).
7. **Rendering** (`templates/app/media_details.html`).

## Snapshot semantics

`AnimeFranchiseSnapshot` defines the canonical franchise state:

- `continuity_component`: transitive component connected by `prequel/sequel`.
- `series_line`: TV-only ordered line derived from continuity.
- `direct_anchors`: where direct neighbors are collected.
- `direct_candidates`: direct normalized relations from anchors.
- `canonical_root_media_id`: canonical component root.
- `fallback_anchor_media_id`: seed fallback anchor when no TV line exists.
- `has_series_line`: indicates whether TV continuity exists.

### Required business details

- `series_line` is **TV-only**.
- `continuity_component` is **transitive prequel/sequel**.
- `direct_anchors` are:
  - full `series_line` (plus root if not in line), or
  - only root when no `series_line`.
- `direct_candidates` come from direct relations of anchors.
- `canonical_root_media_id`:
  - first `series_line` entry when available,
  - otherwise earliest continuity node by date/id ordering.

### Fallback behavior (no `series_line`)

- `Series` stays empty.
- Seed/root becomes fallback anchor for direct candidate collection.
- No fake series entry is injected.

## Series vs secondary sections

- `Series` is fixed and built only from `snapshot.series_line`.
- Secondary sections are dynamic and assigned by the rule pipeline.
- `layout.py` remains structural (group/filter/order + metadata propagation), with no business placement rules.

## Rule packs, execution order, and override discipline

Packs are evaluated in order from `anime_franchise_ui/presets/default.py`:

1. `base_facts`
2. `base_placement`
3. `relation_rules`
4. `anchor_rules`
5. `format_rules`
6. `section_rules`

Runtime behavior is **ordered evaluation with allowed overrides**, not first-match-wins:

- `base_placement` assigns the initial fallback section for unclassified candidates.
- `relation_rules`, `anchor_rules`, and `format_rules` may rewrite `section_key`.
- `section_rules` updates section metadata only and does not move candidates.
- The engine records `candidate.metadata["placement_trace"]` whenever `section_key` changes so initial placement and overrides stay auditable.

## Current section policy

Visible sections:

1. `continuity_extras` (Main Story Extras)
2. `specials`
3. `related_series`

Internal section:

- `ignored` (`visible_in_ui=False`)

### Placement intent

- `base_placement` declares section definitions once and applies fallback placement to `related_series` when no section was set yet.
- `relation_rules` classifies using relation facts derived from `relation_types` (not only `relation_type`) so ambiguous candidates use richer relation signals.
- `anchor_rules` keeps only direct/fallback-anchored candidates in visible sections.
- `format_rules` applies conservative media-format refinements (e.g. `cm/pv` => `ignored`).
- `section_rules` stabilizes titles/order/hidden policy and never rewrites `section_key`.

## Adapter and template contract

- Adapter is a compatibility layer from compiled sections to template payload shape.
- Section visibility comes from section metadata (`visible_in_ui`).
- Footer labels/badges are still applied in `anime_franchise_footer.py` during view enrichment.
- No classification logic is implemented in template/view/layout.

## Design constraints

- Keep business classification in rule packs.
- Keep `Series` fixed from `snapshot.series_line`.
- Keep `layout.py` structural-only.
- Keep adapter as compatibility-only.
- Do not reintroduce the deleted legacy UI profile/rules path.


## Relation signal fields

- `relation_type`: compatibility facade (single representative value).
- `relation_types`: richer relation set used by ambiguous placement rules.
- `metadata["origins"]`: detailed provenance captured by assembler; useful for debugging and future targeted rules, but not currently a primary placement driver.
