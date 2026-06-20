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
        migrations.AlterField(
            model_name="user",
            name="book_layout",
            field=models.CharField(
                choices=[
                    ("grid", "Grid"),
                    ("table", "Table"),
                    ("series", "Series"),
                ],
                default="grid",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="boardgame_layout",
            field=models.CharField(
                choices=[
                    ("grid", "Grid"),
                    ("table", "Table"),
                    ("series", "Series"),
                ],
                default="grid",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="comic_layout",
            field=models.CharField(
                choices=[
                    ("grid", "Grid"),
                    ("table", "Table"),
                    ("series", "Series"),
                ],
                default="grid",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="game_layout",
            field=models.CharField(
                choices=[
                    ("grid", "Grid"),
                    ("table", "Table"),
                    ("series", "Series"),
                ],
                default="grid",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="manga_layout",
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
        migrations.AlterField(
            model_name="user",
            name="movie_layout",
            field=models.CharField(
                choices=[
                    ("grid", "Grid"),
                    ("table", "Table"),
                    ("series", "Series"),
                ],
                default="grid",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="season_layout",
            field=models.CharField(
                choices=[
                    ("grid", "Grid"),
                    ("table", "Table"),
                    ("series", "Series"),
                ],
                default="grid",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="tv_layout",
            field=models.CharField(
                choices=[
                    ("grid", "Grid"),
                    ("table", "Table"),
                    ("series", "Series"),
                ],
                default="grid",
                max_length=20,
            ),
        ),
    ]
