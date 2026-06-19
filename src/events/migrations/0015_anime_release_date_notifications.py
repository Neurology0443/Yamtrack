import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0063_anime_franchise_discovery"),
        ("events", "0014_delete_empty_content_number_comic_events"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AnimeReleaseDateScanState",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "last_seen_start_date_text",
                    models.CharField(blank=True, default="", max_length=16),
                ),
                (
                    "last_seen_start_date_precision",
                    models.CharField(blank=True, default="", max_length=16),
                ),
                (
                    "last_seen_start_date",
                    models.DateField(
                        blank=True,
                        help_text=(
                            "Only populated when MAL start_date precision is "
                            "YYYY-MM-DD."
                        ),
                        null=True,
                    ),
                ),
                (
                    "last_seen_raw_start_date",
                    models.CharField(blank=True, default="", max_length=32),
                ),
                (
                    "last_seen_mal_status",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                ("initialized_at", models.DateTimeField(blank=True, null=True)),
                ("last_checked_at", models.DateTimeField(blank=True, null=True)),
                ("last_success_at", models.DateTimeField(blank=True, null=True)),
                ("last_change_at", models.DateTimeField(blank=True, null=True)),
                ("next_scan_at", models.DateTimeField()),
                (
                    "consecutive_stable_scans",
                    models.PositiveIntegerField(default=0),
                ),
                (
                    "consecutive_error_count",
                    models.PositiveIntegerField(default=0),
                ),
                ("disabled", models.BooleanField(default=False)),
                (
                    "item",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="anime_release_date_scan_state",
                        to="app.item",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="AnimeReleaseDateNotificationDelivery",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("start_date_text", models.CharField(max_length=16)),
                ("start_date_precision", models.CharField(max_length=16)),
                (
                    "previous_start_date_text",
                    models.CharField(blank=True, default="", max_length=16),
                ),
                (
                    "previous_start_date_precision",
                    models.CharField(blank=True, default="", max_length=16),
                ),
                (
                    "start_date",
                    models.DateField(
                        blank=True,
                        help_text=(
                            "Only populated when start_date_precision is day."
                        ),
                        null=True,
                    ),
                ),
                (
                    "previous_start_date",
                    models.DateField(
                        blank=True,
                        help_text=(
                            "Only populated when previous_start_date_precision is day."
                        ),
                        null=True,
                    ),
                ),
                (
                    "change_kind",
                    models.CharField(
                        choices=[
                            ("announced", "Announced"),
                            ("updated", "Updated"),
                        ],
                        max_length=16,
                    ),
                ),
                ("detected_at", models.DateTimeField()),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("failed_at", models.DateTimeField(blank=True, null=True)),
                ("error", models.TextField(blank=True, default="")),
                (
                    "item",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="app.item",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="animereleasedatescanstate",
            index=models.Index(
                fields=["disabled", "next_scan_at"],
                name="events_ard_due_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="animereleasedatenotificationdelivery",
            constraint=models.UniqueConstraint(
                fields=(
                    "user",
                    "item",
                    "previous_start_date_text",
                    "start_date_text",
                ),
                name="events_ard_user_item_transition_uniq",
            ),
        ),
    ]
