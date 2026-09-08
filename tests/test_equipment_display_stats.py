import json
import unittest
from pathlib import Path

from core.equipment_display_stats import equipment_card_stats_from_serial


class EquipmentDisplayStatsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads(
            (Path(__file__).parents[1] / "item" / "item_name_index.json").read_text(encoding="utf-8")
        )

    def stats(self, item_type, serial):
        return equipment_card_stats_from_serial(serial, self.index, item_type)

    def test_four_equipment_families(self):
        self.assertEqual(
            {
                "damage": "15232",
                "radius": 520,
                "cooldown": 11,
                "charges": 2,
                "cryo_efficiency": 150,
            },
            self.stats("Grenade", "278, 0, 1, 60| 2, 371|| {7} {2} {245:[25 29 42 76 7]}|"),
        )
        self.assertEqual(
            {"capacity": 54895, "recharge_delay": 4.300000190734863, "recharge_rate": 6404},
            self.stats("Shield", "279, 0, 1, 60| 2, 1618|| {6} {2} {246:[22 30]} {248:16}|"),
        )
        self.assertEqual(
            {
                "healing": 9611,
                "instant_healing": 4806,
                "health_over_time": 4806,
                "cooldown": 8,
                "duration": 8,
                "charges": 2,
            },
            self.stats("Repkit", "285, 0, 1, 60| 2, 76|| {6} {2} {243:[103 100 56 97]}|"),
        )
        self.assertEqual(
            {
                "damage": "3151x2",
                "dps": 39389,
                "accuracy": 61,
                "fire_rate": 6.300000190734863,
                "magazine": 32,
                "cooldown": 49,
                "splash_radius": 236,
            },
            self.stats("Heavy Weapon", "273, 0, 1, 60| 2, 87|| {33} {14} {18} {16} {1:11} {21} {26} {28}|"),
        )

    def test_zero_segment_override_and_heavy_seed_fields(self):
        self.assertEqual(
            {"capacity": 0, "armor_segments": 0, "damage_reduction": 0},
            self.stats("Shield", "287,0,1,60| 2,1|| {8} {9} |"),
        )
        heavy = self.stats("Heavy Weapon", "273,0,1,60| 2,1|| {30} {14} {20} |")
        self.assertEqual((6, 50), (heavy["magazine"], heavy["cooldown"]))

    def test_bound_effect_rows_and_unique_overrides(self):
        repkit_base = self.stats("Repkit", "265,0,1,60| 2,1|| {5} {7} {243:105} |")
        repkit_unrelated = self.stats("Repkit", "265,0,1,60| 2,1|| {5} {7} {243:105} {243:63} |")
        self.assertEqual(repkit_base, repkit_unrelated)

        triple = self.stats("Repkit", "285,0,1,60| 2,1|| {7} {1} |")
        self.assertEqual((16019, 21, 10, 3), (triple["healing"], triple["cooldown"], triple["duration"], triple["charges"]))

        shield = self.stats("Shield", "321, 0, 1, 60| 2, 1356|| {4} {10} {246:[26 42]} {237:20}|")
        self.assertEqual(4, shield["armor_segments"])

        axe = self.stats("Grenade", "270, 0, 1, 60| 2, 4005|| {7} {10} {245:23} {6} {245:72}|")
        self.assertEqual((13, 2), (axe["cooldown"], axe["charges"]))

        splatoon = self.stats("Heavy Weapon", "282, 0, 1, 60| 2, 1703|| {1} {6} {10} {1:10} {2}|")
        self.assertEqual(("6041", 24166, 35), (splatoon["damage"], splatoon["dps"], splatoon["cooldown"]))

        cuckoo = self.stats(
            "Heavy Weapon",
            "282, 0, 1, 60| 2, 1417|| {24} {6} {9} {8} {11} {12} {20} {17} {4} {244:9}|",
        )
        self.assertEqual((6.900000095367432, 54808), (cuckoo["fire_rate"], cuckoo["dps"]))

        bismuth = self.stats("Grenade", "267,0,1,60| 2,1|| {20} {19} |")
        plain_jakobs = self.stats("Grenade", "267,0,1,60| 2,1|| {20} |")
        self.assertEqual(plain_jakobs, bismuth)

        loiter = self.stats("Heavy Weapon", "273,0,1,60| 2,1|| {36} {44} |")
        mandolin = self.stats("Heavy Weapon", "289,0,1,60| 2,1|| {1} {30} |")
        disc_jockey = self.stats(
            "Heavy Weapon",
            "275, 0, 1, 60| 2, 1224|| {31} {11} {13} {12} {30}|",
        )
        self.assertEqual(360, loiter["splash_radius"])
        self.assertEqual(2, mandolin["magazine"])
        self.assertEqual(42, disc_jockey["cooldown"])

    def test_verified_v4_heavy_regressions(self):
        # Ground truth: equipment_display_stats_20260808_125231.txt, verify=ok.
        sea_eagle = self.stats(
            "Heavy Weapon",
            "282, 0, 1, 60| 2, 3075|| {24} {6} {10} {8} {9} {1:11} {12} {17} {19} {5}|",
        )
        self.assertEqual(("3927", 27143, 120), (
            sea_eagle["damage"], sea_eagle["dps"], sea_eagle["splash_radius"],
        ))

        loiter_damage = self.stats(
            "Heavy Weapon",
            "273, 0, 1, 60| 2, 1973|| {45} {14} {15} {19} {44}|",
        )
        loiter_radius = self.stats(
            "Heavy Weapon",
            "273, 0, 1, 60| 2, 1973|| {45} {14} {16} {19} {44}|",
        )
        self.assertEqual(("66249", 39750, 360), (
            loiter_damage["damage"], loiter_damage["dps"], loiter_damage["splash_radius"],
        ))
        self.assertEqual(598, loiter_radius["splash_radius"])

        jetsetter = self.stats(
            "Heavy Weapon",
            "275, 0, 1, 60| 2, 931|| {36} {11} {13} {35}|",
        )
        self.assertEqual(("7140x3", 7), (jetsetter["damage"], jetsetter["magazine"]))

        flak = self.stats(
            "Heavy Weapon",
            "282, 0, 1, 60| 2, 1195|| {31} {6} {7} {11} {30} {18}|",
        )
        self.assertNotIn("splash_radius", flak)

    def test_repkit_cooldown_uses_card_rounding(self):
        rounded_up = self.stats(
            "Repkit",
            "261, 0, 1, 60| 2, 3692|| {4} {7} {243:[103 98 59 89 39]}|",
        )
        half_down = self.stats(
            "Repkit",
            "266, 0, 1, 60| 2, 2470|| {5} {7} {243:[106 99]} {6} {243:83}|",
        )
        reduction_half = self.stats(
            "Repkit",
            "285, 0, 1, 60| 2, 3572|| {7} {2} {243:[103 98]} {1} {243:97}|",
        )
        self.assertEqual((12, 31, 10), (
            rounded_up["cooldown"],
            half_down["cooldown"],
            reduction_half["cooldown"],
        ))


if __name__ == "__main__":
    unittest.main()
