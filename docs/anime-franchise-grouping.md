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
4. **UI projection**
   - `app/services/anime_franchise_ui_rules.py`
   - `app/services/anime_franchise_ui_builder.py`
   - `app/services/anime_franchise_ui_profiles.py`
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

Rules are evaluated by priority in `anime_franchise_ui_rules.py`.
The first matching rule consumes the candidate.

Responsibility split:

- `anime_franchise_ui_rules.py`: static, shared rule table that defines default section classification and base sort intent.
- `anime_franchise_ui_builder.py`: orchestrates full flow (base classification, profile visibility/reclassification/sorting/title policy, final `AnimeFranchiseViewModel` assembly).
- `anime_franchise_ui_profiles.py`: global UI policy layer (not a full UI rebuild) with declarative hiding + targeted methods.

Builder robustness note:

- Missing section keys are always treated as empty sections.
- If a profile targets an unknown section key, the builder safely falls back to the default rule-based section.
- Section candidate lookups remain defensive (`.get(section_key, [])`) to avoid `KeyError`.
- `hidden_titles` uses normalized matching (`strip + case-insensitive`) for stable behavior.
- Profile hook return values are validated strictly; invalid types raise explicit `TypeError` (no silent broad coercion).

## UI profile API (niveau 2)

`anime_franchise_ui_profiles.py` is intentionally **policy-level**:

- Declarative flags:
  - `hidden_relation_types`
  - `hidden_media_types`
  - `hidden_titles`
- Targeted policy methods:
  - `is_candidate_visible(candidate)`
  - `target_section_key(candidate, default_section_key)`
  - `sort_section_candidates(section_key, candidates)`
  - `section_title(section_key, default_title, candidates)`

This keeps shared classification in `ui_rules.py`, while allowing profile-specific behavior without re-implementing the entire view model pipeline.

### Example: `CuratedUiProfile`

`CuratedUiProfile` demonstrates all four policy levers:

- hides `character` relations and noisy titles,
- reclassifies `spin_off` + `special/tv_special` from `related_series` to `specials`,
- applies profile-level sorting for `related_series` and `specials`,
- renames `related_series` to `Spin-offs & Related`.

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

These are the defaults from `SECTION_RULES` in `anime_franchise_ui_rules.py`.

### `series_line` (rendered as **Series**)

- Built from snapshot `series_line` only (TV-only continuity line).
- Not a rule-driven candidate group.
- Entries are rendered in snapshot order.

### `ignored` (internal, not rendered)

- `visible_in_ui`: `False`
- `priority`: `10` then `11` (two ignored rules)
- `include_media_types` (rule 1): `{"cm", "pv"}`
- `predicate` (rule 2): relation type is `other`
- `direct_from_series_line_only`: `False`
- `allow_indirect_candidates`: `True`
- `sort_mode`: `linked_then_date`
- `hidden_if_empty`: default `True`

### `continuity_extras` (**Main Story Extras**)

- `visible_in_ui`: `True`
- `priority`: `20`
- `include_relation_types`: `{"prequel", "sequel"}`
- `include_media_types`: `{"movie", "ova", "ona", "special", "tv_special"}`
- `exclude_media_types`: `{"tv", "cm", "pv"}`
- `direct_from_series_line_only`: `True`
- `allow_indirect_candidates`: `False`
- `sort_mode`: `continuity_extras`
- `hidden_if_empty`: `True`

### `specials`

- `visible_in_ui`: `True`
- `priority`: `30`
- `include_relation_types`: `{"side_story", "summary", "full_story"}`
- `include_media_types`: `{"ova", "movie", "special", "tv_special"}`
- `exclude_media_types`: `{"tv", "ona", "cm", "pv"}`
- `direct_from_series_line_only`: `True`
- `allow_indirect_candidates`: `False`
- `sort_mode`: `linked_then_date`
- `hidden_if_empty`: `True`

### `related_series`

- `visible_in_ui`: `True`
- `priority`: `40`
- `include_relation_types`: `{"spin_off", "parent_story", "alternative_setting", "alternative_version", "character"}`
- `include_media_types`: `{"tv", "movie", "ova", "ona", "special", "tv_special"}`
- `exclude_media_types`: `{"cm", "pv"}`
- `direct_from_series_line_only`: `True`
- `allow_indirect_candidates`: `False`
- `sort_mode`: `linked_then_date`
- `hidden_if_empty`: `True`

## View and template integration

In `media_details`:

- Franchise grouping is gated by MAL + anime + setting.
- `AnimeFranchiseService().build(media_id)` is called.
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
