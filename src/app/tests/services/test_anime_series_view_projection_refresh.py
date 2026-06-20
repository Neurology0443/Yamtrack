# ruff: noqa: D101, D102, D103

from types import SimpleNamespace
from unittest.mock import Mock, call

from django.test import SimpleTestCase

from app.services.anime_franchise_types import AnimeRelation
from app.services.anime_series_view_projection import AnimeSeriesViewProjection
from app.services.anime_series_view_projection_persistence import (
    AnimeSeriesViewPersistenceStats,
)
from app.services.anime_series_view_projection_refresh import (
    AnimeSeriesViewProjectionRefreshService,
)


def fake_snapshot(
    node_ids,
    *,
    root_media_id,
    series_line_ids,
    relations=(),
    media_types=None,
    canonical_root_media_id=None,
):
    media_types = media_types or {}
    nodes = {
        str(media_id): SimpleNamespace(
            media_id=str(media_id),
            media_type=media_types.get(str(media_id), "tv"),
        )
        for media_id in node_ids
    }
    return SimpleNamespace(
        nodes_by_media_id=nodes,
        root_node=nodes[str(root_media_id)],
        series_line=[nodes[str(media_id)] for media_id in series_line_ids],
        all_normalized_relations=list(relations),
        canonical_root_media_id=str(
            canonical_root_media_id or root_media_id
        ),
    )


def relation(source, target, relation_type):
    return AnimeRelation(
        source_media_id=str(source),
        target_media_id=str(target),
        relation_type=relation_type,
    )


class AnimeSeriesViewProjectionRefreshTests(SimpleTestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=7)
        self.snapshot = fake_snapshot(
            {"1", "2"},
            root_media_id="1",
            series_line_ids=["1", "2"],
        )
        self.snapshot_service = Mock()
        self.snapshot_service.build.return_value = self.snapshot
        self.builder = Mock()
        self.projection = AnimeSeriesViewProjection(
            groups=(),
            projection_version="v2",
        )
        self.builder.build.return_value = self.projection
        self.persistence = Mock()
        self.persistence.persist.return_value = AnimeSeriesViewPersistenceStats()
        self.tracked_fetcher = Mock(return_value={"1"})
        self.service = AnimeSeriesViewProjectionRefreshService(
            snapshot_service=self.snapshot_service,
            projection_builder=self.builder,
            persistence_service=self.persistence,
            tracked_ids_fetcher=self.tracked_fetcher,
        )

    def test_builds_snapshot_fetches_tracked_ids_and_persists(self):
        stats = self.service.refresh_for_media_ids(
            user=self.user,
            media_ids={"1"},
        )

        self.snapshot_service.build.assert_called_once_with(
            "1",
            refresh_cache=False,
            include_branch_continuations=True,
        )
        self.tracked_fetcher.assert_called_once_with(
            user_id=7,
            media_ids=frozenset({"1", "2"}),
        )
        self.builder.build.assert_called_once_with(
            snapshot=self.snapshot,
            tracked_media_ids={"1"},
        )
        self.persistence.persist.assert_called_once_with(
            user=self.user,
            projection=self.projection,
            scope_media_ids=frozenset({"1", "2"}),
            dry_run=False,
        )
        self.assertEqual(stats.snapshots_refreshed, 1)

    def test_identical_snapshot_scopes_are_refreshed_once(self):
        stats = self.service.refresh_for_media_ids(
            user=self.user,
            media_ids={"1", "2"},
        )

        self.assertEqual(self.snapshot_service.build.call_count, 2)
        self.assertEqual(self.builder.build.call_count, 1)
        self.assertEqual(self.persistence.persist.call_count, 1)
        self.assertEqual(stats.snapshots_skipped, 1)

    def test_reanchors_satellite_seed_snapshot_to_complete_projection_scope(self):
        initial = fake_snapshot(
            {"48896", "48895"},
            root_media_id="48896",
            series_line_ids=[],
            media_types={"48896": "movie", "48895": "tv"},
            relations=[
                relation("48896", "48895", "parent_story"),
                relation("48895", "37675", "prequel"),
            ],
        )
        complete = fake_snapshot(
            {"29803", "35073", "37675", "48895", "48896"},
            root_media_id="48895",
            series_line_ids=["29803", "35073", "37675", "48895"],
            canonical_root_media_id="29803",
            relations=[
                relation("29803", "35073", "sequel"),
                relation("35073", "37675", "sequel"),
                relation("37675", "48895", "sequel"),
                relation("48895", "48896", "side_story"),
                relation("48896", "48895", "parent_story"),
            ],
        )

        def build(
            media_id,
            *,
            refresh_cache,
            include_branch_continuations,
        ):
            self.assertFalse(refresh_cache)
            self.assertTrue(include_branch_continuations)
            if media_id == "48896":
                return initial
            if media_id == "48895":
                return complete
            message = "optional external candidate failed"
            raise RuntimeError(message)

        self.snapshot_service.build.side_effect = build
        tracked_ids = {"29803", "35073", "37675", "48895", "48896"}
        self.tracked_fetcher.return_value = tracked_ids
        self.service.refresh_for_media_ids(
            user=self.user,
            media_ids={"48896"},
        )

        self.assertEqual(
            self.snapshot_service.build.call_args_list,
            [
                call(
                    "48896",
                    refresh_cache=False,
                    include_branch_continuations=True,
                ),
                call(
                    "48895",
                    refresh_cache=False,
                    include_branch_continuations=True,
                ),
            ],
        )
        self.builder.build.assert_called_once_with(
            snapshot=complete,
            tracked_media_ids=tracked_ids,
        )
        self.persistence.persist.assert_called_once_with(
            user=self.user,
            projection=self.projection,
            scope_media_ids=frozenset(
                {"29803", "35073", "37675", "48895", "48896"}
            ),
            dry_run=False,
        )

    def test_reanchor_candidate_must_cover_initial_relevant_component(self):
        initial = fake_snapshot(
            {"movie", "parent_tv", "side_story"},
            root_media_id="movie",
            series_line_ids=[],
            media_types={
                "movie": "movie",
                "parent_tv": "tv",
                "side_story": "special",
            },
            relations=[
                relation("movie", "parent_tv", "parent_story"),
                relation("movie", "side_story", "side_story"),
                relation("parent_tv", "older_tv", "prequel"),
            ],
        )
        incomplete_candidate = fake_snapshot(
            {"movie", "parent_tv", "older_tv"},
            root_media_id="parent_tv",
            series_line_ids=["older_tv", "parent_tv"],
            relations=[
                relation("older_tv", "parent_tv", "sequel"),
                relation("movie", "parent_tv", "parent_story"),
            ],
        )
        complete_candidate = fake_snapshot(
            {"movie", "parent_tv", "side_story", "older_tv"},
            root_media_id="older_tv",
            series_line_ids=["older_tv", "parent_tv"],
            relations=[
                relation("older_tv", "parent_tv", "sequel"),
                relation("movie", "parent_tv", "parent_story"),
                relation("movie", "side_story", "side_story"),
            ],
        )
        self.snapshot_service.build.side_effect = [
            initial,
            incomplete_candidate,
            complete_candidate,
        ]

        self.service.refresh_for_media_ids(
            user=self.user,
            media_ids={"movie"},
        )

        self.snapshot_service.build.assert_has_calls(
            [
                call(
                    "movie",
                    refresh_cache=False,
                    include_branch_continuations=True,
                ),
                call(
                    "parent_tv",
                    refresh_cache=False,
                    include_branch_continuations=True,
                ),
                call(
                    "older_tv",
                    refresh_cache=False,
                    include_branch_continuations=True,
                ),
            ]
        )
        self.builder.build.assert_called_once_with(
            snapshot=complete_candidate,
            tracked_media_ids={"1"},
        )

    def test_relevant_component_ignores_unrelated_relation_types(self):
        initial = fake_snapshot(
            {"movie", "parent_tv", "character"},
            root_media_id="movie",
            series_line_ids=[],
            media_types={
                "movie": "movie",
                "parent_tv": "tv",
                "character": "special",
            },
            relations=[
                relation("movie", "parent_tv", "parent_story"),
                relation("movie", "character", "character"),
            ],
        )
        candidate = fake_snapshot(
            {"movie", "parent_tv", "older_tv"},
            root_media_id="parent_tv",
            series_line_ids=["older_tv", "parent_tv"],
            relations=[
                relation("older_tv", "parent_tv", "sequel"),
                relation("movie", "parent_tv", "parent_story"),
            ],
        )
        self.snapshot_service.build.side_effect = [initial, candidate]

        self.service.refresh_for_media_ids(
            user=self.user,
            media_ids={"movie"},
        )

        self.builder.build.assert_called_once_with(
            snapshot=candidate,
            tracked_media_ids={"1"},
        )

    def test_complete_snapshot_does_not_reanchor(self):
        self.service.refresh_for_media_ids(
            user=self.user,
            media_ids={"1"},
        )

        self.snapshot_service.build.assert_called_once()

    def test_non_dominating_candidate_does_not_replace_initial(self):
        initial = fake_snapshot(
            {"1"},
            root_media_id="1",
            series_line_ids=[],
            relations=[relation("1", "2", "prequel")],
        )
        candidate = fake_snapshot(
            {"2", "3"},
            root_media_id="2",
            series_line_ids=["2"],
        )
        self.snapshot_service.build.side_effect = [initial, candidate]

        self.service.refresh_for_media_ids(
            user=self.user,
            media_ids={"1"},
        )

        self.builder.build.assert_called_once_with(
            snapshot=initial,
            tracked_media_ids={"1"},
        )

    def test_optional_candidate_failure_falls_back_to_initial(self):
        initial = fake_snapshot(
            {"1"},
            root_media_id="1",
            series_line_ids=[],
            relations=[relation("1", "2", "prequel")],
        )
        self.snapshot_service.build.side_effect = [
            initial,
            RuntimeError("boom"),
        ]

        stats = self.service.refresh_for_media_ids(
            user=self.user,
            media_ids={"1"},
        )

        self.builder.build.assert_called_once_with(
            snapshot=initial,
            tracked_media_ids={"1"},
        )
        self.assertEqual(self.persistence.persist.call_count, 1)
        self.assertEqual(stats.errors, 0)

    def test_snapshot_missing_requested_id_is_not_persisted(self):
        invalid = fake_snapshot(
            {"2"},
            root_media_id="2",
            series_line_ids=["2"],
        )
        self.snapshot_service.build.return_value = invalid

        stats = self.service.refresh_for_media_ids(
            user=self.user,
            media_ids={"1"},
        )

        self.assertEqual(stats.errors, 1)
        self.builder.build.assert_not_called()
        self.persistence.persist.assert_not_called()

    def test_deduplicates_complete_scope_after_reanchor(self):
        first_initial = fake_snapshot(
            {"8", "10"},
            root_media_id="8",
            series_line_ids=[],
            media_types={"8": "movie", "10": "tv"},
        )
        second_initial = fake_snapshot(
            {"9", "10"},
            root_media_id="9",
            series_line_ids=[],
            media_types={"9": "special", "10": "tv"},
        )
        complete = fake_snapshot(
            {"8", "9", "10"},
            root_media_id="10",
            series_line_ids=["10"],
        )

        def build(
            media_id,
            *,
            refresh_cache,
            include_branch_continuations,
        ):
            self.assertFalse(refresh_cache)
            self.assertTrue(include_branch_continuations)
            return {
                "8": first_initial,
                "9": second_initial,
                "10": complete,
            }[media_id]

        self.snapshot_service.build.side_effect = build
        stats = self.service.refresh_for_media_ids(
            user=self.user,
            media_ids={"8", "9"},
        )

        self.assertEqual(self.builder.build.call_count, 1)
        self.assertEqual(self.persistence.persist.call_count, 1)
        self.assertEqual(stats.snapshots_skipped, 1)

    def test_reanchor_candidates_are_deterministically_prioritized(self):
        snapshot = fake_snapshot(
            {"1", "2"},
            root_media_id="1",
            series_line_ids=[],
            media_types={"1": "movie", "2": "tv"},
            relations=[
                relation("1", "30", "spin_off"),
                relation("1", "20", "side_story"),
                relation("1", "10", "prequel"),
            ],
        )

        candidates = self.service._projection_reanchor_candidates(snapshot)

        self.assertEqual(candidates, ("2", "10", "20", "30"))

    def test_errors_are_counted_and_logged(self):
        self.snapshot_service.build.side_effect = RuntimeError("boom")

        with self.assertLogs(
            "app.services.anime_series_view_projection_refresh",
            level="ERROR",
        ):
            stats = self.service.refresh_for_media_ids(
                user=self.user,
                media_ids={"1"},
            )

        self.assertEqual(stats.errors, 1)
        self.assertEqual(stats.snapshots_skipped, 1)

    def test_dry_run_is_forwarded_to_persistence(self):
        self.service.refresh_for_media_ids(
            user=self.user,
            media_ids={"1"},
            dry_run=True,
        )

        self.assertTrue(self.persistence.persist.call_args.kwargs["dry_run"])
