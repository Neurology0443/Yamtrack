# Anime Franchise Grouping (MAL-only, Anime-only)

## Goal

This feature adds a **service-first** franchise grouping engine for MAL anime detail pages. It classifies related entries into:

- `Series`
- `Main Story Extras`
- `Specials`
- `Related Series`

The design is intentionally modular and prepared for future UI improvements (for example, numbered seasons from the `Series` line).

## Scope

- MAL provider only (`source == mal`)
- Anime detail pages only (`media_type == anime`)
- No cross-provider behavior
- No title matching
- No business classification logic in templates/JS

Feature flag:

- `ANIME_FRANCHISE_GROUPING_ENABLED`

## Architecture

Implementation is split into focused modules:

- `src/app/services/anime_franchise_types.py`
  - dataclasses and section rule schema
- `src/app/services/anime_franchise_graph.py`
  - MAL graph discovery + normalized relation extraction
- `src/app/services/anime_franchise_rules.py`
  - V1 section rules and priority ordering
- `src/app/services/anime_franchise.py`
  - orchestration pipeline and UI view model generation

## Business pipeline

1. Discover the useful MAL graph from the seed anime.
2. Build sequel/prequel continuity component.
3. Derive a TV-only `series_line`.
4. Build non-series candidates from direct neighbors.
5. Classify candidates with first-match-wins priority rules.
6. Return one generic UI view model.

## Relation normalization

`relation_type` values are normalized with the MAL provider helper:

- `app.providers.mal.normalize_relation_type(...)`

This avoids divergence in normalization logic and keeps relation matching consistent.

## V1 sections and rules

### `Series` (`series_line`)

- TV entries only (`anime_media_type == tv`)
- built from sequel/prequel continuity
- stable deterministic ordering:
  - continuity direction when possible
  - fallback `start_date ASC`, then `MAL id ASC`

### `ignored`

- internal only (not visible in UI)
- absorbs:
  - `anime_media_type in {cm, pv}`
  - or `relation_type == other`

### `Main Story Extras` (`continuity_extras`)

- include relation: `{prequel, sequel}`
- include formats: `{movie, ova, ona, special, tv_special}`
- exclude formats: `{tv, cm, pv}`
- `direct_from_series_line_only = True`
- sorting:
  - `linked_series_line_index ASC`
  - `prequel` before `sequel`
  - `start_date ASC`
  - `MAL id ASC`

### `Specials`

- include relation: `{side_story, summary, full_story}`
- include formats: `{ova, movie, special, tv_special}`
- exclude formats: `{tv, ona, cm, pv}`
- `direct_from_series_line_only = True`

### `Related Series`

- include relation: `{spin_off, parent_story, alternative_setting, alternative_version, character}`
- include formats: `{tv, movie, ova, ona, special, tv_special}`
- exclude formats: `{cm, pv}`
- `direct_from_series_line_only = True` in V1

## Fallback behavior when `series_line` is empty

When no TV node exists:

- `Series` stays empty in UI.
- The current seed is used as an **internal fallback anchor**.
- Seed direct neighbors are treated as direct candidates for rule evaluation.
- No fake `Series` item is created.
- The seed is not injected into `Series`.

This keeps the UI consistent while preserving useful satellite sections.

## UI payload model

Every franchise entry (series and section entries) includes:

- `media_id`
- `source`
- `media_type` (always `anime` for Yamtrack integration)
- `anime_media_type` (real MAL format, e.g. `tv`, `movie`, `ova`, ...)
- `relation_type` (when relevant)
- `is_current`
- `linked_series_line_media_id`
- `linked_series_line_index`

This payload is intentionally ready for future badges and richer UI diagnostics.

## View/template responsibilities

### View

`media_details`:

- activates franchise grouping only under MAL+Anime+flag
- calls `AnimeFranchiseService().build(media_id)`
- enriches entries via existing `helpers.enrich_items_with_user_data`
- injects a single context object: `anime_franchise`
- removes `related_anime` from legacy related sections to avoid duplicated rendering

### Template

- renders `Series`
- loops generically over visible franchise sections
- does not perform classification logic

## Extensibility

Adding a new section should mostly be:

1. add one `AnimeFranchiseSectionRule`
2. set priority and title
3. define matching/sorting strategy

No special-case branch should be required in view/template.

## Known V1 constraints

- `Related Series` is direct-only by product decision.
- Badges are not displayed yet, but payload/rules are already prepared.
