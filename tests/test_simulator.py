import time
import unittest

from paladin_controller.sbr import parse_sbr_all
from paladin_controller.simulator import SimulatorTransport


class SimulatorTests(unittest.TestCase):
    def setUp(self):
        self.simulator = SimulatorTransport(delay=0)
        self.simulator.open()

    def send(self, command):
        self.simulator._last_write = time.monotonic() - 1
        return self.simulator.send(command)

    def test_start_open_close_stop_sequence(self):
        self.assertEqual(self.send("?STA").value, "11")
        self.assertTrue(self.send("L=1").ok)
        self.assertEqual(self.send("?STA").value, "8")
        self.assertTrue(self.send("S=1").ok)
        self.assertEqual(self.send("?S").value, "1")
        self.assertTrue(self.send("S=0").ok)
        self.assertTrue(self.send("L=0").ok)
        self.assertEqual(self.send("?STA").value, "11")

    def test_shutter_open_rejected_in_standby(self):
        response = self.send("S=1")
        self.assertEqual(response.fault_code, 130)

    def test_power_rejected_during_normal_operation(self):
        self.send("L=1")
        response = self.send("P=10")
        self.assertEqual(response.fault_code, 151)

    def test_unknown_command_returns_bad_format(self):
        self.assertEqual(self.send("UNKNOWN").fault_code, 77)

    def test_specific_sbr_shift_updates_current_and_conditions(self):
        self.assertEqual(self.send("?SPNSBR").value, "7")
        shift = self.send("SHSBRTO=008")
        self.assertEqual(shift.fault_code, 73)
        self.assertFalse(shift.ok)
        self.assertEqual(self.send("?SPNSBR").value, "8")
        self.assertEqual(self.send("?SBRST07").value, "1")
        self.assertEqual(self.send("?SBRST08").value, "4")

    def test_all_sbr_data_contains_every_spot(self):
        snapshot = parse_sbr_all(self.send("?SBRALL").value)
        self.assertEqual(len(snapshot.spots), 25)
        self.assertEqual(snapshot.spot(3).condition, "BAD")
        self.assertEqual(snapshot.spot(7).condition, "IN USE")

    def test_sbr_shift_rejects_bad_spot(self):
        self.assertEqual(self.send("SHSBRTO=003").fault_code, 96)

    def test_sbr_shift_rejects_undocumented_condition(self):
        self.assertEqual(self.send("SHSBRTO=001").fault_code, 96)


if __name__ == "__main__":
    unittest.main()
