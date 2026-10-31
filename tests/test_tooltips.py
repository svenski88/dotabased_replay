import unittest
from ui_helpers import tooltip_coordinates
from graph_view import proportional_advantage


class TooltipTests(unittest.TestCase):
    def test_pointer_on_right_monitor_is_not_clamped_to_primary(self):
        self.assertEqual(tooltip_coordinates((4100, 200), (300, 100), (3840, 0, 5760, 1080)), (4112, 212))

    def test_negative_origins_and_monitors_above_primary(self):
        self.assertEqual(tooltip_coordinates((-1600, 200), (300, 100), (-1920, 0, 0, 1080)), (-1588, 212))
        self.assertEqual(tooltip_coordinates((200, -1000), (300, 100), (0, -1080, 1920, 0)), (212, -988))

    def test_right_bottom_edges_flip_near_pointer_within_work_area(self):
        self.assertEqual(tooltip_coordinates((1900, 1020), (300, 150), (0, 0, 1920, 1040)), (1588, 858))
        x, y = tooltip_coordinates((-5, 1020), (300, 150), (-1920, 0, 0, 1040))
        self.assertEqual((x, y), (-317, 858))

    def test_advantage_percentages_preserve_unknown_and_zero_total(self):
        self.assertAlmostEqual(proportional_advantage({"radiant_net_worth": 60000, "dire_net_worth": 40000}, "net_worth"), .2)
        self.assertAlmostEqual(proportional_advantage({"radiant_xp": 40000, "dire_xp": 60000}, "xp"), -.2)
        for sample in ({}, {"radiant_xp": 0, "dire_xp": 0}, {"radiant_xp": None, "dire_xp": 2}):
            self.assertIsNone(proportional_advantage(sample, "xp"))


if __name__ == "__main__":
    unittest.main()
