# ruff: noqa: D101,D102,D107
from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase

from app.services.anime_franchise import AnimeFranchiseService
from app.services.anime_franchise_ui_builder import AnimeFranchiseUiBuilder
from app.services.anime_franchise_ui_policies import UiPolicySuite
from app.services.anime_franchise_ui_policy_resolver import (
    SYSTEM_DEFAULT_UI_PROFILE_KEY,
    resolve_ui_policy_suite,
)
from app.services.anime_franchise_ui_profiles import NoCharacterRelationsUiProfile
from app.services.anime_franchise_ui_profiles import build_policy_suite_from_legacy_profile
from app.services.anime_franchise_ui_profiles import get_ui_profile
from app.services.anime_franchise_ui_profiles import CuratedUiProfile
from app.services.anime_franchise_types import AnimeNode, AnimeRelation


class FakeGraphBuilder:
    def __init__(self, nodes, continuity_ids):
        self.nodes = nodes
        self.continuity_ids = set(continuity_ids)

    def build(self, root_media_id):
        del root_media_id
        return {media_id: self.nodes[media_id] for media_id in self.continuity_ids}

    def get_direct_neighbors(self, media_id):
        return self.nodes[str(media_id)].relations

    def ensure_node(self, media_id):
        return self.nodes[str(media_id)]


class ResolveUiPolicySuiteTests(SimpleTestCase):
    def test_ui_policy_suite_wins_over_profile_and_key(self):
        explicit_suite = UiPolicySuite(policies=())
        resolved = resolve_ui_policy_suite(
            ui_policy_suite=explicit_suite,
            ui_profile=NoCharacterRelationsUiProfile(),
            ui_profile_key="curated",
        )
        self.assertIs(resolved, explicit_suite)

    def test_ui_profile_is_adapted_when_no_explicit_suite(self):
        profile = NoCharacterRelationsUiProfile()
        resolved = resolve_ui_policy_suite(ui_profile=profile, ui_profile_key="default")
        expected = build_policy_suite_from_legacy_profile(profile)
        self.assertEqual([policy.key for policy in resolved.policies], [policy.key for policy in expected.policies])

    def test_ui_profile_key_is_resolved_and_adapted(self):
        resolved = resolve_ui_policy_suite(ui_profile_key="no_character")
        self.assertIn("hide_relation_types", [policy.key for policy in resolved.policies])

    def test_default_profile_is_used_when_nothing_is_provided(self):
        resolved = resolve_ui_policy_suite()
        expected = resolve_ui_policy_suite(ui_profile_key=SYSTEM_DEFAULT_UI_PROFILE_KEY)
        self.assertEqual([policy.key for policy in resolved.policies], [policy.key for policy in expected.policies])

    def test_default_profile_key_constant_is_used_when_no_inputs(self):
        with patch("app.services.anime_franchise_ui_policy_resolver.get_ui_profile") as profile_mock:
            profile_mock.return_value = get_ui_profile("default")
            resolve_ui_policy_suite()

        profile_mock.assert_called_once_with(SYSTEM_DEFAULT_UI_PROFILE_KEY)

    def test_empty_ui_profile_key_does_not_silently_fallback_to_default(self):
        with self.assertRaisesMessage(ValueError, "Unsupported UI profile ''"):
            resolve_ui_policy_suite(ui_profile_key="")

    def test_strict_priority_order_is_preserved(self):
        explicit_suite = UiPolicySuite(policies=())
        resolved = resolve_ui_policy_suite(
            ui_policy_suite=explicit_suite,
            ui_profile=CuratedUiProfile(),
            ui_profile_key="no_character",
        )
        self.assertIs(resolved, explicit_suite)


class UiResolverIntegrationTests(SimpleTestCase):
    def _nodes(self):
        return {
            "100": AnimeNode(
                media_id="100",
                title="Series S1",
                source="mal",
                media_type="tv",
                image="img-100",
                start_date=date(2010, 1, 1),
                relations=[
                    AnimeRelation("100", "101", "sequel"),
                    AnimeRelation("100", "204", "spin_off"),
                    AnimeRelation("100", "205", "spin_off"),
                    AnimeRelation("100", "206", "character"),
                    AnimeRelation("100", "207", "side_story"),
                ],
            ),
            "101": AnimeNode(
                media_id="101",
                title="Series S2",
                source="mal",
                media_type="tv",
                image="img-101",
                start_date=date(2011, 1, 1),
                relations=[AnimeRelation("101", "100", "prequel")],
            ),
            "204": AnimeNode("204", "Spin Off TV", "mal", "tv", "img", date(2011, 4, 1)),
            "205": AnimeNode("205", "Spin Off Special", "mal", "special", "img", date(2011, 5, 1)),
            "206": AnimeNode("206", "Character Story", "mal", "special", "img", date(2011, 6, 1)),
            "207": AnimeNode("207", "Preview short", "mal", "ova", "img", date(2011, 7, 1)),
        }

    def _related_series_ids(self, *, profile_key: str) -> list[str]:
        service = AnimeFranchiseService(
            graph_builder=FakeGraphBuilder(self._nodes(), continuity_ids={"100", "101"}),
            ui_profile_key=profile_key,
        )
        view_model = service.build("101")
        related = next(section for section in view_model.sections if section.key == "related_series")
        return [entry["media_id"] for entry in related.entries]

    def test_default_no_character_and_curated_behave_as_before(self):
        self.assertEqual(self._related_series_ids(profile_key="default"), ["204", "205", "206"])
        self.assertEqual(self._related_series_ids(profile_key="no_character"), ["204", "205"])
        self.assertEqual(self._related_series_ids(profile_key="curated"), ["204"])

    def test_service_uses_resolver_in_main_path(self):
        suite = resolve_ui_policy_suite(ui_profile_key="default")
        with patch("app.services.anime_franchise.resolve_ui_policy_suite", return_value=suite) as resolver_mock:
            service = AnimeFranchiseService()

        resolver_mock.assert_called_once_with(
            ui_policy_suite=None,
            ui_profile=None,
            ui_profile_key=None,
            user=None,
            instance=None,
        )
        self.assertIsInstance(service.ui_builder, AnimeFranchiseUiBuilder)
        self.assertIs(service.ui_builder.ui_policy_suite, suite)

    def test_service_does_not_call_resolver_when_ui_builder_is_injected(self):
        injected_builder = AnimeFranchiseUiBuilder(
            ui_policy_suite=resolve_ui_policy_suite(ui_profile_key="no_character")
        )
        with patch("app.services.anime_franchise.resolve_ui_policy_suite") as resolver_mock:
            service = AnimeFranchiseService(ui_builder=injected_builder)

        resolver_mock.assert_not_called()
        self.assertIs(service.ui_builder, injected_builder)

    def test_service_rejects_ui_builder_with_ui_policy_suite(self):
        injected_builder = AnimeFranchiseUiBuilder(
            ui_policy_suite=resolve_ui_policy_suite(ui_profile_key="default")
        )
        with self.assertRaisesMessage(
            ValueError,
            "ui_builder is a full override and cannot be combined",
        ):
            AnimeFranchiseService(
                ui_builder=injected_builder,
                ui_policy_suite=UiPolicySuite(),
            )

    def test_service_rejects_ui_builder_with_ui_profile(self):
        injected_builder = AnimeFranchiseUiBuilder(
            ui_policy_suite=resolve_ui_policy_suite(ui_profile_key="default")
        )
        with self.assertRaisesMessage(
            ValueError,
            "ui_builder is a full override and cannot be combined",
        ):
            AnimeFranchiseService(
                ui_builder=injected_builder,
                ui_profile=NoCharacterRelationsUiProfile(),
            )

    def test_service_rejects_ui_builder_with_ui_profile_key(self):
        injected_builder = AnimeFranchiseUiBuilder(
            ui_policy_suite=resolve_ui_policy_suite(ui_profile_key="default")
        )
        with self.assertRaisesMessage(
            ValueError,
            "ui_builder is a full override and cannot be combined",
        ):
            AnimeFranchiseService(
                ui_builder=injected_builder,
                ui_profile_key="default",
            )

    def test_resolver_path_matches_legacy_profile_adapter_for_default(self):
        service_suite = resolve_ui_policy_suite(ui_profile_key="default")
        self.assertEqual(
            [policy.key for policy in service_suite.policies],
            [policy.key for policy in build_policy_suite_from_legacy_profile(get_ui_profile("default")).policies],
        )


class UiBuilderContractTests(SimpleTestCase):
    def test_builder_requires_resolved_ui_policy_suite(self):
        with self.assertRaisesMessage(
            ValueError,
            "AnimeFranchiseUiBuilder requires a resolved UiPolicySuite",
        ):
            AnimeFranchiseUiBuilder()
