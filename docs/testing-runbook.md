# Testing Runbook (fork features)

This runbook is the complete host/local test matrix for fork-specific MAL anime franchise, notification, cache, and Anime Series View work. The Docker runbook contains the equivalent `docker compose exec` commands for the same families.

## Test modules to run

### Franchise grouping and snapshot

- `app.tests.services.test_anime_franchise`
- `app.tests.services.test_anime_franchise_graph`
- `app.tests.services.test_anime_franchise_snapshot`
- `app.tests.services.test_anime_franchise_ui_pipeline`
- `app.tests.services.test_anime_franchise_context`
- `app.tests.test_anime_franchise_footer`
- `app.tests.views.test_media_details`

### Franchise import and automation

- `app.tests.services.test_anime_franchise_import_profiles`
- `app.tests.services.test_anime_franchise_import_build_session`
- `app.tests.services.test_anime_import_state`
- `app.tests.test_anime_franchise_import`
- `app.tests.test_import_anime_franchise_command`
- `app.tests.test_schedules`
- `app.tests.test_tasks`

### Franchise cache and provider metadata

- `app.tests.services.test_anime_franchise_cache`
- `app.tests.services.test_anime_franchise_cache_builder`
- `app.tests.services.test_anime_franchise_scoped_payload`
- `app.tests.test_anime_franchise_cache_warmer`
- `app.tests.test_item_image_sync`

### Franchise maintenance and discovery notifications

- `app.tests.services.test_anime_franchise_maintenance_cadence`
- `app.tests.services.test_anime_franchise_maintenance_scan`
- `app.tests.test_anime_franchise_discovery`
- `app.tests.test_manual_anime_franchise_task`
- `events.tests.test_notification`
- `events.tests.test_tasks`

### Anime Series View

- `app.tests.services.test_anime_series_view`
- `app.tests.services.test_anime_series_view_projection`
- `app.tests.services.test_anime_series_view_franchise_refresh`
- `app.tests.services.test_anime_series_view_refresh_queue`
- `app.tests.services.test_anime_series_view_refresh_triggers`
- `app.tests.test_anime_series_view_import_integration`
- `app.tests.test_anime_series_view_task`
- `app.tests.test_rebuild_anime_series_view_command`
- `app.tests.views.test_anime_series_view`

### MAL release-date notifications

- `events.tests.test_anime_release_date_notifications`
- `events.tests.test_notification`
- `events.tests.test_tasks`

## Host commands

From repo root, use `uv` so the command works without changing directories:

```bash
uv run --directory . python src/manage.py test \
  app.tests.services.test_anime_franchise \
  app.tests.services.test_anime_franchise_graph \
  app.tests.services.test_anime_franchise_snapshot \
  app.tests.services.test_anime_franchise_ui_pipeline \
  app.tests.services.test_anime_franchise_context \
  app.tests.test_anime_franchise_footer \
  app.tests.views.test_media_details
```

```bash
uv run --directory . python src/manage.py test \
  app.tests.services.test_anime_franchise_import_profiles \
  app.tests.services.test_anime_franchise_import_build_session \
  app.tests.services.test_anime_import_state \
  app.tests.test_anime_franchise_import \
  app.tests.test_import_anime_franchise_command \
  app.tests.test_schedules \
  app.tests.test_tasks
```

```bash
uv run --directory . python src/manage.py test \
  app.tests.services.test_anime_franchise_cache \
  app.tests.services.test_anime_franchise_cache_builder \
  app.tests.services.test_anime_franchise_scoped_payload \
  app.tests.test_anime_franchise_cache_warmer \
  app.tests.test_item_image_sync
```

```bash
uv run --directory . python src/manage.py test \
  app.tests.services.test_anime_franchise_maintenance_cadence \
  app.tests.services.test_anime_franchise_maintenance_scan \
  app.tests.test_anime_franchise_discovery \
  app.tests.test_manual_anime_franchise_task \
  events.tests.test_notification \
  events.tests.test_tasks
```

```bash
uv run --directory . python src/manage.py test \
  app.tests.services.test_anime_series_view \
  app.tests.services.test_anime_series_view_projection \
  app.tests.services.test_anime_series_view_franchise_refresh \
  app.tests.services.test_anime_series_view_refresh_queue \
  app.tests.services.test_anime_series_view_refresh_triggers \
  app.tests.test_anime_series_view_import_integration \
  app.tests.test_anime_series_view_task \
  app.tests.test_rebuild_anime_series_view_command \
  app.tests.views.test_anime_series_view
```

```bash
uv run --directory . python src/manage.py test \
  events.tests.test_anime_release_date_notifications \
  events.tests.test_notification \
  events.tests.test_tasks
```

## When to run which tests

- Changed grouping graph/snapshot/assembler/rules/UI profile/UI pipeline: run franchise grouping and snapshot tests plus `app.tests.views.test_media_details`.
- Changed import profiles/state/task/schedule/command: run franchise import and automation tests.
- Changed cache payloads, provider MAL cache refresh/invalidation, or image sync: run franchise cache and provider metadata tests.
- Changed maintenance cadence, scan state, or discovery notifications: run maintenance and discovery tests.
- Changed Anime Series View projection/refresh/list rendering: run Anime Series View tests.
- Changed MAL release-date notifications: run `events.tests.test_anime_release_date_notifications`, `events.tests.test_notification`, and `events.tests.test_tasks`.
