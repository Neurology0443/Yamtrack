from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0058_user_anime_release_date_notifications_enabled"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="anime_layout",
            field=models.CharField(
                choices=[
                    ("grid", "Grid"),
                    ("table", "Table"),
                    ("series", "Series"),
                ],
                default="table",
                max_length=20,
            ),
        ),
    ]
