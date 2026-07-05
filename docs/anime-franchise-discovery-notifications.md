# Anime franchise discovery notifications

## Product behavior

Franchise discovery notifications tell a user when a new visible MAL anime entry appears in an important part of a franchise they already track.

The notification is informational only. It says that the entry was detected from MAL franchise data and was not automatically added to the user's tracking.

## What counts as a discovery

Discovery candidates are projected from the same franchise snapshot used by the detail-page franchise UI. The projection keeps visible, notification-worthy entries from:

- the fixed `Series` block;
- visible dynamic sections such as `Spin Offs`, `Alternatives`, and `Specials` when the section is eligible;
- supported anime formats.

The discovery path skips invalid media IDs, excluded anime formats such as commercials and promotional videos, and non-notifiable sections such as broad `Related Series` placements.

## Baseline and deduplication

Discovery is baseline-based to avoid notifying the whole history of a franchise that is already known.

- `AnimeFranchiseDiscoveryState` stores the per-user, per-root baseline and last observed fingerprint.
- The first observation creates the baseline and suppresses notification for existing visible candidates.
- A later visible candidate after the baseline can become notification-eligible.
- `AnimeFranchiseDiscoveredEntry` persists one discovered media ID per user and component root, including title, section, relation metadata, queue/send timestamps, and any suppression reason.

This means no notification on the first scan is expected behavior, not a delivery failure.

## Trigger paths

Discovery processing is invoked by:

- franchise import, after the import run builds the snapshot and creates any selected entries;
- autonomous franchise maintenance, when a due tracked seed is processed.

Manual post-add franchise processing intentionally calls maintenance with `process_discovery=False`. It refreshes the detail-page cache and Anime Series View quickly, but does not create discovery notifications.

## Delivery and user preferences

Delivery requires all of these conditions:

- the user has `franchise_discovery_notifications_enabled=True`;
- `notification_urls` contains at least one usable Apprise URL;
- the discovered MAL anime is not already tracked by that user;
- the discovery is not permanently suppressed as `baseline`, `imported_in_same_run`, or `already_tracked`;
- the discovery is inside the retry/reactivation windows.

Eligible discoveries queue `Send franchise discovery notification`, implemented by `send_franchise_discovery_notification_task`. The task sends through the same Apprise delivery helper used by other Yamtrack notifications. A successful delivery writes `notified_at` on `AnimeFranchiseDiscoveredEntry`.

If notifications are disabled when a discovery is seen, the row is still persisted with a temporary delivery block. Re-enabling the preference does not send immediately; a later normal franchise scan can requeue the still-visible discovery while it is still inside the reactivation window.

## Import interaction

Franchise import can both create missing library entries and process discovery in the same run. Entries imported in that run are passed as `imported_media_ids`, so they are suppressed with `imported_in_same_run` and do not generate a redundant discovery notification for themselves.

Imported entries may still queue the separate entry-added notification when that user preference is enabled.

## Maintenance interaction

Autonomous maintenance can detect post-baseline franchise changes even when users do not visit detail pages. It processes the current snapshot, updates discovery state, persists newly visible candidates, and queues eligible notifications.

Maintenance discovery errors are recorded as critical errors for the processed seed. Cache update is attempted before discovery, but the maintenance result is marked as failed or partial-failed when discovery processing raises, then retried according to the maintenance error cadence.

## What this is not

This is not:

- the generic entry-added notification;
- the MAL release-date notification scanner;
- the native event/release notification flow.

## Troubleshooting

Use Django shell checks rather than direct SQL so model names stay authoritative.

Check the user preference and delivery URLs:

```bash
docker compose exec -T yamtrack python manage.py shell <<'PY'
from django.contrib.auth import get_user_model
user = get_user_model().objects.get(id=1)
print({
    "franchise_discovery_notifications_enabled": user.franchise_discovery_notifications_enabled,
    "has_notification_urls": bool(user.notification_urls.strip()),
})
PY
```

Check whether a baseline exists for a user/root:

```bash
docker compose exec -T yamtrack python manage.py shell <<'PY'
from app.models import AnimeFranchiseDiscoveryState
for state in AnimeFranchiseDiscoveryState.objects.filter(user_id=1).order_by("component_root_mal_id")[:20]:
    print(state.component_root_mal_id, state.baseline_completed_at, state.last_seen_count, state.last_error[:160])
PY
```

Inspect discovered entries and suppression/delivery state:

```bash
docker compose exec -T yamtrack python manage.py shell <<'PY'
from app.models import AnimeFranchiseDiscoveredEntry
for entry in AnimeFranchiseDiscoveredEntry.objects.filter(user_id=1).order_by("-last_seen_at")[:20]:
    print(entry.discovered_media_id, entry.title, entry.section_label, entry.notification_suppressed_reason or "-", entry.notification_queued_at, entry.notified_at)
PY
```

Inspect logs for queue and delivery failures:

```bash
docker compose logs --since=90m yamtrack | grep -Ei "franchise discovery|Send franchise discovery notification|notification" || true
```

## Related docs

- [Anime notifications overview](anime-notifications-overview.md)
- [Anime franchise import](anime-franchise-import.md)
- [Anime franchise maintenance](anime-franchise-maintenance.md)
- [Anime release-date notifications](anime-release-date-notifications.md)
- [Operational commands](operational-commands.md)
