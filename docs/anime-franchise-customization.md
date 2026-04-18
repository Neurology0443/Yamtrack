# Anime Franchise Customization Guide

Use this guide to change behavior without breaking the architecture.

## Where to change what

### Section rules (UI grouping)

- File: `src/app/services/anime_franchise_ui_rules.py`
- Use for:
  - section keys/titles,
  - match filters (`relation_type`, media type, predicate),
  - ordering priority,
  - sort mode and visibility.

### UI builder orchestration

- File: `src/app/services/anime_franchise_ui_builder.py`
- Use for:
  - candidate construction from snapshot/direct candidates,
  - first-match rule classification,
  - section assembly into `AnimeFranchiseViewModel`.

### UI profile hooks

- File: `src/app/services/anime_franchise_ui_profiles.py`
- Use for:
  - declarative masking (`hidden_relation_types`, `hidden_media_types`, `hidden_titles`),
  - section reclassification (`target_section_key`),
  - per-section sort policy (`sort_section_candidates`),
  - section title policy (`section_title`).
- `hidden_titles` comparisons are normalized (`strip + case-insensitive`).
- Default behavior is provided by `DefaultUiProfile` and is intentionally a no-op.
- Profiles are policy-level (niveau 2): they customize UI behavior without rebuilding the whole view model.
- Example reference: `CuratedUiProfile` combines hide/reclassify/sort/rename behavior.
- Compatibility shims exist for older names:
  - `src/app/services/anime_franchise_rules.py`
  - `src/app/services/anime_franchise_ui_profile.py`

### Import heuristics and profile behavior

- File: `src/app/services/anime_franchise_import_profiles.py`
- Use for:
  - continuity/satellite/complete selection,
  - runtime/episode heuristics,
  - eligible relation types,
  - seed mode constraints.

### Import orchestration

- File: `src/app/services/anime_franchise_import_service.py`
- Use for:
  - due seed retrieval, profile execution, entry creation, and scan-state recording.
- `src/app/services/anime_franchise_import.py` is retained as a compatibility re-export.

### Scan scheduling/backoff

- File: `src/app/services/anime_import_state.py`
- Use for:
  - due selection policy,
  - fingerprint semantics,
  - stable/error backoff,
  - `mark_due_now` profile list.

### Task/scheduler automation

- Files:
  - `src/app/tasks.py`
  - `src/app/schedules.py`
  - `src/config/settings.py`
- Use for:
  - task lock policy,
  - beat schedule wiring,
  - environment setting defaults.

### Notification behavior

- Files:
  - `src/events/notifications.py`
  - `src/events/tasks.py`
  - `src/users/models.py`
  - `src/users/forms.py`
  - `src/templates/users/notifications.html`
- Use for:
  - notification trigger payload,
  - post-commit async dispatch,
  - user opt-in setting (`entry_added_notifications_enabled`),
  - Apprise URL validation and settings UI copy.

### Rendering and footer badges

- Files:
  - `src/app/views.py`
  - `src/app/anime_franchise_footer.py`
  - `src/templates/app/media_details.html`
- Use for:
  - series labels (`Season N`),
  - footer relation/format labels,
  - section rendering layout.

## Do / Don’t

### Do

- Do keep franchise business logic in services.
- Do keep `AnimeFranchiseSnapshot` as canonical input for both UI and import.
- Do keep first-match-wins rule order explicit and tested.
- Do update tests and runbook when profile/rule behavior changes.
- Do keep MAL scope explicit for grouping behavior.

### Don’t

- Don’t add classification logic to templates or JavaScript.
- Don’t duplicate graph/snapshot logic in import or views.
- Don’t bypass `notify_entry_added_after_commit` for entry-added events.
- Don’t silently change seed eligibility/backoff rules without updating docs/tests.
- Don’t reintroduce legacy `related_anime` display alongside grouped sections.

## Safe change checklist

1. Update one layer only (rules, import profile, or scheduler) per change.
2. Validate impact on both UI and import flows.
3. Run targeted tests from `docs/testing-runbook.md`.
4. Update docs for any changed behavior.
