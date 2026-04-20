"""Tests for minimal native UI policy registry helpers."""

from django.test import SimpleTestCase

from app.services.anime_franchise_ui_policies import (
    HideMediaTypesPolicy,
    HideRelationTypesPolicy,
    HideTitlesPolicy,
    UiPolicySuite,
)
from app.services.anime_franchise_ui_policy_registry import build_policy, build_policy_suite
from app.services.anime_franchise_ui_policies import UiPolicySpec


class UiPolicyRegistryTests(SimpleTestCase):
    def test_build_policy_hide_relation_types(self):
        policy = build_policy(
            UiPolicySpec(
                key="hide_relation_types",
                params={"relation_types": ["character", "summary"]},
            )
        )

        self.assertIsInstance(policy, HideRelationTypesPolicy)
        self.assertEqual(policy.relation_types, frozenset({"character", "summary"}))

    def test_build_policy_hide_media_types(self):
        policy = build_policy(
            UiPolicySpec(
                key="hide_media_types",
                params={"media_types": ["special", "tv_special"]},
            )
        )

        self.assertIsInstance(policy, HideMediaTypesPolicy)
        self.assertEqual(policy.media_types, frozenset({"special", "tv_special"}))

    def test_build_policy_hide_titles(self):
        policy = build_policy(
            UiPolicySpec(
                key="hide_titles",
                params={"titles": ["Preview Short", "Other Noise"]},
            )
        )

        self.assertIsInstance(policy, HideTitlesPolicy)
        self.assertEqual(policy.hidden_titles, frozenset({"Preview Short", "Other Noise"}))

    def test_build_policy_suite_builds_expected_policy_instances(self):
        suite = build_policy_suite(
            [
                UiPolicySpec("hide_relation_types", params={"relation_types": ["character"]}),
                UiPolicySpec("hide_media_types", params={"media_types": ["special"]}),
                UiPolicySpec("hide_titles", params={"titles": ["Preview Short"]}),
            ]
        )

        self.assertIsInstance(suite, UiPolicySuite)
        self.assertEqual(
            [policy.__class__.__name__ for policy in suite.policies],
            [
                "HideRelationTypesPolicy",
                "HideMediaTypesPolicy",
                "HideTitlesPolicy",
            ],
        )

    def test_build_policy_unknown_key_raises_clear_error(self):
        with self.assertRaisesMessage(ValueError, "Unsupported UI policy 'unknown'"):
            build_policy(UiPolicySpec(key="unknown"))
