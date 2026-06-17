from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0056_merge_entry_notifications_upstream_user_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="franchise_discovery_notifications_enabled",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Receive notifications when a new MAL anime appears in an important "
                    "section of a franchise you already track."
                ),
            ),
        ),
    ]
