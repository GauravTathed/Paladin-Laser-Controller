import unittest

from paladin_controller.commands import COMMANDS, command_risk, search_commands


class CommandGuideTests(unittest.TestCase):
    def test_catalog_is_comprehensive(self):
        self.assertGreaterEqual(len(COMMANDS), 65)
        templates = {command.template for command in COMMANDS}
        for expected in {"?STA", "L=n", "S=n", "?KTALLS", "?SETTINGS", "GOON"}:
            self.assertIn(expected, templates)

    def test_plain_language_search(self):
        results = search_commands("shutter status")
        self.assertTrue(any(spec.template == "?S" for spec in results))

    def test_unknown_writes_default_to_service_risk(self):
        self.assertEqual(command_risk("?V"), "query")
        self.assertEqual(command_risk("S=0"), "operational")
        self.assertEqual(command_risk("SETVAN=029.0"), "service")
        self.assertEqual(command_risk("SOMETHING=1"), "service")


if __name__ == "__main__":
    unittest.main()

