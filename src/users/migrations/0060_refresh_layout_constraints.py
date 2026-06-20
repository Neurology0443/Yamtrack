from django.db import migrations, models


LAYOUT_VALUES = ["grid", "table", "series"]


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0059_alter_user_layout_choices"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="user",
            name="tv_layout_valid",
        ),
        migrations.RemoveConstraint(
            model_name="user",
            name="season_layout_valid",
        ),
        migrations.RemoveConstraint(
            model_name="user",
            name="movie_layout_valid",
        ),
        migrations.RemoveConstraint(
            model_name="user",
            name="anime_layout_valid",
        ),
        migrations.RemoveConstraint(
            model_name="user",
            name="manga_layout_valid",
        ),
        migrations.RemoveConstraint(
            model_name="user",
            name="game_layout_valid",
        ),
        migrations.RemoveConstraint(
            model_name="user",
            name="book_layout_valid",
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(tv_layout__in=LAYOUT_VALUES),
                name="tv_layout_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(season_layout__in=LAYOUT_VALUES),
                name="season_layout_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(movie_layout__in=LAYOUT_VALUES),
                name="movie_layout_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(anime_layout__in=LAYOUT_VALUES),
                name="anime_layout_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(manga_layout__in=LAYOUT_VALUES),
                name="manga_layout_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(game_layout__in=LAYOUT_VALUES),
                name="game_layout_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(book_layout__in=LAYOUT_VALUES),
                name="book_layout_valid",
            ),
        ),
    ]
