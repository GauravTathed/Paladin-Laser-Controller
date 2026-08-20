import time
import unittest

from paladin_controller.app import DeviceSession


class DeviceSessionTests(unittest.TestCase):
    def setUp(self):
        self.session = DeviceSession()

    def tearDown(self):
        self.session.shutdown()

    def wait_for(self, results, count=1, timeout=2.0):
        deadline = time.monotonic() + timeout
        while len(results) < count and time.monotonic() < deadline:
            self.session.drain_callbacks()
            time.sleep(0.01)
        self.session.drain_callbacks()
        self.assertGreaterEqual(len(results), count)

    def test_simulator_connection_and_query_callbacks(self):
        results = []
        self.session.connect("SIMULATOR", 9600, lambda result, error: results.append((result, error)))
        self.wait_for(results)
        self.assertIsNone(results[0][1])
        self.assertTrue(self.session.connected)

        self.session.send("?STA", lambda result, error: results.append((result, error)))
        self.wait_for(results, count=2)
        self.assertIsNone(results[1][1])
        self.assertEqual(results[1][0].value, "11")

    def test_sbr_shift_closes_then_reopens_same_connection(self):
        results = []
        self.session.connect("SIMULATOR", 9600, lambda result, error: results.append((result, error)))
        self.wait_for(results)

        self.session.send_and_close("SHSBRTO=008", lambda result, error: results.append((result, error)), priority=0)
        self.wait_for(results, count=2)
        self.assertEqual(results[1][0].fault_code, 73)
        self.assertFalse(self.session.connected)

        self.session.reconnect(lambda result, error: results.append((result, error)))
        self.wait_for(results, count=3)
        self.assertIsNone(results[2][1])
        self.assertTrue(self.session.connected)

        self.session.send("?SPNSBR", lambda result, error: results.append((result, error)))
        self.wait_for(results, count=4)
        self.assertEqual(results[3][0].value, "8")


if __name__ == "__main__":
    unittest.main()
