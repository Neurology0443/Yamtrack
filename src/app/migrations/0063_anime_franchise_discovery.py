from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("app", "0062_merge_animeimportscanstate_episode_item_not_null"),
    ]

    operations = [
        migrations.CreateModel(
            name="AnimeFranchiseDiscoveryState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("component_root_mal_id", models.CharField(max_length=36)),
                ("baseline_completed_at", models.DateTimeField(blank=True, null=True)),
                ("first_scanned_at", models.DateTimeField(blank=True, null=True)),
                ("last_scanned_at", models.DateTimeField(blank=True, null=True)),
                ("last_fingerprint", models.CharField(blank=True, default="", max_length=128)),
                ("last_seen_count", models.PositiveIntegerField(default=0)),
                ("last_error", models.TextField(blank=True, default="")),
                ("last_error_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="AnimeFranchiseDiscoveredEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("component_root_mal_id", models.CharField(max_length=36)),
                ("discovered_media_id", models.CharField(max_length=36)),
                ("title", models.TextField(blank=True, default="")),
                ("section_key", models.CharField(blank=True, default="", max_length=50)),
                ("section_label", models.CharField(blank=True, default="", max_length=100)),
                ("relation_type", models.CharField(blank=True, default="", max_length=50)),
                ("source_media_id", models.CharField(blank=True, default="", max_length=36)),
                ("anime_media_type", models.CharField(blank=True, default="", max_length=50)),
                ("root_title", models.TextField(blank=True, default="")),
                ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                ("notification_queued_at", models.DateTimeField(blank=True, null=True)),
                ("notified_at", models.DateTimeField(blank=True, null=True)),
                ("notification_suppressed_reason", models.CharField(blank=True, default="", max_length=50)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="animefranchisediscoverystate",
            constraint=models.UniqueConstraint(fields=("user", "component_root_mal_id"), name="app_anime_franchise_discovery_state_unique"),
        ),
        migrations.AddIndex(
            model_name="animefranchisediscoverystate",
            index=models.Index(fields=["user", "component_root_mal_id"], name="app_af_disc_state_idx"),
        ),
        migrations.AddConstraint(
            model_name="animefranchisediscoveredentry",
            constraint=models.UniqueConstraint(fields=("user", "component_root_mal_id", "discovered_media_id"), name="app_anime_franchise_discovery_unique"),
        ),
        migrations.AddIndex(
            model_name="animefranchisediscoveredentry",
            index=models.Index(fields=["user", "component_root_mal_id"], name="app_af_disc_root_idx"),
        ),
        migrations.AddIndex(
            model_name="animefranchisediscoveredentry",
            index=models.Index(fields=["user", "discovered_media_id"], name="app_af_disc_media_idx"),
        ),
    ]
