# Environment Variables

This page outlines the environment variables used in the YamTrack project.

## Media Sources

| Name | Notes |
| ---- | ----- |
| `TMDB_API` | The Movie Database API key for movies and TV shows. A default key is provided. |
| `TMDB_NSFW` | Default to `False`. Set to `True` to include adult content in TV and movie searches. |
| `TMDB_LANG` | TMDB metadata language. Uses a language code in ISO 639-1 (e.g., `en`). Also supports a country code in ISO 3166-1 (e.g., `en-US`). Metadata is cached for a few hours in Redis. You may need to clear the cache to see the new language immediately. |
| `TVDB_API` | TVDB API key. A default key is provided. Used for TVDB-backed metadata where supported. |
| `MAL_API` | MyAnimeList API key for anime and manga. A default key is provided. |
| `MAL_NSFW` | Default to `False`. Set to `True` to include adult content in anime and manga searches from MyAnimeList. |
| `MU_NSFW` | Default to `False`. Set to `True` to include adult content in manga searches from MangaUpdates. |
| `IGDB_ID` | IGDB API key for games. A default key is provided, but it's recommended to get your own as it has a low rate limit. |
| `IGDB_SECRET` | IGDB API secret for games. A default value is provided, but it's recommended to get your own as it has a low rate limit. |
| `IGDB_NSFW` | Default to `False`. Set to `True` to include adult content in game searches. |
| `BGG_API_TOKEN` | BoardGameGeek API token. A default token is provided. |
| `STEAM_API_KEY` | Steam Web API key. Default is empty. Set it when Steam metadata/features require a key. |
| `HARDCOVER_API` | Hardcover API key for books. A default key is provided, but it's recommended to get your own as it has a low rate limit. Custom values must include the `Bearer ` prefix. |
| `COMICVINE_API` | ComicVine API key for comics. A default key is provided, but it's recommended to get your own as it has a low rate limit. |
| `TRAKT_API` | Trakt API client ID/key. A default key is provided. |
| `TRAKT_API_SECRET` | Trakt API client secret. Default is empty. Set it when Trakt OAuth/client-secret flows require it. |
| `ANILIST_ID` | AniList client ID. Default is empty. |
| `ANILIST_SECRET` | AniList client secret. Default is empty. |
| `SIMKL_ID` | Simkl client ID. A default value is provided. |
| `SIMKL_SECRET` | Simkl client secret. A default value is provided. |

## Media Import

See [media-imports](media-imports.md).

## Redis and Django Settings

| Name | Notes |
| ---- | ----- |
| `REDIS_URL` | Default to `redis://localhost:6379`. Set this to your Redis server URL, in the format of `redis://{service}:{port}`. In the Docker Compose examples this is `redis://redis:6379`. If Yamtrack shares a Docker network with another container or service named `redis`, use the Yamtrack Redis container name instead: `redis://yamtrack-redis:6379`. |
| `CELERY_REDIS_URL` | Default to the value of `REDIS_URL`. Set this to your Redis server URL for Celery if you need a different value than `REDIS_URL`. |
| `REDIS_PREFIX` | Optional prefix for Redis keys and channels to enable isolation when sharing a Redis instance across multiple applications. Useful for ACL-based permission control. |
| `SECRET` | [Secret key](https://docs.djangoproject.com/en/stable/ref/settings/#secret-key) used for cryptographic signing. Should be a random string. |
| `URLS` | Shortcut to set both the `CSRF` and `ALLOWED_HOSTS` settings. Comma-separated list of URLs (e.g., `https://yamtrack.mydomain.com`). |
| `ALLOWED_HOSTS` | Comma-separated list of host/domain names that this Django site can serve (e.g., `yamtrack.mydomain.com`). Default to `*` for all hosts. |
| `CSRF` | Comma-separated list of trusted origins for `POST` requests when using reverse proxies (e.g., `https://yamtrack.mydomain.com`). |
| `REGISTRATION` | Default to `True`. Set to `False` to disable user registration. |
| `DEBUG` | Default to `False`. Set to `True` for debugging. |
| `ADMIN_ENABLED` | Default to `False`. Set to `True` to enable the Django admin interface. |
| `TRACK_TIME` | Default to `True`. Set to `False` to disable time tracking in Yamtrack. |
| `VERSION` | Default to `dev`. Runtime version string usually set from the Docker build argument. |
| `SESSION_COOKIE_AGE` | Default to `1209600` seconds, which is 14 days. Controls Django session lifetime. |

## User and System Configuration

| Name | Notes |
| ---- | ----- |
| `PUID` | User ID for the app. Default to `1000`. |
| `PGID` | Group ID for the app. Default to `1000`. |
| `TZ` | Timezone (e.g., `Europe/Berlin`). Default to `UTC`. |
| `WEB_CONCURRENCY` | Number of web server processes. Default to `1`. |
| `YAMTRACK_IPV6_ENABLED` | Default to `False`. Set to `True` to use the nginx config that also listens on IPv6. |
| `ENV_DEBUG` | Default to `False`. Set to `True` to run Celery worker and beat with debug log level under supervisord. |
| `DAILY_DIGEST_HOUR` | Default to `8`. Hour of day, in the configured timezone, when the daily digest task is scheduled. |
| `USER_MESSAGE_RETENTION_DAYS` | Default to `30`. Number of days shown user messages are kept before cleanup. |
| `SOCIAL_PROVIDERS` | Comma-separated list of social authentication providers to enable (e.g., `allauth.socialaccount.providers.openid_connect,allauth.socialaccount.providers.github`). |
| `SOCIALACCOUNT_PROVIDERS` | JSON configuration for social providers. See the [Docs](social-auth.md) for an OIDC configuration example. |
| `ACCOUNT_DEFAULT_HTTP_PROTOCOL` | Protocol for social providers. If your `redirect_uri` in OIDC config is `https`, set this to `https`. Default is determined based on your `CSRF` settings. |
| `ACCOUNT_LOGOUT_REDIRECT_URL` | Absolute URL to redirect users after logout. Useful for OpenID Connect providers to ensure complete logout from the external authentication provider. |
| `SOCIALACCOUNT_ONLY` | Default to `False`. Set to `True` to disable local authentication when using social authentication only. |
| `REDIRECT_LOGIN_TO_SSO` | Default to `False`. Set to `True` to automatically redirect (using JavaScript) to the SSO provider when there's only one available. Useful for single sign-on setups. |
| `YAMTRACK_AUTO_LOGIN_USERNAME` | Default to `None`, which disables this feature. Specify a username to automatically login with the selected user. The user needs to be existing and active. |

## Celery Health Check

| Name | Notes |
| ---- | ----- |
| `HEALTHCHECK_CELERY_PING_TIMEOUT` | Default to `1`. Increases the timeout for the health check ping to Celery. This is useful for slow connections. |

## PostgreSQL Environment Variables (YamTrack Container)

| Name | Notes |
| ---- | ----- |
| `DB_HOST` | The hostname or IP address of the PostgreSQL server. If not set, SQLite is used as the default database. |
| `DB_PORT` | The port number on which the PostgreSQL server is listening. |
| `DB_NAME` | The name of the database to connect to. |
| `DB_USER` | The username used to authenticate with the PostgreSQL server. |
| `DB_PASSWORD` | The password for the specified user. |

**Note:** Check the example `docker-compose.postgres.yml` in the root directory of the repo for a PostgreSQL configuration example.

### External PostgreSQL database with SSL (YamTrack Container)

| Name | Notes |
| ---- | ----- |
| `DB_SSL_MODE` | Determines whether or with what priority a secure SSL TCP/IP connection will be negotiated with the server. See [the official documentation](https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLMODE). |
| `DB_SSL_CERT_MODE` | Determines whether a client certificate may be sent to the server, and whether the server is required to request one. See [the official documentation](https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLCERTMODE). |

## Docker Secrets Support

YamTrack supports reading sensitive configuration values from Docker secrets files. The following environment variables can alternatively be provided as secrets:

| Environment Variable | Secret File Equivalent |
| -------------------- | ---------------------- |
| `SECRET` | `SECRET_FILE` |
| `DB_NAME` | `DB_NAME_FILE` |
| `DB_USER` | `DB_USER_FILE` |
| `DB_PASSWORD` | `DB_PASSWORD_FILE` |
| `TMDB_API` | `TMDB_API_FILE` |
| `TVDB_API` | `TVDB_API_FILE` |
| `MAL_API` | `MAL_API_FILE` |
| `IGDB_ID` | `IGDB_ID_FILE` |
| `IGDB_SECRET` | `IGDB_SECRET_FILE` |
| `BGG_API_TOKEN` | `BGG_API_TOKEN_FILE` |
| `STEAM_API_KEY` | `STEAM_API_KEY_FILE` |
| `HARDCOVER_API` | `HARDCOVER_API_FILE` |
| `COMICVINE_API` | `COMICVINE_API_FILE` |
| `TRAKT_API` | `TRAKT_API_FILE` |
| `TRAKT_API_SECRET` | `TRAKT_API_SECRET_FILE` |
| `ANILIST_ID` | `ANILIST_ID_FILE` |
| `ANILIST_SECRET` | `ANILIST_SECRET_FILE` |
| `SIMKL_ID` | `SIMKL_ID_FILE` |
| `SIMKL_SECRET` | `SIMKL_SECRET_FILE` |
| `SOCIALACCOUNT_PROVIDERS` | `SOCIALACCOUNT_PROVIDERS_FILE` |

## Host under subpath

| Name | Notes |
| ---- | ----- |
| `BASE_URL` | To host YamTrack under a subpath like `https://example.com/yamtrack`, set this to `/yamtrack`, without trailing slash. |

## Self-signed certificates

| Name | Notes |
| ---- | ----- |
| `REQUESTS_CA_BUNDLE` | Path to a custom CA certificate bundle file for SSL verification. Useful for self-hosted authentication providers with self-signed certificates (e.g., `/etc/ssl/certs/ca-certificates.crt`). This requires the CA certificate to be present in the host's CA bundle. |

## MAL anime metadata cache

These settings control individual MAL anime detail metadata cache entries, not the assembled franchise payload cache.

| Variable | Default | Description |
| --- | --- | --- |
| `MAL_RATE_LIMIT_PER_MINUTE` | `100` | Per-minute MyAnimeList API rate limit used by the provider request path. Lower this if MAL returns HTTP 429 responses. |
| `MAL_CACHE_FRESH_DAYS` | `7` | Number of days a cached MAL anime detail payload is considered fresh. |
| `MAL_CACHE_KEEP_DAYS` | `365` | Sliding TTL, in days, for keeping MAL anime detail payloads and sidecar metadata in Redis. |
| `MAL_CACHE_RETRY_AFTER_ERROR_HOURS` | `12` | Cooldown before retrying a MAL anime metadata refresh after a refresh error. |
| `MAL_CACHE_REFRESH_MIN_INTERVAL_HOURS` | `24` | Minimum interval before scheduling another background stale-refresh attempt for the same MAL anime metadata payload. |

## MAL anime release-date notifications

This scanner watches MAL anime start-date metadata and is separate from the normal `send_release_notifications` task.

| Variable | Default | Description |
| --- | --- | --- |
| `ANIME_RELEASE_DATE_NOTIFICATIONS_ENABLED` | `true` | Enables the Celery Beat scanner for MAL anime start-date notifications. |
| `ANIME_RELEASE_DATE_SCAN_INTERVAL_HOURS` | `12` | Interval, in hours, for the MAL anime release-date scan schedule. |
| `ANIME_RELEASE_DATE_SCAN_BATCH_SIZE` | `25` | Maximum number of due MAL anime release-date scan states processed per scan run. |
| `ANIME_RELEASE_DATE_SCAN_MIN_REFRESH_HOURS` | `24` | Minimum age, in hours, before refreshing MAL metadata for release-date scanning. |
| `ANIME_RELEASE_DATE_SCAN_ERROR_RETRY_HOURS` | `12` | Retry delay, in hours, after a release-date scan error. |
| `ANIME_RELEASE_DATE_SCAN_MAX_BACKOFF_DAYS` | `7` | Maximum backoff, in days, for release-date scan states. |
| `ANIME_RELEASE_DATE_SCAN_LOCK_MINUTES` | `360` | Celery scan lock duration, in minutes, to avoid concurrent release-date scans. |

## MAL anime franchise payload cache

These settings control the complete assembled MAL anime franchise payload cache. They do not replace or alter the existing individual MAL anime metadata cache settings.

| Variable | Default | Description |
| --- | --- | --- |
| `ANIME_FRANCHISE_GROUPING_ENABLED` | `true` | Enables the MAL anime franchise grouping/detail-page feature. |
| `ANIME_FRANCHISE_CACHE_TTL_DAYS` | `365` | Redis/cache TTL for complete franchise payloads and sidecar metadata. |
| `ANIME_FRANCHISE_CACHE_ALIASES_ENABLED` | `true` | Enables lightweight canonical cache aliases for complete MAL anime franchise payloads. Aliases point related MAL anime IDs to one canonical payload and do not duplicate the cached payload. |
| `ANIME_FRANCHISE_CACHE_FRESH_DAYS` | `30` | Logical freshness window before a stale payload may be refreshed in the background. |
| `ANIME_FRANCHISE_BUILD_COOLDOWN_HOURS` | `24` | Minimum time between successful build enqueue attempts for the same franchise. |
| `ANIME_FRANCHISE_RETRY_AFTER_ERROR_HOURS` | `12` | Cooldown before retrying after a build error. |
| `ANIME_FRANCHISE_QUEUE_LOCK_MINUTES` | `30` | Queue lock duration to avoid duplicate Celery enqueues. |
| `ANIME_FRANCHISE_TASK_LOCK_MINUTES` | `60` | Worker task lock duration to avoid concurrent builds. |
| `ANIME_FRANCHISE_MAX_NODES` | `50` | Maximum graph nodes to hydrate before saving a truncated partial payload; values `<= 0` are treated as unlimited. |
| `ANIME_FRANCHISE_PAYLOAD_SCHEMA_VERSION` | `1` | Schema version used to invalidate incompatible cached franchise payloads. |

## MAL anime franchise import automation

These settings create/update the `auto_import_anime_franchise` Celery Beat entry only when enabled.

| Variable | Default | Description |
| --- | --- | --- |
| `ANIME_FRANCHISE_IMPORT_AUTOMATION_ENABLED` | `false` | Enables the optional Celery Beat task that runs automatic MAL anime franchise import. |
| `ANIME_FRANCHISE_IMPORT_AUTOMATION_INTERVAL_MINUTES` | `1440` | Interval, in minutes, for the automatic import task. |
| `ANIME_FRANCHISE_IMPORT_AUTOMATION_PROFILE` | `continuity` | Import profile used by automation. Valid profiles are currently `continuity`, `satellites`, and `complete`. |
| `ANIME_FRANCHISE_IMPORT_AUTOMATION_REFRESH_CACHE` | `false` | Whether automated import should refresh MAL/provider cache data while building snapshots. |
| `ANIME_FRANCHISE_IMPORT_AUTOMATION_FULL_RESCAN` | `false` | Whether automated import should ignore due-state scheduling and rescan all eligible seeds. |
| `ANIME_FRANCHISE_IMPORT_AUTOMATION_LIMIT` | `None` | Optional maximum number of due seeds to process per automated import run. Empty value disables the limit. |

## MAL anime franchise maintenance

These settings create/update the `scan_mal_anime_franchise_maintenance` Celery Beat entry only when enabled.

| Variable | Default | Description |
| --- | --- | --- |
| `ANIME_FRANCHISE_MAINTENANCE_SCAN_ENABLED` | `false` | Enables the autonomous MAL anime franchise maintenance Celery Beat scanner. |
| `ANIME_FRANCHISE_MAINTENANCE_SCAN_INTERVAL_MINUTES` | `60` | Interval, in minutes, for the maintenance scanner schedule. |
| `ANIME_FRANCHISE_MAINTENANCE_SCAN_BATCH_SIZE` | `10` | Maximum number of due maintenance states selected per scan run. |
| `ANIME_FRANCHISE_MAINTENANCE_TARGET_SWEEP_HOURS` | `24` | Target sweep window, in hours, used by maintenance cadence calculations. |
| `ANIME_FRANCHISE_MAINTENANCE_INITIAL_SPREAD_HOURS` | `24` | Spread window, in hours, used when creating initial maintenance states. |
| `ANIME_FRANCHISE_MAINTENANCE_REFRESH_CACHE` | `true` | Whether maintenance should request fresh MAL/provider cache data while processing seeds. |
| `ANIME_FRANCHISE_MAINTENANCE_LOCK_MINUTES` | `360` | Celery lock duration, in minutes, to avoid concurrent maintenance scans. |
| `ANIME_FRANCHISE_MAINTENANCE_ERROR_RETRY_HOURS` | `12` | Retry delay, in hours, after a maintenance error. |
| `ANIME_FRANCHISE_MAINTENANCE_REFRESH_SERIES_VIEW_ON_CHANGE` | `true` | Refreshes Anime Series View memberships when maintenance detects a changed maintenance fingerprint or root. |
| `ANIME_FRANCHISE_MAINTENANCE_REFRESH_SERIES_VIEW_ON_SUCCESS` | `false` | Refreshes Anime Series View memberships on every successful maintenance run. More aggressive than change-only refresh. |
| `ANIME_FRANCHISE_MAINTENANCE_USE_STABLE_BACKOFF` | `false` | Enables additional stable-franchise backoff behavior for repeatedly unchanged franchises. |
| `ANIME_FRANCHISE_MAINTENANCE_MAX_STABLE_BACKOFF_DAYS` | `30` | Maximum stable-franchise backoff, in days. |
| `ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MIN_AGE_YEARS` | `15` | Minimum franchise age, in years, before a stable franchise can be considered deep-cold. |
| `ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MIN_STABLE_SCANS` | `8` | Minimum consecutive stable scans before deep-cold cadence can apply. |
| `ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MIN_CHANGE_AGE_DAYS` | `180` | Minimum age, in days, since the last detected change before deep-cold cadence can apply. |
| `ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MIN_DAYS` | `21` | Minimum deep-cold scan interval, in days. |
| `ANIME_FRANCHISE_MAINTENANCE_DEEP_COLD_MAX_DAYS` | `30` | Maximum deep-cold scan interval, in days. |
