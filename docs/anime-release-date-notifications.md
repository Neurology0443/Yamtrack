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

## Dedicated scan eligibility

An item is considered for the dedicated scan only when all of these conditions
are true:

- the item source is MAL;
- the item media type is anime;
- at least one user tracks it as `Planning` or `In progress`;
- that user enabled anime release-date notifications;
- that user has at least one non-empty Apprise notification URL;
- that user did not exclude the item from notifications;
- the global scan state is enabled and its `next_scan_at` is due;
- the minimum refresh cooldown has elapsed.

`Completed`, `Paused`, and `Dropped` tracking entries do not make an anime
eligible. Multiple eligible users tracking the same anime still produce only
one global cache lookup or MAL refresh.

The known start date then controls how long the item remains scannable:

- no valid date: keep scanning with progressive backoff;
- a current or future `YYYY` date: keep scanning because MAL may add a month or
  day, or change the year;
- a current or future `YYYY-MM` date: keep scanning because MAL may add a day or
  change the month;
- a complete date today or in the future: keep scanning because MAL may still
  move the date;
- a complete date before today: disable the scan state;
- a partial year older than the current year: disable the scan state;
- a partial month older than the current month: disable the scan state;
- MAL status `Finished`: disable the scan state.

Known partial or complete future dates use the long backoff and normally return
after seven days plus jitter. Therefore, having a precise future date does not
cause frequent MAL requests, but still allows a later postponement to be
detected.

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
