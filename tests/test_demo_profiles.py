import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from profiles import get_demo_profiles, normalize_profile, validate_profile


class DemoProfileTests(unittest.TestCase):
    def test_five_distinct_examples_keep_metadata_after_round_trip(self):
        profiles = get_demo_profiles()
        self.assertEqual([item["demo_id"] for item in profiles],
                         ["pcb", "press", "food", "warehouse", "new_factory"])
        self.assertEqual(len({item["uid"] for item in profiles}), 5)
        for item in profiles:
            self.assertTrue(item["demo_is_example"])
            self.assertTrue(item["template_is_example"])
            self.assertIn("가상 예제", item["name"])
            self.assertTrue(item["demo_description"])
            self.assertGreaterEqual(len(item["demo_learning_points"]), 2)
            self.assertEqual(normalize_profile(item), item)

    def test_building_totals_and_representative_values_are_consistent(self):
        for item in get_demo_profiles():
            self.assertEqual(sum(row["gross_floor_area_m2"] for row in item["buildings"]),
                             item["gross_floor_area_m2"])
            self.assertEqual(sum(row["building_area_m2"] for row in item["buildings"]),
                             item["building_area_m2"])
            self.assertEqual(max(row["ground_floors"] for row in item["buildings"]),
                             item["ground_floors"])
            self.assertEqual(max(row["height_m"] for row in item["buildings"]), item["height_m"])
            self.assertTrue(item["equipment"])

    def test_unverified_products_do_not_claim_legal_classification(self):
        for item in get_demo_profiles():
            for field in ("hazardous_chemicals", "psm_confirmed", "dangerous_goods_facility",
                          "special_health_exam_target", "work_environment_measurement_target"):
                self.assertIsNone(item[field])
            for product in item["chemicals"]:
                self.assertIsNone(product["classification_verified"])
                self.assertIsNone(product["concentration_pct"])
            if item["chemicals"]:
                self.assertTrue(any("법적 분류가 미확인" in message
                                    for message in validate_profile(item)))

    def test_examples_are_fresh_copies_and_keep_specific_construction_data(self):
        first = get_demo_profiles()
        first[0]["buildings"][0]["name"] = "edited"
        first[0]["demo_learning_points"].append("edited")
        second = get_demo_profiles()
        self.assertNotEqual(second[0]["buildings"][0]["name"], "edited")
        self.assertNotIn("edited", second[0]["demo_learning_points"])
        self.assertEqual(second[-1]["construction_cost_krw"], 12000000000)
        self.assertEqual(second[-1]["excavation_depth_m"], 3)
        self.assertEqual(second[-1]["permit_status"], "공사 중")


if __name__ == "__main__":
    unittest.main()
