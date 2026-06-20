"""Rebuild persisted Anime Series View projections."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from app.models import Anime, MediaTypes, Sources
from app.services.anime_series_view_projection_refresh import (
    AnimeSeriesViewProjectionRefreshService,
)


class Command(BaseCommand):
    """Rebuild projections for selected users and MAL anime IDs."""

    help = "Rebuild the persisted Anime Series View from canonical snapshots."

    def add_arguments(self, parser):
        """Configure rebuild scope and execution flags."""
        parser.add_argument("--user-id", action="append", type=int, dest="user_ids")
        parser.add_argument("--all-users", action="store_true")
        parser.add_argument("--media-id", action="append", dest="media_ids")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--refresh-cache", action="store_true")
        parser.add_argument("--limit", type=int)

    def handle(self, *_args, **options):
        """Refresh selected users and print aggregate projection counters."""
        if options["limit"] is not None and options["limit"] < 1:
            message = "--limit must be greater than or equal to 1."
            raise CommandError(message)
        if options["all_users"] and options["user_ids"]:
            message = "--all-users cannot be combined with --user-id."
            raise CommandError(message)
        if not options["all_users"] and not options["user_ids"]:
            message = "Use --user-id or --all-users."
            raise CommandError(message)

        users = get_user_model().objects.all().order_by("id")
        if options["user_ids"]:
            users = users.filter(id__in=options["user_ids"])

        requested_ids = {
            str(media_id).strip()
            for media_id in options["media_ids"] or []
            if str(media_id).strip()
        }
        service = AnimeSeriesViewProjectionRefreshService()
        totals = {
            "users": 0,
            "snapshots": 0,
            "recorded": 0,
            "created": 0,
            "updated": 0,
            "deleted": 0,
            "errors": 0,
        }
        for user in users:
            media_ids = requested_ids or set(
                Anime.objects.filter(
                    user=user,
                    item__source=Sources.MAL.value,
                    item__media_type=MediaTypes.ANIME.value,
                ).values_list("item__media_id", flat=True)
            )
            if options["limit"] is not None:
                media_ids = set(
                    sorted(media_ids, key=_media_id_key)[: options["limit"]]
                )
            if not media_ids:
                continue
            stats = service.refresh_for_media_ids(
                user=user,
                media_ids=media_ids,
                dry_run=options["dry_run"],
                refresh_cache=options["refresh_cache"],
            )
            totals["users"] += 1
            totals["snapshots"] += stats.snapshots_refreshed
            totals["recorded"] += stats.memberships_recorded
            totals["created"] += stats.memberships_created
            totals["updated"] += stats.memberships_updated
            totals["deleted"] += stats.memberships_deleted
            totals["errors"] += stats.errors

        self.stdout.write(
            self.style.SUCCESS(
                " | ".join(
                    [
                        f"users={totals['users']}",
                        f"snapshots={totals['snapshots']}",
                        f"memberships_recorded={totals['recorded']}",
                        f"created={totals['created']}",
                        f"updated={totals['updated']}",
                        f"deleted={totals['deleted']}",
                        f"errors={totals['errors']}",
                        f"dry_run={options['dry_run']}",
                    ]
                )
            )
        )


def _media_id_key(media_id):
    media_id = str(media_id)
    return (0, int(media_id)) if media_id.isdigit() else (1, media_id)
