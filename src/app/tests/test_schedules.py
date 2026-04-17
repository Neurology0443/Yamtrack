from django.test import SimpleTestCase

from app.schedules import build_anime_franchise_import_schedule


class AnimeFranchiseImportScheduleTests(SimpleTestCase):
    def test_returns_empty_dict_when_disabled(self):
        schedule = build_anime_franchise_import_schedule(
            enabled=False,
            interval_minutes=60,
            profile="satellites",
        )

        self.assertEqual(schedule, {})

    def test_returns_expected_entry_when_enabled(self):
        schedule = build_anime_franchise_import_schedule(
            enabled=True,
            interval_minutes=30,
            profile="satellites",
            refresh_cache=True,
            full_rescan=True,
            limit=5,
        )

        self.assertEqual(
            schedule,
            {
                "auto_import_anime_franchise": {
                    "task": "Import anime franchise",
                    "schedule": 60 * 30,
                    "kwargs": {
                        "profile_key": "satellites",
                        "refresh_cache": True,
                        "full_rescan": True,
                        "limit": 5,
                    },
                },
            },
        )

    def test_omits_limit_from_kwargs_when_none(self):
        schedule = build_anime_franchise_import_schedule(
            enabled=True,
            interval_minutes=60,
            profile="continuity",
            refresh_cache=False,
            full_rescan=False,
            limit=None,
        )

        self.assertEqual(
            schedule["auto_import_anime_franchise"]["kwargs"],
            {
                "profile_key": "continuity",
                "refresh_cache": False,
                "full_rescan": False,
            },
        )
