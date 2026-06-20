from django.db import migrations


def clear_old_series_view_projection(apps, schema_editor):
    AnimeSeriesViewMembership = apps.get_model(
        "app",
        "AnimeSeriesViewMembership",
    )
    AnimeSeriesViewMembership.objects.filter(
        source_profile_key="series_view",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0065_animeseriesviewmembership_display_metadata"),
    ]

    operations = [
        migrations.RunPython(
            clear_old_series_view_projection,
            migrations.RunPython.noop,
        ),
    ]
