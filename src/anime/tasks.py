from celery import shared_task

from anime.use_cases import RefreshAnimeMetadata


@shared_task
def refresh_anime_metadata(media_id: int) -> None:
    """Delegate background refresh to its application use case."""
    RefreshAnimeMetadata().execute(media_id)
