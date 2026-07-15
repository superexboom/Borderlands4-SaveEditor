import copy
import unittest

from core import bl4_functions, unlock_logic
from core.unlock_data import (
    VAULT_CARD_PURCHASES,
    VAULT_CARD_REWARD_UNLOCKABLES,
    VAULT_CARD_TOKENS,
)


class ProfileVaultCardTest(unittest.TestCase):
    def test_profile_currency_apply_does_not_create_character_state(self):
        currencies = {card["currency_key"]: 0 for card in VAULT_CARD_TOKENS}
        profile = {"domains": {"local": {"shared": {"currencies": currencies}}}}
        paths = bl4_functions.find_currency_paths(profile)
        first_key = VAULT_CARD_TOKENS[0]["currency_key"]

        result = bl4_functions.apply_character_and_currency_changes(
            {first_key: "123"}, profile, paths
        )

        self.assertTrue(result)
        self.assertEqual(123, currencies[first_key])
        self.assertNotIn("experience", profile)
        self.assertNotIn("state", profile)

    def test_character_level_keeps_progress_points_in_sync(self):
        save = {
            "state": {
                "experience": [
                    {"type": "Character", "level": 1, "points": 0},
                    {"type": "Specialization", "level": 1, "points": 0},
                ]
            },
            "progression": {"point_pools": {"characterprogresspoints": 0}},
        }
        data = {
            "角色等级": "42",
            "角色经验值": "1000",
            "专精等级": "2",
            "专精点数": "50",
        }

        self.assertTrue(bl4_functions.apply_character_and_currency_changes(data, save, {}))
        self.assertEqual(41, save["progression"]["point_pools"]["characterprogresspoints"])

    def test_vault_card_reward_unlock_is_additive(self):
        if not VAULT_CARD_PURCHASES or not VAULT_CARD_REWARD_UNLOCKABLES:
            self.skipTest("generated Vault Card reward data is unavailable")

        profile = {
            "domains": {"local": {"shared": {}, "unlockables": {}}},
            "oak.ui.dlc_data": {"ui_dlc_data": {"vaultcard_purchases": ["Existing.Entry"]}},
        }
        original = copy.deepcopy(profile)

        unlock_logic.unlock_all_vault_card_rewards(profile)

        purchases = profile["oak.ui.dlc_data"]["ui_dlc_data"]["vaultcard_purchases"]
        self.assertIn("Existing.Entry", purchases)
        self.assertTrue(set(VAULT_CARD_PURCHASES).issubset(purchases))
        self.assertEqual(len(purchases), len({entry.lower() for entry in purchases}))
        self.assertEqual(
            original["domains"]["local"]["shared"],
            profile["domains"]["local"]["shared"],
        )
        for namespace, expected in VAULT_CARD_REWARD_UNLOCKABLES.items():
            actual = profile["domains"]["local"]["unlockables"][namespace]["entries"]
            self.assertTrue(set(expected).issubset(actual))

    def test_uvhm_unlock_preserves_current_level(self):
        save = {"globals": {
            "highest_unlocked_vault_hunter_level": 7,
            "vault_hunter_level": 7,
        }}

        unlock_logic.unlock_postgame(save)

        self.assertEqual(7, save["globals"]["highest_unlocked_vault_hunter_level"])
        self.assertEqual(7, save["globals"]["vault_hunter_level"])

    def test_refill_ammo_preserves_unknown_ammo_types(self):
        save = {"state": {"ammo": {"future_dlc_ammo": 4, "pistol": 1}}}

        unlock_logic.max_ammo(save)

        self.assertEqual(4, save["state"]["ammo"]["future_dlc_ammo"])
        self.assertEqual(900, save["state"]["ammo"]["pistol"])


if __name__ == "__main__":
    unittest.main()
