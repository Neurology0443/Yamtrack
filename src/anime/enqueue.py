def enqueue_anime_metadata_refresh(media_id: int) -> None:
    """Publish a refresh without exposing Celery to the application use-case."""
    from anime.tasks import refresh_anime_metadata  # noqa: PLC0415

    refresh_anime_metadata.delay(media_id)
