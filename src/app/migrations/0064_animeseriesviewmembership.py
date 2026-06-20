import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0063_anime_franchise_discovery"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
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
                ("group_kind", models.CharField(max_length=40)),
                (
                    "context_parent_media_id",
                    models.CharField(
                        blank=True,
                        max_length=36,
                        null=True,
                    ),
                ),
                (
                    "context_relation_type",
                    models.CharField(
                        blank=True,
                        max_length=40,
                        null=True,
                    ),
                ),
                ("component_size", models.PositiveIntegerField(default=1)),
                ("projection_version", models.CharField(max_length=20)),
                ("source_profile_key", models.CharField(max_length=40)),
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
        ),
        migrations.AddConstraint(
            model_name="animeseriesviewmembership",
            constraint=models.UniqueConstraint(
                fields=(
                    "user",
                    "media_id",
                    "source_profile_key",
                    "projection_version",
                ),
                name="app_aniseriesview_membership_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="animeseriesviewmembership",
            index=models.Index(
                fields=["user", "source_profile_key", "media_id"],
                name="app_asv_media_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="animeseriesviewmembership",
            index=models.Index(
                fields=["user", "source_profile_key", "root_media_id"],
                name="app_asv_root_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="animeseriesviewmembership",
            index=models.Index(
                fields=["user", "source_profile_key", "group_kind"],
                name="app_asv_kind_idx",
            ),
        ),
    ]
