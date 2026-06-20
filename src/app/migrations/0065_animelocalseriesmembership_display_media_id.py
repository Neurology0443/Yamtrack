from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0064_animelocalseriesmembership"),
    ]

    operations = [
        migrations.AddField(
            model_name="animelocalseriesmembership",
            name="display_media_id",
            field=models.CharField(blank=True, default="", max_length=36),
        ),
    ]
