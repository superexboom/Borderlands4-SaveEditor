import copy
import unittest
from unittest.mock import patch

from core.item_display_resolver import validate_weapon_generation, weapon_generation_context
from core.weapon_generation_logic import evaluate_group_selection


INDEX = {
    "part_refs": {
        "13:1": {"category": "inv_comp", "parent": "dad_ar"},
        "13:2": {"category": "body", "selection_group": "body", "selection_tags": {"adds": ["body"]}},
        "13:3": {
            "category": "barrel",
            "selection_group": "barrel",
            "selection_tags": {"adds": ["barrel", "licensed"]},
        },
        "13:4": {
            "category": "barrel_acc",
            "selection_group": "barrel_acc",
            "selection_tags": {"requires": ["barrel", "licensed"]},
        },
        "13:5": {
            "category": "barrel_acc",
            "selection_group": "barrel_acc",
            "selection_tags": {"adds": ["licensed"]},
        },
        "13:6": {
            "category": "body_acc",
            "selection_group": "body_acc",
            "selection_tags": {"adds": ["body_acc_ele"]},
        },
        "1:7": {
            "category": "body_ele",
            "selection_group": "body_ele",
            "selection_tags": {"adds": ["fire"], "requires": ["body_acc_ele"]},
        },
        "1:8": {
            "category": "body_ele",
            "selection_group": "body_ele",
            "selection_tags": {"excludes": ["weapon"]},
        },
        "14:9": {"category": "body", "selection_group": "body"},
        "13:9": {
            "category": "magazine",
            "selection_group": "magazine",
            "selection_tags": {"adds": ["cov_mag"]},
        },
        "13:10": {
            "category": "body_bolt",
            "selection_group": "body_bolt",
            "selection_tags": {"excludes": ["cov_mag"]},
        },
    },
    "weapon_generation_rules": {
        "part_selection_tags": {},
        "part_availability": {},
        "weapons": {
            "13": {
                "parent": "dad_ar",
                "manufacturer": "Daedalus",
                "weapon_type": "Assault Rifle",
                "part_types": ["body", "barrel", "barrel_acc", "body_acc", "body_ele", "magazine", "body_bolt"],
                "compositions": {
                    "13:1": {
                        "availability": "coregame",
                        "base_tags": ["weapon"],
                        "groups": {
                            "body": {"min": 1, "max": 1, "allowed_part_refs": ["13:2"]},
                            "barrel": {"min": 1, "max": 1, "allowed_part_refs": ["13:3"]},
                            "barrel_acc": {"min": 1, "max": 2, "allowed_part_refs": ["13:4", "13:5"]},
                            "body_acc": {
                                "source": "default",
                                "min": 0,
                                "max": 1,
                                "allowed_part_refs": ["13:6"],
                            },
                            "body_ele": {"min": 1, "max": 1, "allowed_part_refs": ["1:7", "1:8"]},
                            "magazine": {"min": 0, "max": 1, "allowed_part_refs": ["13:9"]},
                            "body_bolt": {"min": 0, "max": 1, "allowed_part_refs": ["13:10"]},
                        },
                        "tag_rules": [{"tags": ["licensed"], "max": 1}],
                        "forced_part_refs": [],
                    }
                },
            }
        },
    },
}


class WeaponGenerationValidationTests(unittest.TestCase):
    @patch("core.item_display_resolver._item_index", return_value=INDEX)
    def test_rules_are_order_independent_and_enforce_native_tag_semantics(self, _index):
        first = "13, 0, 1, 60| 2, 1|| {4} {1:[7]} {1} {6} {2} {3}|"
        reordered = "13, 0, 1, 60| 2, 1|| {3} {2} {6} {1} {1:[7]} {4}|"
        context = weapon_generation_context(first)
        self.assertEqual("13:1", context["composition_ref"])
        self.assertEqual(["1:7"], context["groups"]["body_ele"]["eligible_refs"])
        self.assertEqual("default", context["groups"]["body_acc"]["source"])
        self.assertEqual("legal", validate_weapon_generation(first)["status"])
        self.assertEqual(
            validate_weapon_generation(first)["status"],
            validate_weapon_generation(reordered)["status"],
        )
        self.assertEqual(
            "incomplete",
            validate_weapon_generation(first.replace(" {2}", ""), allow_incomplete=True)["status"],
        )
        no_conditional_provider = first.replace(" {1:[7]}", "").replace(" {6}", "")
        self.assertEqual([], weapon_generation_context(no_conditional_provider)["groups"]["body_ele"]["eligible_refs"])
        self.assertEqual("legal", validate_weapon_generation(no_conditional_provider)["status"])
        missing_conditional_part = first.replace(" {1:[7]}", "")
        self.assertEqual("modified", validate_weapon_generation(missing_conditional_part)["status"])
        self.assertEqual(
            "incomplete",
            validate_weapon_generation(missing_conditional_part, allow_incomplete=True)["status"],
        )
        self.assertEqual("modified", validate_weapon_generation(first.replace("1:[7]", "1:[8]"))["status"])
        self.assertEqual("modified", validate_weapon_generation(first.replace("{1:[7]}", "{1:[7]} {5}"))["status"])
        self.assertEqual("modified", validate_weapon_generation(first + " {14:[9]}")["status"])
        self.assertEqual("unknown", validate_weapon_generation(first.replace(" {1}", ""))["status"])

    @patch("core.item_display_resolver._item_index", return_value=INDEX)
    def test_exclusions_follow_native_group_order(self, _index):
        base = "13, 0, 1, 60| 2, 1|| {1} {2} {3} {4} {6} {1:[7]}|"
        self.assertEqual("legal", validate_weapon_generation(base + " {10}")["status"])
        self.assertEqual("modified", validate_weapon_generation(base + " {9} {10}")["status"])
        self.assertEqual("modified", validate_weapon_generation(base + " {10} {9}")["status"])

    def test_empty_conditional_pool_closes_without_count_error(self):
        index = copy.deepcopy(INDEX)
        index["part_refs"].update({
            "13:11": {
                "category": "trigger",
                "selection_group": "trigger",
                "selection_tags": {"adds": ["throw_enabled"]},
            },
            "13:12": {
                "category": "conditional",
                "selection_group": "conditional",
                "selection_tags": {"requires": ["throw_enabled", "mag_01"]},
            },
            "13:13": {
                "category": "conditional",
                "selection_group": "conditional",
                "selection_tags": {"requires": ["throw_enabled", "mag_02"]},
            },
        })
        weapon = index["weapon_generation_rules"]["weapons"]["13"]
        weapon["part_types"].extend(["trigger", "conditional"])
        groups = weapon["compositions"]["13:1"]["groups"]
        groups["trigger"] = {"min": 0, "max": 1, "allowed_part_refs": ["13:11"]}
        groups["conditional"] = {"min": 1, "max": 1, "allowed_part_refs": ["13:12", "13:13"]}
        decoded = "13, 0, 1, 60| 2, 1|| {1} {2} {3} {4} {6} {1:[7]} {11}|"
        with patch("core.item_display_resolver._item_index", return_value=index):
            context = weapon_generation_context(decoded)
            self.assertEqual(["throw_enabled"], context["groups"]["conditional"]["activation_tags"])
            self.assertFalse(context["groups"]["conditional"]["active"])
            self.assertEqual([], context["groups"]["conditional"]["eligible_refs"])
            self.assertEqual(0, context["groups"]["conditional"]["effective_max"])
            self.assertEqual("legal", validate_weapon_generation(decoded, allow_incomplete=True)["status"])

    def test_same_group_conflicts_are_removed_from_candidate_pool(self):
        index = copy.deepcopy(INDEX)
        index["part_refs"].update({
            "13:14": {
                "category": "barrel_acc",
                "selection_group": "barrel_acc",
                "selection_tags": {"adds": ["barrel_mod_d"], "excludes": ["licensed_topacc"]},
            },
            "13:15": {
                "category": "barrel_acc",
                "selection_group": "barrel_acc",
                "selection_tags": {"adds": ["licensed_topacc"], "excludes": ["barrel_mod_d"]},
            },
        })
        group = index["weapon_generation_rules"]["weapons"]["13"]["compositions"]["13:1"]["groups"]["barrel_acc"]
        group["allowed_part_refs"].extend(["13:14", "13:15"])
        decoded = "13, 0, 1, 60| 2, 1|| {1} {2} {3} {4} {6} {1:[7]} {14}|"
        with patch("core.item_display_resolver._item_index", return_value=index):
            context = weapon_generation_context(decoded)
            self.assertNotIn("13:15", context["groups"]["barrel_acc"]["eligible_refs"])
            self.assertEqual("modified", validate_weapon_generation(decoded + " {15}")["status"])

    def test_invalid_provider_does_not_enable_later_group(self):
        index = copy.deepcopy(INDEX)
        index["part_refs"]["13:16"] = {
            "category": "body_acc",
            "selection_group": "body_acc",
            "selection_tags": {"adds": ["body_acc_ele"]},
        }
        decoded = "13, 0, 1, 60| 2, 1|| {1} {2} {3} {4} {16}|"
        with patch("core.item_display_resolver._item_index", return_value=index):
            context = weapon_generation_context(decoded)
            self.assertFalse(context["groups"]["body_acc"]["selected_reachable"])
            self.assertEqual([], context["groups"]["body_ele"]["eligible_refs"])

    @patch("core.item_display_resolver._item_index", return_value=INDEX)
    def test_tag_limit_does_not_report_false_exclusion(self, _index):
        decoded = "13, 0, 1, 60| 2, 1|| {1} {2} {3} {5}|"
        result = validate_weapon_generation(decoded)
        codes = [violation["code"] for violation in result["violations"]]
        self.assertIn("tag_limit", codes)
        self.assertNotIn("excluded_tag_conflict", codes)

    def test_part_count_stops_when_candidate_pool_is_exhausted(self):
        tags = {ref: {} for ref in ("a", "b", "c")}
        complete = evaluate_group_selection(
            allowed_refs=list(tags), selected_refs=list(tags), tags_for_ref=tags.get,
            base_tags=(), tag_rules=(), base_tag_counts=(), minimum=4, maximum=4,
        )
        missing = evaluate_group_selection(
            allowed_refs=list(tags), selected_refs=["a", "b"], tags_for_ref=tags.get,
            base_tags=(), tag_rules=(), base_tag_counts=(), minimum=4, maximum=4,
        )
        self.assertTrue(complete["selected_terminal"])
        self.assertEqual([3], complete["terminal_counts"])
        self.assertFalse(missing["selected_terminal"])
        self.assertEqual(["c"], missing["remaining_eligible_refs"])

    def test_same_group_dependency_is_not_revived_after_initial_filter(self):
        tags = {
            "provider": {"adds": ["provided"]},
            "dependent": {"requires": ["provided"]},
        }
        result = evaluate_group_selection(
            allowed_refs=list(tags), selected_refs=list(tags), tags_for_ref=tags.get,
            base_tags=(), tag_rules=(), base_tag_counts=(), minimum=2, maximum=2,
        )
        self.assertFalse(result["selected_reachable"])

    def test_real_abyss_three_accessories_are_natural(self):
        decoded = (
            "23, 0, 1, 60| 2, 1054|| {61} {2} {4} {5} {60} {71} {74} {70} "
            "{14} {26} {43} {50} {1:[57 53]}|"
        )
        context = weapon_generation_context(decoded)
        group = context["groups"]["barrel_acc"]
        self.assertEqual((4, 4), (group["min"], group["max"]))
        self.assertEqual((3, 3), (group["effective_min"], group["effective_max"]))
        self.assertTrue(group["selected_terminal"])
        self.assertEqual("legal", validate_weapon_generation(decoded)["status"])

    def test_real_overdraw_and_empty_authoring_groups(self):
        cases = (
            ("11, 0, 1, 60| 2, 1|| {76} {75} {62} {63} {65}|", "barrel_acc", 3),
            ("8, 0, 1, 60| 2, 1|| {59} {51}|", "foregrip", 1),
            ("19, 0, 1, 60| 2, 1|| {1}|", "magazine_borg", 0),
            ("19, 0, 1, 60| 2, 1|| {19}|", "magazine_borg", 0),
        )
        for decoded, group_name, expected_count in cases:
            with self.subTest(decoded=decoded, group=group_name):
                group = weapon_generation_context(decoded)["groups"][group_name]
                self.assertEqual([expected_count], group["terminal_counts"])
                self.assertEqual(expected_count, group["effective_min"])
                self.assertEqual(expected_count, group["effective_max"])
                self.assertTrue(group["selected_terminal"])


if __name__ == "__main__":
    unittest.main()
