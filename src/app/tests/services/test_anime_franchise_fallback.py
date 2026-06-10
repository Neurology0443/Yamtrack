from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.test.utils import override_settings

from app.services.anime_franchise_fallback import (
    _fallback_metadata_fetcher,
    build_series_line_fallback_payload,
    has_direct_continuity_relation,
)
from app.services.anime_franchise_types import AnimeNode

USER_SPECIFIC_KEYS = {
    "item",
    "media",
    "progress",
    "status",
    "user",
    "user_id",
    "html",
    "rendered_html",
}


def _metadata(relation_type="sequel"):
    return {
        "media_id": "100",
        "title": "Root",
        "related": {
            "related_anime": [
                {"media_id": "101", "relation_type": relation_type},
            ],
        },
    }


def _node(media_id, title):
    return AnimeNode(
        media_id=str(media_id),
        title=title,
        source="mal",
        media_type="tv",
        image=f"img-{media_id}",
        start_date=date(2024, 1, int(str(media_id)[-1]) + 1),
        runtime_minutes=24,
        episode_count=12,
    )


def _snapshot(nodes):
    return SimpleNamespace(
        root_node=nodes[0],
        series_line=nodes,
    )


class AnimeFranchiseFallbackTests(SimpleTestCase):
    """Test lightweight MAL anime series-line fallback payloads."""

    @patch("app.services.anime_franchise_fallback.AnimeFranchiseSnapshotService")
    @override_settings(ANIME_FRANCHISE_FALLBACK_ENABLED=False)
    def test_fallback_disabled_returns_none_without_snapshot_build(
        self,
        mock_snapshot_service,
    ):
        """Disabled setting should bypass snapshot construction."""
        payload = build_series_line_fallback_payload("100", _metadata())

        self.assertIsNone(payload)
        mock_snapshot_service.assert_not_called()

    @patch("app.services.anime_franchise_fallback.AnimeFranchiseGraphBuilder")
    @override_settings(
        ANIME_FRANCHISE_FALLBACK_ENABLED=True,
        ANIME_FRANCHISE_FALLBACK_MAX_NODES=0,
    )
    def test_max_nodes_zero_disables_fallback_without_graph_build(
        self,
        mock_graph_builder,
    ):
        """Zero max nodes should disable the synchronous fallback."""
        payload = build_series_line_fallback_payload("100", _metadata())

        self.assertIsNone(payload)
        mock_graph_builder.assert_not_called()

    @patch("app.services.anime_franchise_fallback.AnimeFranchiseGraphBuilder")
    @override_settings(
        ANIME_FRANCHISE_FALLBACK_ENABLED=True,
        ANIME_FRANCHISE_FALLBACK_MAX_NODES=-1,
    )
    def test_negative_max_nodes_disables_fallback_without_graph_build(
        self,
        mock_graph_builder,
    ):
        """Negative max nodes should disable the synchronous fallback."""
        payload = build_series_line_fallback_payload("100", _metadata())

        self.assertIsNone(payload)
        mock_graph_builder.assert_not_called()

    @patch("app.services.anime_franchise_fallback.AnimeFranchiseGraphBuilder")
    @override_settings(ANIME_FRANCHISE_FALLBACK_ENABLED=True)
    def test_without_direct_continuity_relation_returns_none_without_graph_build(
        self,
        mock_graph_builder,
    ):
        """Non-continuity direct relations should not start graph discovery."""
        payload = build_series_line_fallback_payload(
            "100",
            {
                "media_id": "100",
                "title": "Root",
                "related": {
                    "related_anime": [
                        {"media_id": "200", "relation_type": "side_story"},
                        {"media_id": "300", "relation_type": "spin_off"},
                    ],
                },
            },
        )

        self.assertIsNone(payload)
        mock_graph_builder.assert_not_called()

    @patch("app.services.anime_franchise_fallback.AnimeFranchiseSnapshotService")
    @patch("app.services.anime_franchise_fallback.AnimeFranchiseGraphBuilder")
    @override_settings(
        ANIME_FRANCHISE_FALLBACK_ENABLED=True,
        ANIME_FRANCHISE_FALLBACK_MAX_NODES=15,
    )
    def test_direct_continuity_relation_produces_payload(
        self,
        mock_graph_builder,
        mock_snapshot_service,
    ):
        """A TV series line with at least two entries should produce a payload."""
        nodes = [
            _node("100", "Root"),
            _node("101", "Root Z"),
            _node("102", "Root GT"),
        ]
        mock_graph_builder.return_value.is_truncated = False
        mock_snapshot_service.return_value.build.return_value = _snapshot(nodes)

        payload = build_series_line_fallback_payload("100", _metadata())

        mock_graph_builder.assert_called_once()
        _, graph_kwargs = mock_graph_builder.call_args
        self.assertEqual(graph_kwargs["max_nodes"], 15)
        self.assertIs(graph_kwargs["metadata_fetcher"], _fallback_metadata_fetcher)

        self.assertIsNotNone(payload)
        self.assertEqual(payload["root_media_id"], "100")
        self.assertEqual(payload["display_title"], "Root")
        self.assertEqual(payload["sections"], [])
        self.assertFalse(payload["truncated"])
        self.assertTrue(payload["fallback"])
        self.assertEqual(payload["series"]["title"], "Series")
        self.assertEqual(payload["series"]["key"], "series_line")
        entries = payload["series"]["entries"]
        self.assertEqual(len(entries), 3)
        self.assertTrue(entries[0]["is_current"])
        self.assertFalse(entries[1]["is_current"])
        self.assertEqual(entries[0]["media_type"], "anime")
        self.assertEqual(entries[0]["anime_media_type"], "tv")
        self.assertEqual(entries[0]["start_date"], "2024-01-01")
        for entry in entries:
            self.assertTrue(
                {
                    "media_id",
                    "source",
                    "media_type",
                    "anime_media_type",
                    "title",
                    "image",
                    "start_date",
                    "runtime_minutes",
                    "episode_count",
                    "is_current",
                }.issubset(entry),
            )
            self.assertFalse(USER_SPECIFIC_KEYS & set(entry))

    @patch("app.services.anime_franchise_fallback.AnimeFranchiseSnapshotService")
    @override_settings(ANIME_FRANCHISE_FALLBACK_ENABLED=True)
    def test_single_entry_series_line_returns_none(self, mock_snapshot_service):
        """Single-entry series lines should not replace direct MAL relations."""
        mock_snapshot_service.return_value.build.return_value = _snapshot(
            [_node("100", "Root")],
        )

        payload = build_series_line_fallback_payload("100", _metadata())

        self.assertIsNone(payload)

    @patch("app.services.anime_franchise_fallback.AnimeFranchiseSnapshotService")
    @override_settings(ANIME_FRANCHISE_FALLBACK_ENABLED=True)
    def test_snapshot_exception_fails_open(self, mock_snapshot_service):
        """Snapshot errors should not propagate to the details page."""
        mock_snapshot_service.return_value.build.side_effect = RuntimeError("boom")

        payload = build_series_line_fallback_payload("100", _metadata())

        self.assertIsNone(payload)

    @patch("app.services.anime_franchise_fallback.AnimeFranchiseSnapshotService")
    @patch("app.services.anime_franchise_fallback.AnimeFranchiseGraphBuilder")
    @override_settings(
        ANIME_FRANCHISE_FALLBACK_ENABLED=True,
        ANIME_FRANCHISE_FALLBACK_MAX_NODES=999,
    )
    def test_fallback_max_nodes_is_clamped(
        self,
        mock_graph_builder,
        mock_snapshot_service,
    ):
        """Overlarge fallback limits should be clamped to the hard cap."""
        mock_graph_builder.return_value.is_truncated = False
        mock_snapshot_service.return_value.build.return_value = _snapshot(
            [_node("100", "Root"), _node("101", "Root Z")],
        )

        payload = build_series_line_fallback_payload("100", _metadata())

        mock_graph_builder.assert_called_once()
        _, graph_kwargs = mock_graph_builder.call_args
        self.assertEqual(graph_kwargs["max_nodes"], 30)
        self.assertIs(graph_kwargs["metadata_fetcher"], _fallback_metadata_fetcher)
        self.assertFalse(payload["truncated"])

    @patch("app.services.anime_franchise_fallback.mal.anime")
    def test_fallback_metadata_fetcher_allows_stale_without_scheduling_refresh(
        self,
        mock_anime,
    ):
        """Fallback metadata fetches should allow stale cache without scheduling."""
        _fallback_metadata_fetcher("100", refresh_cache=False)

        mock_anime.assert_called_once_with(
            "100",
            refresh_cache=False,
            allow_stale=True,
            schedule_stale_refresh=False,
        )

    @patch("app.services.anime_franchise_fallback.AnimeFranchiseGraphBuilder")
    @override_settings(ANIME_FRANCHISE_FALLBACK_ENABLED=True)
    def test_invalid_related_shapes_return_none_without_graph_build(
        self,
        mock_graph_builder,
    ):
        """Invalid related containers should fail closed before graph discovery."""
        for related in (None, [], "bad", object()):
            with self.subTest(related=related):
                metadata = {"media_id": "100", "title": "Root", "related": related}

                self.assertFalse(has_direct_continuity_relation(metadata))
                self.assertIsNone(build_series_line_fallback_payload("100", metadata))

        mock_graph_builder.assert_not_called()

    @patch("app.services.anime_franchise_fallback.AnimeFranchiseGraphBuilder")
    @override_settings(ANIME_FRANCHISE_FALLBACK_ENABLED=True)
    def test_invalid_related_anime_shapes_return_none_without_graph_build(
        self,
        mock_graph_builder,
    ):
        """Invalid related_anime values should fail closed before graph discovery."""
        for related_anime in (None, "bad", {}):
            with self.subTest(related_anime=related_anime):
                metadata = {
                    "media_id": "100",
                    "title": "Root",
                    "related": {"related_anime": related_anime},
                }

                self.assertFalse(has_direct_continuity_relation(metadata))
                self.assertIsNone(build_series_line_fallback_payload("100", metadata))

        mock_graph_builder.assert_not_called()

    @patch("app.services.anime_franchise_fallback.AnimeFranchiseGraphBuilder")
    @override_settings(ANIME_FRANCHISE_FALLBACK_ENABLED=True)
    def test_non_string_relation_types_return_none_without_graph_build(
        self,
        mock_graph_builder,
    ):
        """Unexpected relation_type values should not reach graph discovery."""
        for relation_type in (123, {}, []):
            with self.subTest(relation_type=relation_type):
                metadata = _metadata(relation_type=relation_type)

                self.assertFalse(has_direct_continuity_relation(metadata))
                self.assertIsNone(build_series_line_fallback_payload("100", metadata))

        mock_graph_builder.assert_not_called()

