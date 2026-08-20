import unittest

from paladin_controller.app import PaladinApp


class SbrWorkflowTests(unittest.TestCase):
    def test_sbr_queries_are_not_in_automatic_monitoring_loop(self):
        self.assertFalse(any("SBR" in command for command in PaladinApp.POLL_COMMANDS))

    def test_sbr_shift_settle_time_is_ten_seconds(self):
        self.assertEqual(PaladinApp.SBR_SETTLE_MS, 10_000)


if __name__ == "__main__":
    unittest.main()
