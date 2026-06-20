# ruff: noqa: D102
from types import SimpleNamespace

from django.test import SimpleTestCase

from app.services.anime_series_view_franchise_projection import (
    resolve_series_line_root,
)


class AnimeSeriesViewFranchiseProjectionTests(SimpleTestCase):
    """Test the deliberately strict series-line root resolver."""

    def test_returns_first_series_line_node(self):
        first = object()
        snapshot = SimpleNamespace(series_line=[first, object()])

        self.assertIs(resolve_series_line_root(snapshot), first)

    def test_empty_series_line_has_no_fallback(self):
        snapshot = SimpleNamespace(
            series_line=[],
            canonical_root_media_id="canonical",
            root_node=object(),
        )

        self.assertIsNone(resolve_series_line_root(snapshot))
