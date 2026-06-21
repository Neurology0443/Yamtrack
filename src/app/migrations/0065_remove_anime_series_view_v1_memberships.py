from django.db import migrations


def remove_v1_memberships(apps, schema_editor):
    membership = apps.get_model("app", "AnimeSeriesViewMembership")
    membership.objects.filter(projection_version="franchise_root_v1").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0064_animeseriesviewmembership"),
    ]

    operations = [
        migrations.RunPython(
            remove_v1_memberships,
            migrations.RunPython.noop,
        ),
    ]
