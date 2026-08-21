# Anime architecture

Yamtrack remains the main application. The Anime subsystem adds Anime-specific
behavior while keeping general tracking, users, and the rest of the application
under Yamtrack's existing responsibilities.

## Anime's place in Yamtrack

Anime is a focused extension inside the host application. It owns only data and
behavior that need Anime-specific rules. It does not move general Yamtrack
responsibilities into a new system or replace existing tracking features.

The code for this extension lives in the dedicated `src/anime/` Django
application. This keeps its special rules together while still using Yamtrack's
application, configuration, and database.

## Where metadata comes from

MyAnimeList (MAL) is the external source for the Anime metadata currently handled
by this subsystem. Anime keeps the last valid copy in Yamtrack's database. Once
information has been fetched, reading it does not require another network call
every time.

This provider metadata does not replace the user's tracking state. Yamtrack still
owns that state and the general application integration.

The `MalAnimeMetadataStore` is the single boundary used by Anime to read, refresh,
normalize, and save MAL metadata. It turns the provider response into data with a
stable shape before the rest of the Anime code uses it.

## Local-first reads

`GetAnimeMetadata` looks for a valid local copy first. If one is not available,
Anime can fetch the required metadata from MAL. Recent provider failures may
temporarily delay another fetch attempt. If a valid copy exists, Anime can return
it immediately.

When that copy is due for a refresh, Anime continues to return it and may request
a refresh in the background. A failed refresh records the failure but does not
erase the last valid copy. If neither local data nor a successful provider result
is available, Anime reports that the metadata is unavailable.

```text
MAL
 ↓
metadata store
 ↓
durable local record
 ↓
read-only metadata snapshot
 ↓
Anime application logic
```

In the code, these parts are named `MalAnimeMetadataStore`,
`AnimeMetadataRecord`, and `AnimeMetadataSnapshot`.

## Durable records and temporary snapshots

`AnimeMetadataRecord` is the durable representation stored in the application
database. The database record exists so the information survives application
restarts.

`AnimeMetadataSnapshot` is the clean, read-only form used while Anime is working
with that information. It is temporary and cannot be changed after it is created.

## Database support

Anime supports both SQLite and PostgreSQL. It uses Django's object-relational
mapper (ORM), which lets the code read and write application records without
depending directly on one database engine. PostgreSQL is therefore not required
by the Anime subsystem.

## Background refreshes

A refresh can be sent to Celery so it runs as background work. The Celery task is
deliberately small. It passes the request to the `RefreshAnimeMetadata` use case,
which performs the refresh through the metadata store.

The task queue coordinates work. Important metadata and refresh state remain in
the application database; the queue and Redis are not the durable source of that
information.
