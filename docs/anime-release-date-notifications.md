# MAL anime release-date notifications

## Purpose

Yamtrack can notify a user when the start date of an actively tracked
MyAnimeList anime is announced, becomes more precise, or changes.

The feature is opt-in per user. It is disabled by default and applies only to
MAL anime in `Planning` or `In progress` with at least one notification URL.
Items excluded from notifications are ignored.

## Source of truth

The only release-date source is:

```python
metadata["details"]["start_date"]
```

This value comes from the MAL anime provider. The feature does not use AniList
`airingSchedule`, calendar `Event` rows, or `Event.notification_sent`. Episode
and actual-release notifications remain separate features.

Supported values are parsed strictly:

- `YYYY`
- `YYYY-MM`
- `YYYY-MM-DD`

Empty, malformed, or impossible dates do not generate notifications. Partial
dates are stored as first-class states so transitions such as `2027` to
`2027-05` and `2027-05` to `2027-05-27` can be detected.

## Observation paths

There are three ways to observe the MAL value:

1. An existing MAL metadata refresh passes its old and new payloads to the
   service. No extra provider request is made.
2. Franchise import passes the payload already returned by `anime_minimal()`.
   The state is initialized silently and no extra provider request is made.
3. A dedicated Celery scan processes a bounded deterministic batch of due
   states. It uses the MAL cache when its `fetched_at` value is recent enough
   and refreshes MAL only as a last resort.

The dedicated scan is a safety net for anime whose detail page is never opened.

## Persistence and deduplication

`AnimeReleaseDateScanState` stores one global state per MAL anime `Item`. One
provider refresh therefore serves every user tracking the same anime.

`AnimeReleaseDateNotificationDelivery` stores one row per user and date
transition. Its uniqueness constraint includes both the previous and new text
values, allowing a later reverse transition while preventing the same
transition from being sent twice.

The first observed state is always initialized silently. This prevents existing
known dates from producing a notification storm when the feature is deployed.

## Scan controls

The scan uses:

- a global cache lock;
- deterministic ordering by `next_scan_at` and row ID;
- a configurable batch size;
- a minimum refresh cooldown;
- recent MAL cache data before any provider request;
- stable-state backoff up to the configured maximum;
- jitter only when calculating the next scan time;
- automatic disabling for definitively past dates and MAL `Finished` status.

The default schedule runs every 12 hours with a batch of 25 and a minimum
24-hour refresh interval. This caps the theoretical provider refresh volume at
50 anime per day, while recent cache entries reduce it further.

## Settings

- `ANIME_RELEASE_DATE_NOTIFICATIONS_ENABLED`
- `ANIME_RELEASE_DATE_SCAN_INTERVAL_HOURS`
- `ANIME_RELEASE_DATE_SCAN_BATCH_SIZE`
- `ANIME_RELEASE_DATE_SCAN_MIN_REFRESH_HOURS`
- `ANIME_RELEASE_DATE_SCAN_ERROR_RETRY_HOURS`
- `ANIME_RELEASE_DATE_SCAN_MAX_BACKOFF_DAYS`
- `ANIME_RELEASE_DATE_SCAN_LOCK_MINUTES`
