from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0064_animeseriesviewmembership"),
    ]

    operations = [
        migrations.AddField(
            model_name="animeseriesviewmembership",
            name="display_alternative_title_en",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
        migrations.AlterField(
            model_name="animeseriesviewmembership",
            name="projection_version",
            field=models.CharField(default="franchise_root_v3", max_length=30),
        ),
    ]
