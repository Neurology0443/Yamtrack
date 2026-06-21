from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0059_alter_user_layout_choices"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="user",
            name="anime_layout_valid",
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(anime_layout__in=["grid", "table", "series"]),
                name="anime_layout_valid",
            ),
        ),
    ]
