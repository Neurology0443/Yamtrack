from django.test import TestCase
from django.urls import reverse


class ServiceWorkerViewTests(TestCase):
    """Tests for the service worker view."""

    def test_service_worker_returns_javascript_with_expected_header(self):
        """Service worker endpoint returns JS content and required header."""
        response = self.client.get(reverse("service_worker"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response["Content-Type"].startswith("application/javascript"),
        )
        self.assertEqual(response["Service-Worker-Allowed"], "/")
