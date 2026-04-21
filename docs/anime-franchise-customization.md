# Anime Franchise Customization Guide

Use this guide to change behavior without breaking the architecture.

## Where to change what

### UI grouping rule packs (main path)

- Directory: `src/app/services/anime_franchise_ui/rules/`
- Use for:
  - `base_facts.py`: normalized candidate facts shared by other packs,
  - `base_placement.py`: section declaration and initial fallback placement,
  - `relation_rules.py`: relation-signal placement refinements,
  - `anchor_rules.py`: anchor/directness refinements,
  - `format_rules.py`: format/runtime/episode refinements,
  - `section_rules.py`: section metadata policy (title/order/visibility only).

### Import heuristics and profile behavior

- File: `src/app/services/anime_franchise_import_profiles.py`

### Scan scheduling/backoff

- File: `src/app/services/anime_import_state.py`

### Task/scheduler automation

- Files:
  - `src/app/tasks.py`
  - `src/app/schedules.py`
  - `src/config/settings.py`

### Notification behavior

- Files:
  - `src/events/notifications.py`
  - `src/events/tasks.py`
  - `src/users/models.py`
  - `src/users/forms.py`
  - `src/templates/users/notifications.html`

### Rendering and footer badges

- Files:
  - `src/app/views.py`
  - `src/app/anime_franchise_footer.py`
  - `src/templates/app/media_details.html`

## Do / Don’t

### Do

- Keep franchise business logic in rule packs/services.
- Keep `AnimeFranchiseSnapshot` as canonical input for both UI and import.
- Keep `Series` fixed from `snapshot.series_line`.
- Keep override discipline explicit (`base_placement` initial, middle packs refine, `section_rules` metadata-only).
- Update tests and docs together when changing rule behavior.

### Don’t

- Don’t add classification logic to templates or JavaScript.
- Don’t move business rules into `layout.py`.
- Don’t duplicate snapshot logic in import or views.
- Don’t add pipeline badges/metadata not consumed by rendering.

## Safe change checklist

1. Update one concern at a time (facts, placement, relation, anchor, format, or metadata policy).
2. Validate UI payload contract tests after rule changes.
3. Run targeted tests from `docs/testing-runbook.md`.
4. Update docs for any changed behavior.
