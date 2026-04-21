# Architecture Overview

This fork keeps MAL anime franchise logic service-first and shared between UI and import.

## Scope

- Grouping applies only to MAL anime (`source=mal`, `media_type=anime`).
- The canonical domain object is a franchise `snapshot`.
- UI and import are projections on top of the same snapshot.

## Layer responsibilities

### 1) Provider and graph discovery

- `src/app/providers/mal.py`: fetches MAL metadata and normalizes relation types.
- `src/app/services/anime_franchise_graph.py`: builds normalized nodes/relations and continuity graph from MAL data.

### 2) Canonical franchise snapshot

- `src/app/services/anime_franchise_snapshot.py` computes:
  - continuity component (transitive prequel/sequel graph),
  - `series_line` (TV-only ordering),
  - direct anchors and direct candidates,
  - canonical component root (`canonical_root_media_id`),
  - fallback anchor behavior when no TV line exists.

### 3) Projections

- UI projection:
  - `src/app/services/anime_franchise_ui/series.py`
  - `src/app/services/anime_franchise_ui/assembler.py`
  - `src/app/services/anime_franchise_ui/presets/default.py`
  - `src/app/services/anime_franchise_ui/engine.py`
  - `src/app/services/anime_franchise_ui/layout.py`
  - `src/app/services/anime_franchise_ui/adapter.py`
  - `src/app/services/anime_franchise.py` (facade)
- Import projection:
  - `src/app/services/anime_franchise_import_profiles.py`
  - `src/app/services/anime_franchise_import.py`
  - `src/app/services/anime_import_state.py`

### 4) Delivery and app integration

- UI delivery:
  - `src/app/views.py` + `src/templates/app/media_details.html`
  - `src/app/anime_franchise_footer.py` for footer labels/badges.
- Import automation:
  - `src/app/tasks.py` Celery task + cache lock,
  - `src/app/management/commands/import_anime_franchise.py` CLI,
  - `src/app/schedules.py` + `src/config/settings.py` automation settings.
- Notifications/messages:
  - `src/events/notifications.py` and `src/events/tasks.py` for async entry-added notifications,
  - `src/users/models.py`, `src/users/forms.py`, `src/templates/users/notifications.html` for user settings,
  - `src/app/models.py` (`UserMessage`) and cleanup task.

## ASCII flow maps

### UI flow

```text
app/providers/mal.py
   -> app/services/anime_franchise_graph.py
   -> app/services/anime_franchise_snapshot.py
   -> app/services/anime_franchise_ui (pipeline)
   -> app/services/anime_franchise.py
   -> app/views.py (media_details)
   -> templates/app/media_details.html
```

### Import flow

```text
app/providers/mal.py
   -> app/services/anime_franchise_graph.py
   -> app/services/anime_franchise_snapshot.py
   -> app/services/anime_franchise_import_profiles.py
   -> app/services/anime_franchise_import.py
   -> app/services/anime_import_state.py
   -> app/tasks.py / management command / schedules+settings
```

### Notification flow (entry added)

```text
Entry creation (manual save or franchise import)
   -> events.notifications.notify_entry_added_after_commit(...)
   -> events.tasks.send_entry_added_notification_task
   -> events.notifications.send_entry_added_notification
   -> user Apprise endpoints
```

## Why this architecture fits Yamtrack

- Single canonical source (`snapshot`) avoids duplicate business logic.
- UI templates stay display-only (no classification logic in templates/JS).
- UI and import reuse the same franchise graph/snapshot.
- Incremental scan state reduces unnecessary rescans with stable/error backoff.
- Scope is explicit and constrained to MAL anime grouping.
