"""Run MAL anime franchise maintenance scan manually."""

from django.core.management.base import BaseCommand

from app.services.anime_franchise_maintenance_scan import (
    AnimeFranchiseMaintenanceScanService,
)


class Command(BaseCommand):
    """Run the same maintenance scan service used by Celery."""

    help = "Scan due MAL anime franchise maintenance states."

    def add_arguments(self, parser):
        """Add optional scan limit argument."""
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *_args, **options):
        """Run the maintenance scan service and print counters."""
        stats = AnimeFranchiseMaintenanceScanService().scan_due(limit=options["limit"])
        self.stdout.write(self.style.SUCCESS(str(stats.to_dict())))
