from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("app", "0063_anime_franchise_discovery"),
    ]

    operations = [
        migrations.CreateModel(
            name="AnimeSeriesViewMembership",
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
                ("media_id", models.CharField(max_length=36)),
                ("root_media_id", models.CharField(max_length=36)),
                ("display_media_id", models.CharField(max_length=36)),
                (
                    "display_title",
                    models.CharField(blank=True, default="", max_length=500),
                ),
                (
                    "display_image",
                    models.URLField(blank=True, default="", max_length=1000),
                ),
                (
                    "display_media_type",
                    models.CharField(blank=True, default="", max_length=40),
                ),
                ("display_start_date", models.DateField(blank=True, null=True)),
                (
                    "group_kind",
                    models.CharField(
                        choices=[
                            ("franchise", "Franchise"),
                            ("singleton", "Singleton"),
                        ],
                        default="franchise",
                        max_length=40,
                    ),
                ),
                (
                    "projection_version",
                    models.CharField(default="franchise_root_v2", max_length=30),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["user", "media_id"],
                        name="app_asv_user_media_idx",
                    ),
                    models.Index(
                        fields=["user", "root_media_id"],
                        name="app_asv_user_root_idx",
                    ),
                    models.Index(
                        fields=["user", "projection_version"],
                        name="app_asv_user_version_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "media_id"),
                        name="app_asv_membership_user_media_uniq",
                    )
                ],
            },
        )
    ]
