import copy
import unittest

from core import b_encoder, bl4_functions, decoder_logic, serial_inspect


LV1_SERIAL = "@Ugr$lG7-8sL(4z`<KALPY4GrpidjS"
OFFICIAL_LV1_WEAPON = "@Uga`wSaA`KY24ax-g-%`LcN_jSr{#0{_gr^Zs7P(94yqO^C+Zvm"
UNKNOWN_VALID_SERIAL = "@Ugv?-o2`+&o!bFRpK^3Y/hf36<h765C{Y1q?wM0!S3@Q&Q73vf!7it{>"
UNKNOWN_BAD_SERIALS = (
    "@Uge9B?m/$)o!oXdiNkyuCZ$R-/18UzX0",
    "@Ugr$xKm/$!m!X=r/qY8CCnru=H4eETO0",
)


class LevelOneHeaderTests(unittest.TestCase):
    def setUp(self):
        self.decoded, _, error = decoder_logic.decode_serial_to_string(LV1_SERIAL)
        self.assertIsNone(error)

    def test_implicit_level_one_keeps_seed(self):
        header = bl4_functions.parse_decoded_item_header(self.decoded)
        self.assertEqual(1, header["level"])
        self.assertEqual(2932, header["seed"])
        self.assertTrue(header["implicit_level_one"])

        encoded, error = b_encoder.encode_to_base85(self.decoded)
        self.assertFalse(error)
        self.assertEqual(LV1_SERIAL, encoded)

    def test_level_update_inserts_marker_without_overwriting_seed(self):
        updated = bl4_functions.update_level_in_decoded_str(self.decoded, 60)
        header = bl4_functions.parse_decoded_item_header(updated)
        self.assertEqual(60, header["level"])
        self.assertEqual(2932, header["seed"])
        self.assertFalse(header["implicit_level_one"])

    def test_implicit_level_one_weapon_stats_do_not_use_seed_as_level(self):
        report = serial_inspect.inspect_serial(OFFICIAL_LV1_WEAPON, "en-US")
        self.assertEqual((1, 435, True), (
            report["level"], report["seed"], report["implicit_level_one"],
        ))
        self.assertEqual("13", report["weapon_stats"]["damage"])
        self.assertEqual(44, report["weapon_stats"]["dps"])

    def test_item_loading_and_sync_use_default_level_one(self):
        data = {
            "state": {
                "experience": [{"type": "Character", "level": 60}],
                "inventory": {"items": {"backpack": {"slot_0": {"serial": LV1_SERIAL}}}},
            }
        }
        items = bl4_functions.process_and_load_items(data)
        self.assertEqual(1, items[0]["level"])

        synced = copy.deepcopy(data)
        self.assertEqual((1, 0), bl4_functions.sync_inventory_item_levels(synced)[:2])
        serial = synced["state"]["inventory"]["items"]["backpack"]["slot_0"]["serial"]
        decoded, _, error = decoder_logic.decode_serial_to_string(serial)
        self.assertIsNone(error)
        header = bl4_functions.parse_decoded_item_header(decoded)
        self.assertEqual(60, header["level"])
        self.assertEqual(2932, header["seed"])

    def test_sync_skips_unknown_item_list_and_preserves_integer_paths(self):
        unknown_serials = [UNKNOWN_VALID_SERIAL, *UNKNOWN_BAD_SERIALS]
        data = {
            "state": {
                "experience": [{"type": "Character", "level": 60}],
                "inventory": {"items": {"backpack": {
                    "slot_0": {"serial": LV1_SERIAL},
                    "unknown_items": [{"serial": serial} for serial in unknown_serials],
                }}},
            }
        }

        unknown_path = next(
            path for path, _item in bl4_functions._walk_for_serials(data, [])
            if "unknown_items" in path
        )
        self.assertIsInstance(unknown_path[-1], int)

        self.assertEqual((1, 0), bl4_functions.sync_inventory_item_levels(data)[:2])
        self.assertEqual(
            unknown_serials,
            [item["serial"] for item in data["state"]["inventory"]["items"]["backpack"]["unknown_items"]],
        )


if __name__ == "__main__":
    unittest.main()
