"""Centralized provider image synchronization for Item.image."""

from __future__ import annotations

from collections.abc import Iterable  # noqa: TC003
from dataclasses import dataclass

from django.conf import settings
from django.db.models import Q

from app.models import Item, Sources


@dataclass(frozen=True)
class ProviderImageEntry:
    """Known provider image candidate for a global Item row."""

    source: str
    media_type: str
    media_id: str
    image: str


def _normalize_text(value) -> str:
    """Normalize provider identifiers and images to stripped strings."""
    if value is None:
        return ""
    return str(value).strip()


def _is_usable_image(image: str | None) -> bool:
    """Return whether a provider image is safe to write into Item.image."""
    normalized_image = _normalize_text(image)
    return bool(normalized_image) and normalized_image != settings.IMG_NONE


def should_sync_provider_image(item: Item | None, new_image: str | None) -> bool:
    """Return True when a provider image may replace ``item.image``."""
    if item is None or not _is_usable_image(new_image):
        return False

    if not item.image or item.image == settings.IMG_NONE:
        return True

    if item.source == Sources.MAL.value:
        return item.image != _normalize_text(new_image)

    return False


def sync_existing_item_image(
    item: Item | None,
    new_image: str | None,
    *,
    save: bool = True,
) -> bool:
    """Sync a known provider image into an already-loaded Item object."""
    if not should_sync_provider_image(item, new_image):
        return False

    item.image = _normalize_text(new_image)
    if save:
        item.save(update_fields=["image"])
    return True


def sync_provider_image(
    *,
    source: str,
    media_type: str,
    media_id: str,
    image: str | None,
) -> int:
    """Sync one provider image into the matching global Item row."""
    normalized_media_id = _normalize_text(media_id)
    normalized_image = _normalize_text(image)
    if not normalized_media_id or not _is_usable_image(normalized_image):
        return 0

    item = (
        Item.objects.filter(
            source=source,
            media_type=media_type,
            media_id=normalized_media_id,
            season_number__isnull=True,
            episode_number__isnull=True,
        )
        .only("id", "source", "image")
        .first()
    )
    return int(sync_existing_item_image(item, normalized_image, save=True))


def sync_provider_images(entries: Iterable[ProviderImageEntry]) -> int:
    """Bulk sync provider images into matching global no-season/no-episode Item rows."""
    desired_images = {}
    for entry in entries:
        media_id = _normalize_text(entry.media_id)
        image = _normalize_text(entry.image)
        if not media_id or not _is_usable_image(image):
            continue
        desired_images[(entry.source, entry.media_type, media_id)] = image

    if not desired_images:
        return 0

    query = None

    for source, media_type, media_id in desired_images:
        q = Q(source=source, media_type=media_type, media_id=media_id)
        query = q if query is None else query | q

    items = list(
        Item.objects.filter(
            query,
            season_number__isnull=True,
            episode_number__isnull=True,
        ).only("id", "source", "media_type", "media_id", "image")
    )
    items_to_update = []
    for item in items:
        new_image = desired_images.get(
            (item.source, item.media_type, str(item.media_id))
        )
        if sync_existing_item_image(item, new_image, save=False):
            items_to_update.append(item)

    if not items_to_update:
        return 0

    Item.objects.bulk_update(items_to_update, ["image"])
    return len(items_to_update)
