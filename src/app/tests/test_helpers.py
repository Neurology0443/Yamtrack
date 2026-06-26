from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.test import TestCase, override_settings

from app import helpers
from app.helpers import (
    build_absolute_app_url,
    enrich_items_with_user_data,
    form_error_messages,
    get_configured_app_url,
    minutes_to_hhmm,
    redirect_back,
)
from app.models import Anime, Item, MediaTypes, Movie, Sources, Status
from app.services import item_image_sync


class HelpersTest(TestCase):
    """Test helper functions."""

    def test_minutes_to_hhmm(self):
        """Test conversion of minutes to HH:MM format."""
        # Test minutes only
        self.assertEqual(minutes_to_hhmm(30), "30min")

        # Test hours and minutes
        self.assertEqual(minutes_to_hhmm(90), "1h 30min")
        self.assertEqual(minutes_to_hhmm(125), "2h 05min")

        # Test zero
        self.assertEqual(minutes_to_hhmm(0), "0min")

    @override_settings(URLS=["https://yamtrack.example.com:8924"])
    def test_get_configured_app_url_from_urls(self):
        """Test configured public origin from URLS."""
        self.assertEqual(
            get_configured_app_url(),
            "https://yamtrack.example.com:8924",
        )

    @override_settings(URLS=["https://yamtrack.example.com"])
    def test_build_absolute_app_url_uses_configured_origin(self):
        """Test absolute URL construction behind reverse proxies."""
        request = MagicMock()

        result = build_absolute_app_url(request, "/import/trakt/private")

        self.assertEqual(result, "https://yamtrack.example.com/import/trakt/private")
        request.build_absolute_uri.assert_not_called()

    @override_settings(URLS=[])
    def test_build_absolute_app_url_falls_back_to_request(self):
        """Test request-based absolute URL construction without URLS."""
        request = MagicMock()
        request.build_absolute_uri.return_value = (
            "http://testserver/import/trakt/private"
        )

        result = build_absolute_app_url(request, "/import/trakt/private")

        self.assertEqual(result, "http://testserver/import/trakt/private")
        request.build_absolute_uri.assert_called_once_with("/import/trakt/private")

    @patch("app.helpers.url_has_allowed_host_and_scheme")
    @patch("app.helpers.HttpResponseRedirect")
    @patch("app.helpers.redirect")
    def test_redirect_back_with_next(self, _, mock_http_redirect, mock_url_check):
        """Test redirect_back with a 'next' parameter."""
        mock_url_check.return_value = True
        mock_http_redirect.return_value = "redirected"

        request = MagicMock()
        request.GET = {"next": "http://example.com/path?page=2&sort=name"}

        result = redirect_back(request)

        # Check that we redirected to the URL without the page parameter
        mock_http_redirect.assert_called_once()
        redirect_url = mock_http_redirect.call_args[0][0]
        self.assertEqual(redirect_url, "http://example.com/path?sort=name")
        self.assertEqual(result, "redirected")

    @patch("app.helpers.url_has_allowed_host_and_scheme")
    @patch("app.helpers.redirect")
    def test_redirect_back_without_next(self, mock_redirect, mock_url_check):
        """Test redirect_back without a 'next' parameter."""
        mock_url_check.return_value = False
        mock_redirect.return_value = "home_redirect"

        request = MagicMock()
        request.GET = {}

        result = redirect_back(request)

        mock_redirect.assert_called_once_with("home")
        self.assertEqual(result, "home_redirect")

    @patch("app.helpers.messages")
    def test_form_error_messages(self, mock_messages):
        """Test form_error_messages function."""
        form = MagicMock()
        form.errors = {
            "title": ["This field is required."],
            "release_date": ["Enter a valid date."],
        }
        request = HttpRequest()

        form_error_messages(form, request)

        # Check that error messages were added
        self.assertEqual(mock_messages.error.call_count, 2)
        mock_messages.error.assert_any_call(request, "Title: This field is required.")
        mock_messages.error.assert_any_call(
            request,
            "Release Date: Enter a valid date.",
        )


class EnrichItemsWithUserDataTest(TestCase):
    """Test the enrich_items_with_user_data function."""

    def setUp(self):
        """Set up test data."""
        self.credentials = {"username": "test", "password": "testpass"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.request = MagicMock()
        self.request.user = self.user

        # Create test items in the database
        self.movie_item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
            image="http://example.com/movie.jpg",
        )

        self.season_item = Item.objects.create(
            media_id="67890",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Test TV Show",
            image="http://example.com/show.jpg",
            season_number=1,
        )

        # Create user tracking data for the movie
        self.movie_media = Movie.objects.create(
            item=self.movie_item,
            user=self.user,
            status=Status.PLANNING.value,
            progress=1,
        )

    def test_enrich_items_with_user_data(self):
        """Test enriching items with multiple scenarios."""
        raw_items = [
            # Scenario 1: Existing movie with user tracking data
            {
                "media_id": "238",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "title": "Test Movie",
                "image": "http://example.com/movie.jpg",
                "release_date": "2023-01-01",
                "rating": 8.5,
                "genre": "Action",
            },
            # Scenario 2: Existing season without user tracking data
            {
                "media_id": "67890",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.SEASON.value,
                "title": "Test TV Show",
                "season_title": "Season 1",
                "season_number": 1,
                "image": "http://example.com/show.jpg",
            },
            # Scenario 3: Non-existent item (raw data only)
            {
                "media_id": "99999",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "title": "Unknown Movie",
                "image": "http://example.com/unknown.jpg",
                "description": "This movie doesn't exist in our database",
            },
        ]

        enriched_items = enrich_items_with_user_data(self.request, raw_items, "test")
        self.assertEqual(len(enriched_items), 3)

        # Scenario 1: Existing movie with user tracking data
        movie_enriched = enriched_items[0]
        self.assertEqual(movie_enriched["media"], self.movie_media)
        self.assertEqual(movie_enriched["item"]["title"], "Test Movie")
        self.assertEqual(movie_enriched["item"]["media_id"], "238")
        # Verify additional properties are preserved
        self.assertEqual(movie_enriched["item"]["release_date"], "2023-01-01")
        self.assertEqual(movie_enriched["item"]["rating"], 8.5)
        self.assertEqual(movie_enriched["item"]["genre"], "Action")

        # Scenario 2: Existing season without user tracking data
        season_enriched = enriched_items[1]
        self.assertEqual(
            season_enriched["media"],
            None,
        )  # No user tracking for this season
        self.assertEqual(
            season_enriched["item"]["season_title"],
            "Season 1",
        )  # Should use season_title
        self.assertEqual(season_enriched["item"]["season_number"], 1)

        # Scenario 3: Non-existent movie (raw data)
        unknown_movie_enriched = enriched_items[2]
        self.assertEqual(
            unknown_movie_enriched["item"]["media_id"],
            raw_items[2]["media_id"],
        )
        self.assertEqual(unknown_movie_enriched["media"], None)
        self.assertEqual(unknown_movie_enriched["item"]["title"], "Unknown Movie")
        self.assertEqual(unknown_movie_enriched["item"]["media_id"], "99999")
        self.assertEqual(
            unknown_movie_enriched["item"]["description"],
            "This movie doesn't exist in our database",
        )

    def test_hide_completed_recommendations_enabled(self):
        """Test that completed items are hidden when preference is enabled."""
        self.user.hide_completed_recommendations = True
        self.user.save()
        Movie.objects.filter(pk=self.movie_media.pk).update(
            status=Status.COMPLETED.value
        )

        raw_items = [
            {
                "media_id": "238",  # This is our completed movie
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "title": "Test Movie",
                "image": "http://example.com/movie.jpg",
            },
            {
                "media_id": "99999",  # Not tracked
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "title": "Unknown Movie",
                "image": "http://example.com/unknown.jpg",
            },
        ]

        # When section is "recommendations", completed items should be hidden
        enriched_items = enrich_items_with_user_data(
            self.request, raw_items, "recommendations"
        )
        self.assertEqual(len(enriched_items), 1)
        self.assertEqual(enriched_items[0]["item"]["media_id"], "99999")

    def test_hide_completed_recommendations_disabled(self):
        """Test that completed items are shown when preference is disabled."""
        self.user.hide_completed_recommendations = False
        self.user.save()
        Movie.objects.filter(pk=self.movie_media.pk).update(
            status=Status.COMPLETED.value
        )

        raw_items = [
            {
                "media_id": "238",  # This is our completed movie
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "title": "Test Movie",
                "image": "http://example.com/movie.jpg",
            },
            {
                "media_id": "99999",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "title": "Unknown Movie",
                "image": "http://example.com/unknown.jpg",
            },
        ]

        # With preference disabled, all items should be returned
        enriched_items = enrich_items_with_user_data(
            self.request, raw_items, "recommendations"
        )
        self.assertEqual(len(enriched_items), 2)

    def test_enrich_items_with_user_data_refreshes_stale_mal_image(self):
        """Test stale MAL images are refreshed from already-loaded provider data."""
        item = Item.objects.create(
            media_id="59193",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Mushoku Tensei III: Isekai Ittara Honki Dasu",
            image="https://myanimelist.net/images/anime/old.webp",
        )
        Anime.objects.create(
            item=item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        entry = {
            "media_id": "59193",
            "source": Sources.MAL.value,
            "media_type": MediaTypes.ANIME.value,
            "title": "Mushoku Tensei III: Isekai Ittara Honki Dasu",
            "image": "https://cdn.myanimelist.net/images/anime/1527/158340l.jpg",
        }

        result = helpers.enrich_items_with_user_data(
            self.request,
            [entry],
            "test_section",
        )

        item.refresh_from_db()
        self.assertEqual(item.image, entry["image"])
        self.assertEqual(result[0]["media"].item.image, entry["image"])
        self.assertEqual(result[0]["item"]["image"], entry["image"])

    def test_enrich_items_with_user_data_deduplicates_image_refreshes(self):
        """Test duplicate provider entries only schedule one image bulk update."""
        item = Item.objects.create(
            media_id="59193",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Mushoku Tensei III: Isekai Ittara Honki Dasu",
            image="https://myanimelist.net/images/anime/old.webp",
        )
        Anime.objects.create(
            item=item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        entry = {
            "media_id": "59193",
            "source": Sources.MAL.value,
            "media_type": MediaTypes.ANIME.value,
            "title": "Mushoku Tensei III: Isekai Ittara Honki Dasu",
            "image": "https://cdn.myanimelist.net/images/anime/1527/158340l.jpg",
        }

        with patch("app.helpers.Item.objects.bulk_update") as bulk_update:
            helpers.enrich_items_with_user_data(
                self.request,
                [entry, entry.copy()],
                "test_section",
            )

        bulk_update.assert_called_once()
        updated_items = list(bulk_update.call_args.args[0])
        self.assertEqual(len(updated_items), 1)


class ImageRefreshTest(TestCase):
    """Test compatibility helper logic for refreshing stored item images."""

    def test_should_sync_provider_image_for_missing_image(self):
        """Test a missing image is refreshed."""
        item = Item(
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            image="",
        )

        self.assertTrue(
            item_image_sync.should_sync_provider_image(
                item,
                "https://cdn.myanimelist.net/images/anime/new.jpg",
            )
        )

    def test_should_sync_provider_image_for_placeholder_image(self):
        """Test the placeholder image is refreshed."""
        item = Item(
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            image=settings.IMG_NONE,
        )

        self.assertTrue(
            item_image_sync.should_sync_provider_image(
                item,
                "https://cdn.myanimelist.net/images/anime/new.jpg",
            )
        )

    def test_should_sync_provider_image_for_stale_mal_image(self):
        """Test a stale MAL image is refreshed."""
        item = Item(
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            image="https://myanimelist.net/images/anime/old.webp",
        )

        self.assertTrue(
            item_image_sync.should_sync_provider_image(
                item,
                "https://cdn.myanimelist.net/images/anime/new.jpg",
            )
        )

    def test_should_sync_provider_image_skips_identical_image(self):
        """Test an identical provider image is not refreshed."""
        image = "https://cdn.myanimelist.net/images/anime/new.jpg"
        item = Item(
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            image=image,
        )

        self.assertFalse(item_image_sync.should_sync_provider_image(item, image))

    def test_should_sync_provider_image_skips_absent_provider_images(self):
        """Test absent provider images do not replace stored images."""
        for new_image in (None, "", settings.IMG_NONE):
            item = Item(
                source=Sources.MAL.value,
                media_type=MediaTypes.ANIME.value,
                image="https://cdn.myanimelist.net/images/anime/current.jpg",
            )

            self.assertFalse(
                item_image_sync.should_sync_provider_image(item, new_image)
            )

    def test_should_sync_provider_image_protects_manual_source(self):
        """Test manual images are not replaced by provider images."""
        item = Item(
            source=Sources.MANUAL.value,
            media_type=MediaTypes.ANIME.value,
            image="https://example.com/custom.jpg",
        )

        self.assertFalse(
            item_image_sync.should_sync_provider_image(
                item,
                "https://cdn.myanimelist.net/images/anime/provider.jpg",
            )
        )

    def test_should_sync_provider_image_protects_filled_non_mal_source(self):
        """Test filled non-MAL source images are not refreshed."""
        item = Item(
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            image="https://image.tmdb.org/old.jpg",
        )

        self.assertFalse(
            item_image_sync.should_sync_provider_image(
                item,
                "https://image.tmdb.org/new.jpg",
            )
        )

    def test_refresh_item_image_if_missing_refreshes_stale_mal_image(self):
        """Test refresh_item_image_if_missing updates stale MAL images."""
        item = Item.objects.create(
            media_id="59193",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Mushoku Tensei III: Isekai Ittara Honki Dasu",
            image="https://myanimelist.net/images/anime/old.webp",
        )
        new_image = "https://cdn.myanimelist.net/images/anime/1527/158340l.jpg"

        helpers.refresh_item_image_if_missing(item, new_image)

        item.refresh_from_db()
        self.assertEqual(item.image, new_image)

    def test_refresh_item_image_if_missing_protects_manual_source(self):
        """Test refresh_item_image_if_missing preserves manual images."""
        image_custom = "https://example.com/custom.jpg"
        item = Item.objects.create(
            media_id="manual-anime",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Custom Anime",
            image=image_custom,
        )
        new_image = "https://cdn.myanimelist.net/images/anime/provider.jpg"

        helpers.refresh_item_image_if_missing(item, new_image)

        item.refresh_from_db()
        self.assertEqual(item.image, image_custom)
