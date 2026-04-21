# Anime Franchise Grouping (MAL anime)

This document describes the real grouping pipeline used by the anime details page.

## Functional scope

- Enabled by `ANIME_FRANCHISE_GROUPING_ENABLED`.
- Applied only when `source=mal` and `media_type=anime` in `media_details`.
- Grouping output is injected as `anime_franchise` context and rendered by `media_details.html`.

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
- `fallback_anchor_media_id`: seed fallback anchor when no series line exists.
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

- Series section stays empty.
- Seed/root becomes fallback anchor for direct candidate collection.
- No fake series entry is injected.

## UI rules and first-match-wins

Rules are evaluated by ordered packs from `anime_franchise_ui/presets/default.py`:

1. `base_facts`
2. `base_placement`
3. `relation_rules`
4. `anchor_rules`
5. `format_rules`
6. `section_rules`

`ensure_section(...)` is declaration-only (create-if-missing), while explicit
section mutations are applied via dedicated setters.

Current visible sections:

1. `continuity_extras` (Main Story Extras)
2. `specials`
3. `related_series`

Internal section:

- `ignored` (not shown in UI)

### Current rule intent

- `ignored`: swallows `cm`, `pv`, and relation `other`.
- `continuity_extras`: direct-only prequel/sequel satellites in non-TV narrative formats.
- `specials`: direct-only side-story/summary/full-story satellites.
- `related_series`: direct-only spin-off/parent/alternative/character relations.

## Default values currently applied (UI groups)

These are declared by the default UI pipeline rule packs. Section visibility is
driven by section `metadata["visible_in_ui"]`, propagated through layout and
consumed by the adapter.

### `series_line` (rendered as **Series**)

- Built from snapshot `series_line` only (TV-only continuity line).
- Not a rule-driven candidate group.
- Entries are rendered in snapshot order.

### `ignored` (internal, not rendered)

- `visible_in_ui`: `False` (metadata)
- receives at least: relation `other`, `cm`, `pv`, and non-direct anchors.
- `hidden_if_empty`: `True`

### `continuity_extras` (**Main Story Extras**)

- `visible_in_ui`: `True` (metadata)
- coarse relation placement: `prequel` / `sequel`
- coarse format filter: excludes `tv`, `cm`, `pv`
- `hidden_if_empty`: `True`

### `specials`

- `visible_in_ui`: `True` (metadata)
- coarse relation placement: `side_story`, `summary`, `full_story`
- coarse format filter: `ona` excluded from `specials`
- `hidden_if_empty`: `True`

### `related_series`

- `visible_in_ui`: `True` (metadata)
- coarse relation placement: `spin_off`, `parent_story`, `alternative_setting`,
  `alternative_version`, `character`
- `hidden_if_empty`: `True`

## View and template integration

In `media_details`:

- Franchise grouping is gated by MAL + anime + setting.
- `AnimeFranchiseService().build(media_id)` runs snapshot + UI pipeline.
- Result entries are enriched with user data.
- Footer display metadata is added via `anime_franchise_footer.py`.
- Legacy `media.related.related_anime` is removed to prevent duplicate display.

In `media_details.html`:

- Template renders `Series` and generic section blocks.
- No grouping logic is implemented in the template.

## Design constraints

- Keep classification in services, not in templates.
- Keep MAL normalization in provider helper.
- Keep snapshot as the only canonical franchise domain object.
- Keep `layout.py` structural only (group/filter/order/metadata propagation).
- `anime_franchise_ui_profile.py` remains transitional in-repo and is no longer
  the main UI path.
