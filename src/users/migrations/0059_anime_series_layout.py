from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0058_user_anime_release_date_notifications_enabled"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="user",
            name="anime_layout_valid",
        ),
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
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(anime_layout__in=["grid", "table", "series"]),
                name="anime_layout_valid",
            ),
        ),
    ]
