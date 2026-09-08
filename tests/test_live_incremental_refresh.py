import copy
import unittest

from live.adapter import items_to_yaml, patch_live_yaml_items


class LiveIncrementalRefreshTests(unittest.TestCase):
    def setUp(self):
        self.old = "@U-old"
        self.yaml = items_to_yaml([
            {
                "ok": True, "container": "BackpackItems", "idx": 2,
                "serial": self.old, "handle": 12, "instance_id": 34,
                "stable_identity_supported": True,
            },
            {"ok": True, "container": "BankItems", "idx": 4, "serial": "@U-bank"},
        ])

    def test_live_item_token_is_preserved_beside_the_serial(self):
        node = self.yaml["state"]["inventory"]["items"]["backpack"]["slot_2"]
        self.assertEqual(12, node["_live_handle"])
        self.assertEqual(34, node["_live_instance_id"])
        self.assertIs(True, node["_live_identity_supported"])

    def test_apply_replaces_only_verified_slot(self):
        paths = patch_live_yaml_items(
            self.yaml,
            [{"container": "BackpackItems", "idx": 2, "serial": "@U-new"}],
            require_existing=True,
            expected_serials={("BackpackItems", 2): self.old},
        )
        self.assertEqual(
            [["state", "inventory", "items", "backpack", "slot_2"]], paths
        )
        self.assertEqual(
            "@U-new",
            self.yaml["state"]["inventory"]["items"]["backpack"]["slot_2"]["serial"],
        )
        self.assertEqual(
            "@U-bank",
            self.yaml["state"]["inventory"]["items"]["bank"]["slot_4"]["serial"],
        )

    def test_stale_apply_is_rejected_without_partial_mutation(self):
        before = copy.deepcopy(self.yaml)
        result = patch_live_yaml_items(
            self.yaml,
            [{"container": "BackpackItems", "idx": 2, "serial": "@U-new"}],
            require_existing=True,
            expected_serials={("BackpackItems", 2): "@U-not-current"},
        )
        self.assertIsNone(result)
        self.assertEqual(before, self.yaml)

    def test_batch_spawn_is_atomic_and_rejects_collisions(self):
        paths = patch_live_yaml_items(
            self.yaml,
            [
                {"container": "BackpackItems", "index": 3, "serial": "@U-a"},
                {"container": "BackpackItems", "index": 5, "serial": "@U-b"},
            ],
            require_existing=False,
        )
        self.assertEqual(2, len(paths))
        before = copy.deepcopy(self.yaml)
        result = patch_live_yaml_items(
            self.yaml,
            [
                {"container": "BackpackItems", "idx": 6, "serial": "@U-c"},
                {"container": "BackpackItems", "idx": 5, "serial": "@U-collision"},
            ],
            require_existing=False,
        )
        self.assertIsNone(result)
        self.assertEqual(before, self.yaml)


if __name__ == "__main__":
    unittest.main()
