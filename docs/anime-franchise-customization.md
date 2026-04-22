# Anime Franchise Customization Guide

Use this guide to change behavior safely while staying aligned with the current architecture.

## Architecture reminder before editing

- Main UI grouping path: `AnimeFranchiseService -> AnimeFranchiseUiPipeline`.
- `Series` is fixed from `snapshot.series_line`.
- Secondary sections are rule-driven.
- `layout.py` is structural-only.
- `adapter.py` is compatibility-only.
- `views.py` + `anime_franchise_footer.py` are integration/presentation enrichment.

## Where to change what

### 1) UI grouping rule packs (main path)

Directory: `src/app/services/anime_franchise_ui/rules/`

Use for:

- `base_facts.py`
  - add/update normalized candidate facts used by later packs,
  - tune relation/provenance-derived helper signals.
- `base_placement.py`
  - declare section definitions,
  - set initial fallback placement for unclassified candidates.
- `relation_rules.py`
  - relation-based section assignment/refinement.
- `anchor_rules.py`
  - directness/fallback-anchor gating behavior.
- `format_rules.py`
  - conservative format/runtime gating and exclusions.
- `section_rules.py`
  - metadata policy only (titles/order/hidden); no candidate moves.

Also relevant:

- `src/app/services/anime_franchise_ui/presets/default.py` for pack order.
- `src/app/services/anime_franchise_ui/engine.py` for override trace behavior.

### 2) Import heuristics and profile behavior

File: `src/app/services/anime_franchise_import_profiles.py`

Use for:

- tuning `continuity` / `satellites` / `complete` profile semantics,
- changing profile eligibility/selection logic,
- adjusting how snapshot facts map to import decisions.

### 3) Scan scheduling/backoff

File: `src/app/services/anime_import_state.py`

Use for:

- retry/backoff windows,
- error-state progression,
- incremental rescan cadence and state transitions.

### 4) Task/scheduler automation

Files:

- `src/app/tasks.py`
- `src/app/schedules.py`
- `src/config/settings.py`

Use for:

- Celery task trigger cadence,
- automation on/off and periodic schedule wiring,
- operational defaults for franchise import jobs.

### 5) Notification behavior

Files:

- `src/events/notifications.py`
- `src/events/tasks.py`
- `src/users/models.py`
- `src/users/forms.py`
- `src/templates/users/notifications.html`

Use for:

- opt-in settings,
- async dispatch behavior,
- payload formatting and endpoint delivery policy.

### 6) Rendering and footer badges

Files:

- `src/app/views.py`
- `src/app/anime_franchise_footer.py`
- `src/templates/app/media_details.html`

Use for:

- integration shape between service payload and page context,
- `series_label` and footer relation/format badge presentation,
- template-level display structure.

Do not use this area to implement new grouping placement policy.

## Practical guardrails (Do / Don’t)

### Do

- Keep grouping business logic in rule packs.
- Keep snapshot semantics canonical for both UI and import projections.
- Keep `Series` exclusively sourced from `snapshot.series_line`.
- Keep override behavior explicit and debuggable (`placement_trace`).
- Update tests + docs in the same change when behavior shifts.

### Don’t

- Don’t move placement rules into `layout.py`, adapter, or templates.
- Don’t document legacy UI logic as active runtime path.
- Don’t mix import projection decisions into UI placement documentation.
- Don’t overstate provenance fields (`metadata["origins"]`) as fully mature policy drivers unless code truly does that.

## Safe change checklist

1. Identify the concern: facts, placement, relation, anchor, format, metadata, or integration display.
2. Patch the minimal layer that owns that concern.
3. Run targeted tests from `docs/testing-runbook.md` and franchise debug checks.
4. Validate no regressions in fallback no-series behavior.
5. Update architecture/grouping/debug docs to match actual runtime behavior.
