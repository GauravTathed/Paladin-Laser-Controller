import unittest

from paladin_controller.protocol import ProtocolError, frame_command, parse_fault_history, parse_response, status_name


class ProtocolTests(unittest.TestCase):
    def test_frames_regular_command_with_carriage_return(self):
        self.assertEqual(frame_command("?V;"), b"?V\r")

    def test_reset_has_no_terminator(self):
        self.assertEqual(frame_command("~"), b"~")

    def test_rejects_multiple_commands(self):
        with self.assertRaises(ProtocolError):
            frame_command("?V;?STA")

    def test_parses_default_mode(self):
        response = parse_response("3.0000:0;", "?V")
        self.assertTrue(response.ok)
        self.assertEqual(response.value, "3.0000")
        self.assertEqual(response.fault_code, 0)

    def test_parses_echo_protocol(self):
        response = parse_response("?V:3.0000:0;", "?V")
        self.assertEqual(response.value, "3.0000")
        self.assertEqual(response.fault_code, 0)

    def test_decodes_controller_message(self):
        response = parse_response(":151;", "P=12")
        self.assertFalse(response.ok)
        self.assertEqual(response.fault_message, "Allowed only in standby/warm-up")

    def test_status_73_is_explicitly_undocumented(self):
        response = parse_response("8:73;", "SHSBRTO=008")
        self.assertEqual(response.fault_code, 73)
        self.assertEqual(response.fault_message, "Undocumented controller status 73")

    def test_decodes_operating_state(self):
        self.assertEqual(status_name("8"), "Normal operation")
        self.assertEqual(status_name(11), "Standby")

    def test_parses_fault_history_pairs(self):
        records = parse_fault_history("177|1713.04|0|0")
        self.assertEqual(records[0].code, 177)
        self.assertEqual(records[0].message, "Time to shift to next SBR spot")
        self.assertAlmostEqual(records[0].head_hours, 1713.04)

    def test_empty_fault_history(self):
        self.assertEqual(parse_fault_history("0"), [])



if __name__ == "__main__":
    unittest.main()
