"""Rebuild persisted Anime Series View memberships."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from app.models import Anime, MediaTypes, Sources
from app.services.anime_series_view_franchise_refresh import (
    AnimeSeriesViewFranchiseRefreshService,
)
from app.services.anime_series_view_refresh_queue import normalize_media_ids


class Command(BaseCommand):
    """Rebuild Series View memberships for selected users."""

    help = "Rebuild the persisted Anime Series View franchise projection."

    def add_arguments(self, parser):
        """Register command-line options."""
        parser.add_argument("--user-id", action="append", type=int, dest="user_ids")
        parser.add_argument("--all-users", action="store_true")
        parser.add_argument("--media-id", action="append", dest="media_ids")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--refresh-cache", action="store_true")
        parser.add_argument("--limit", type=int)

    def handle(self, *args, **options):  # noqa: ARG002
        """Execute the rebuild synchronously and report per-user statistics."""
        user_ids = options["user_ids"] or []
        if not user_ids and not options["all_users"]:
            message = "Provide --user-id or --all-users."
            raise CommandError(message)
        if user_ids and options["all_users"]:
            message = "--all-users cannot be combined with --user-id."
            raise CommandError(message)
        if options["limit"] is not None and options["limit"] < 1:
            message = "--limit must be greater than or equal to 1."
            raise CommandError(message)

        users = get_user_model().objects.all()
        if user_ids:
            users = users.filter(id__in=user_ids)

        service = AnimeSeriesViewFranchiseRefreshService()
        explicit_media_ids = normalize_media_ids(options["media_ids"])
        for user in users.order_by("id"):
            media_ids = explicit_media_ids
            if not media_ids:
                query = Anime.objects.filter(
                    user=user,
                    item__source=Sources.MAL.value,
                    item__media_type=MediaTypes.ANIME.value,
                ).values_list("item__media_id", flat=True)
                if options["limit"] is not None:
                    query = query[: options["limit"]]
                media_ids = normalize_media_ids(query)
            elif options["limit"] is not None:
                media_ids = media_ids[: options["limit"]]

            stats = service.refresh_for_media_ids(
                user=user,
                media_ids=media_ids,
                refresh_cache=options["refresh_cache"],
                dry_run=options["dry_run"],
            )
            self.stdout.write(
                " | ".join(
                    [
                        f"user_id={user.id}",
                        f"requested={stats.requested}",
                        f"snapshots_built={stats.snapshots_built}",
                        f"snapshots_skipped={stats.snapshots_skipped}",
                        (f"franchise_created={stats.franchise_memberships_created}"),
                        (f"franchise_updated={stats.franchise_memberships_updated}"),
                        f"singleton_created={stats.singleton_memberships_created}",
                        f"singleton_updated={stats.singleton_memberships_updated}",
                        f"deleted={stats.memberships_deleted}",
                        f"errors={stats.errors}",
                        f"dry_run={options['dry_run']}",
                    ]
                )
            )
