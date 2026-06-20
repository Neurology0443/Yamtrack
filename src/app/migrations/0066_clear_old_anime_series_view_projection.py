from django.db import migrations


def clear_old_series_view_projection(apps, schema_editor):
    """Clear regenerated Anime Series View read-model rows.

    AnimeSeriesViewMembership is a derived projection, not primary user
    tracking data. Rows for the Series View profile can be rebuilt from Anime
    entries and MAL franchise snapshots.
    """
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
