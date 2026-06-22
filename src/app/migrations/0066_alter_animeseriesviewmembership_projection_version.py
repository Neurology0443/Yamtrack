from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0065_animeseriesviewmembership_display_alternative_title_en"),
    ]

    operations = [
        migrations.AlterField(
            model_name="animeseriesviewmembership",
            name="projection_version",
            field=models.CharField(default="franchise_root_v3", max_length=30),
        ),
    ]
