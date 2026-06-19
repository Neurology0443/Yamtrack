"""Import missing MAL anime entries for a franchise profile."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from app.services.anime_franchise_import import AnimeFranchiseImportService


class Command(BaseCommand):
    """Import missing MAL anime entries for one franchise profile."""

    help = "Import MAL anime franchise entries with profile-based selection."

    def add_arguments(self, parser):
        """Register command-line arguments."""
        parser.add_argument(
            "--profile",
            required=True,
            choices=["continuity", "satellites", "complete"],
        )
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--full-rescan", action="store_true")
        parser.add_argument("--limit", type=int)
        parser.add_argument("--refresh-cache", action="store_true")
        parser.add_argument("--user-id", action="append", type=int, dest="user_ids")

    def handle(self, *_args, **options):
        """Run the selected import profile."""
        if options["limit"] is not None and options["limit"] < 1:
            message = "--limit must be greater than or equal to 1."
            raise CommandError(message)

        try:
            stats = AnimeFranchiseImportService().run(
                profile_key=options["profile"],
                dry_run=options["dry_run"],
                full_rescan=options["full_rescan"],
                limit=options["limit"],
                refresh_cache=options["refresh_cache"],
                user_ids=options["user_ids"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                " | ".join(
                    [
                        f"profile={options['profile']}",
                        f"scanned={stats.scanned}",
                        f"created={stats.created}",
                        f"planned_creations={stats.planned_creations}",
                        f"already_exists={stats.already_exists}",
                        (
                            "local_series_memberships_recorded="
                            f"{stats.local_series_memberships_recorded}"
                        ),
                        (
                            "local_series_groups_resolved="
                            f"{stats.local_series_groups_resolved}"
                        ),
                        f"errors={stats.errors}",
                    ]
                )
            )
        )
