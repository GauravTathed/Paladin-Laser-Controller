import unittest

from paladin_controller.protocol import ProtocolError
from paladin_controller.sbr import parse_sbr_all


class SbrParserTests(unittest.TestCase):
    def test_parses_spot_conditions_and_hours(self):
        snapshot = parse_sbr_all("4|2|2|1|999.5|4|12.3|0|0.0|2|8.0")
        self.assertEqual(snapshot.maximum_spots, 4)
        self.assertEqual(snapshot.spot(1).condition, "USED")
        self.assertEqual(snapshot.spot(2).condition, "IN USE")
        self.assertAlmostEqual(snapshot.spot(2).hours, 12.3)
        self.assertEqual(snapshot.spot(3).condition, "GOOD")
        self.assertEqual(snapshot.spot(4).condition, "BAD")

    def test_rejects_incomplete_spot_data(self):
        with self.assertRaises(ProtocolError):
            parse_sbr_all("4|2|2|0|0.0")


if __name__ == "__main__":
    unittest.main()

