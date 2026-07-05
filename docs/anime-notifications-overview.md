# Anime notifications overview

## Notification families

Yamtrack has several notification flows that can involve anime. They share Apprise delivery URLs, but they answer different product questions and use different state models.

| Notification family | Trigger | Scope | Main user preference/global setting | Related doc |
| --- | --- | --- | --- | --- |
| Entry added | A media entry is created/imported | User library | `entry_added_notifications_enabled` and `notification_urls` | [Anime franchise import](anime-franchise-import.md) |
| Franchise discovery | A new visible franchise member is discovered after baseline | MAL franchise snapshot | `franchise_discovery_notifications_enabled` and `notification_urls` | [Franchise discovery notifications](anime-franchise-discovery-notifications.md) |
| MAL release-date | MAL `details.start_date` is announced, becomes more precise, or changes | MAL anime tracked as `Planning` or `In progress` | Global `ANIME_RELEASE_DATE_NOTIFICATIONS_ENABLED` plus user `anime_release_date_notifications_enabled` and `notification_urls` | [Anime release-date notifications](anime-release-date-notifications.md) |
| Native release/event | Existing Yamtrack event/release flow finds current releases or daily digest items | General media events | `release_notifications_enabled`, `daily_digest_enabled`, media-type settings, exclusions, and `notification_urls` | Existing notification and calendar docs |

## User preferences and global switches

User delivery always needs at least one usable Apprise URL in `notification_urls`.

The MAL release-date scanner has an extra global switch: `ANIME_RELEASE_DATE_NOTIFICATIONS_ENABLED`. That switch controls whether the Beat scanner is scheduled. It does not opt users into delivery.

Franchise discovery has no separate global env switch. It is controlled by where discovery processing runs, the user's `franchise_discovery_notifications_enabled` preference, and the persisted baseline/deduplication state.

## Trigger matrix

| Action | Entry added | Franchise discovery | MAL release-date | Native event/release |
| --- | --- | --- | --- | --- |
| Manual media add | Can queue entry-added notification | No; manual franchise post-processing uses `process_discovery=False` | Can initialize release-date state silently from detail metadata | Calendar/event flow remains separate |
| Franchise import | Can queue for created entries | Processes discoveries; imported IDs are suppressed for discovery | Initializes imported MAL anime state silently | Calendar/event flow remains separate |
| Autonomous franchise maintenance | No | Can detect and queue post-baseline discoveries | No direct release-date scan | Calendar/event flow remains separate |
| `Scan MAL anime release dates` | No | No | Scans due MAL anime states and delivers eligible transitions | No |
| `Send release notifications` / daily digest | No | No | No | Sends native event/release notifications |

## Which notification should I expect?

- If a row was automatically added to a user's library, expect the entry-added flow when that preference is enabled.
- If a missing franchise member appeared after the user's franchise baseline and was not imported or already tracked, expect the franchise discovery flow.
- If MAL changed `details.start_date` for an active tracked anime after silent initialization, expect the MAL release-date flow when both global scan and user delivery are enabled.
- If an existing Yamtrack `Event` is due, expect the native release or digest flow.

## Related docs

- [Anime franchise discovery notifications](anime-franchise-discovery-notifications.md)
- [Anime release-date notifications](anime-release-date-notifications.md)
- [Anime franchise import](anime-franchise-import.md)
- [Operational commands](operational-commands.md)
