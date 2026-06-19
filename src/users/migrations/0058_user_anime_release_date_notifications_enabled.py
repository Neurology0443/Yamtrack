from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0057_user_franchise_discovery_notifications_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="anime_release_date_notifications_enabled",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Receive notifications when a tracked MAL anime start date is "
                    "announced or changed"
                ),
            ),
        ),
    ]
