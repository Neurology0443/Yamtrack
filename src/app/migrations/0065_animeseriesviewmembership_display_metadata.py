from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0064_animeseriesviewmembership"),
    ]

    operations = [
        migrations.AddField(
            model_name="animeseriesviewmembership",
            name="context_parent_title",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="animeseriesviewmembership",
            name="display_image",
            field=models.URLField(blank=True, default="", max_length=1000),
        ),
        migrations.AddField(
            model_name="animeseriesviewmembership",
            name="display_media_type",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="animeseriesviewmembership",
            name="display_start_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="animeseriesviewmembership",
            name="display_title",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
    ]
