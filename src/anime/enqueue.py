import logging

from kombu.exceptions import OperationalError as BrokerOperationalError

from anime.metadata import validate_media_id

logger = logging.getLogger(__name__)


def enqueue_anime_metadata_refresh(media_id: int) -> None:
    """Publish a refresh without exposing Celery to the application use-case."""
    validate_media_id(media_id)
    from anime.tasks import refresh_anime_metadata  # noqa: PLC0415

    try:
        refresh_anime_metadata.apply_async(args=(media_id,), retry=False)
    except (BrokerOperationalError, OSError):
        logger.exception(
            "Could not enqueue MAL metadata refresh for anime %s",
            media_id,
        )
