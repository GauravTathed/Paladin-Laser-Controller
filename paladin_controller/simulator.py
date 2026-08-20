"""Small behavioral simulator for UI practice and automated tests."""

from __future__ import annotations

import re
import time

from .protocol import MIN_COMMAND_INTERVAL_SECONDS, ParsedResponse, normalize_command, parse_response


class SimulatorTransport:
    port = "SIMULATOR"

    def __init__(self, delay: float = 0.02):
        self.delay = delay
        self.is_open = False
        self.warmup_ready = 1
        self.front_panel = 1
        self.laser_on = 0
        self.shutter_open = 0
        self.status = 11
        self.power = 0.0
        self.set_power = 12.0
        self.service_mode = 1
        self.warning = 0
        self.fault_history = "0|0"
        self.sbr_maximum_spots = 25
        self.sbr_columns = 5
        self.sbr_rows = 5
        self.sbr_limit = 1000.0
        self.current_sbr_spot = 7
        self.sbr_spots = {number: {"status": 0, "hours": 0.0} for number in range(1, 26)}
        self.sbr_spots[1] = {"status": 3, "hours": 1985.5}
        self.sbr_spots[2] = {"status": 1, "hours": 742.8}
        self.sbr_spots[3] = {"status": 2, "hours": 81.2}
        self.sbr_spots[self.current_sbr_spot] = {"status": 4, "hours": 12.4}
        self._last_write = 0.0

    def open(self) -> None:
        self.is_open = True

    def close(self) -> None:
        self.is_open = False

    def send(self, command: str) -> ParsedResponse:
        if not self.is_open:
            raise RuntimeError("Simulator is not connected")
        command = normalize_command(command)
        wait = MIN_COMMAND_INTERVAL_SECONDS - (time.monotonic() - self._last_write)
        if wait > 0:
            time.sleep(wait)
        if self.delay:
            time.sleep(self.delay)
        self._last_write = time.monotonic()
        if command == "~":
            return ParsedResponse("", "Communication buffers reset", 0, "OK")
        value, fault = self._handle(command.upper())
        return parse_response(f"{value}:{fault};", command)

    def _handle(self, command: str) -> tuple[str, int]:
        query_values = {
            ">=0": "0",
            "?W": str(self.warmup_ready),
            "?FP": str(self.front_panel),
            "?L": str(self.laser_on),
            "?P": f"{self.power:.2f}",
            "?SP": f"{self.set_power:.2f}",
            "?S": str(self.shutter_open),
            "?V": "3.0000-SIM",
            "?LT": "Paladin Scan (simulated)",
            "?STA": str(self.status),
            "?LF": self.fault_history,
            "?SM": str(self.service_mode),
            "?EMBS": "1" if self.shutter_open else "0",
            "?WR": str(self.warning),
            "?CIP": "42.5" if self.laser_on else "0.0",
            "?CIPA": "40.8" if self.laser_on else "0.0",
            "?SCIP": "45.0",
            "?SCIPA": "43.0",
            "?CM": "0",
            "?DBL": "1",
            "?TF": "0",
            "?MAINT": "0",
            "?AM": "1" if self.status in (13, 14) else "0",
            "?SPHSBR": f"{self.sbr_spots[self.current_sbr_spot]['hours']:.2f}",
            "?SPNSBR": str(self.current_sbr_spot),
            "?SBRWR": "0",
            "?SBRMAX": str(self.sbr_maximum_spots),
            "?SBRLIM": f"{self.sbr_limit:.1f}",
            "?SBRTLIM": "65.0",
            "?LL": "10.0",
            "?HL": "14.0",
            "?FL": "8.0",
            "?PRO": "12.7",
            "?IRO": "47.2",
            "?AP": "0",
            "?APIR": "0",
            "?HWF": "0",
        }
        if command in query_values:
            return query_values[command], 0
        if command.startswith("?SN"):
            return {"?SN0": "SIM-HEAD-001", "?SN1": "SIM-OSC-001", "?SN3": "SIM-AMP-001", "?SN9": "SIM-PS-001"}.get(command, ""), 0
        if command.startswith("?OPH"):
            return "1234.5", 0
        if command.startswith("?DT"):
            return "24.8" if command == "?DT1" else "25.1", 0
        if command.startswith("?ST"):
            return "29.0", 0
        if command.startswith("?HT"):
            return "31.2", 0
        if re.fullmatch(r"\?T[01257]", command):
            return "29.1", 0
        if command.startswith("?SWT"):
            return "0", 0
        if command.startswith("?SBRH"):
            try:
                number = int(command.removeprefix("?SBRH"))
                return f"{self.sbr_spots[number]['hours']:.2f}", 0
            except (ValueError, KeyError):
                return "", 78
        if command.startswith("?SBRST"):
            try:
                number = int(command.removeprefix("?SBRST"))
                return str(self.sbr_spots[number]["status"]), 0
            except (ValueError, KeyError):
                return "", 78
        if command == "?SBRALL":
            payload = [str(self.sbr_maximum_spots), str(self.sbr_columns), str(self.sbr_rows)]
            for number in range(1, self.sbr_columns * self.sbr_rows + 1):
                payload.extend((str(self.sbr_spots[number]["status"]), f"{self.sbr_spots[number]['hours']:.2f}"))
            return "|".join(payload), 0
        if command == "?KTALLS":
            return "SIM-HEAD-001|SIM-PS-001|SIM-OSC-001|SIM-AMP-001|3.0000-SIM|24.8|25.1|29.1|29.0|29.0|150.0|31.0", 0
        if command == "?SETTINGS":
            return "Paladin Scan (simulated)|24.0|24.0|29.0|29.0|29.0|150.0|45.0|43.0|12.0", 0
        if command.startswith("FP=") and command[-1:] in {"0", "1"}:
            self.front_panel = int(command[-1])
            return str(self.front_panel), 0
        if command == "L=1":
            if self.status != 11:
                return "", 120
            self.laser_on, self.status, self.power = 1, 8, self.set_power
            return "1", 0
        if command == "L=0":
            self.shutter_open, self.laser_on, self.status, self.power = 0, 0, 11, 0.0
            return "0", 0
        if command == "S=1":
            if self.status not in (8, 14):
                return "0", 130
            self.shutter_open = 1
            return "1", 0
        if command == "S=0":
            self.shutter_open = 0
            return "0", 0
        if command.startswith("P="):
            if self.status not in (11, 12):
                return "", 151
            try:
                value = float(command.split("=", 1)[1])
            except ValueError:
                return "", 77
            if not 0 <= value <= 25:
                return "", 78
            self.set_power = value
            return f"{value:.2f}", 0
        if command.startswith("SM=") and command[-1:] in {"0", "1"}:
            if self.status not in (11, 12):
                return "", 151
            self.service_mode = int(command[-1])
            return str(self.service_mode), 0
        shift_to = re.fullmatch(r"SHSBRTO=([01])(\d{2})", command)
        if shift_to:
            return self._shift_sbr(int(shift_to.group(2)), int(shift_to.group(1)))
        shift_next = re.fullmatch(r"SHSBR([01])", command)
        if shift_next:
            candidates = [
                number for number, data in self.sbr_spots.items()
                if data["status"] == 0 or (data["status"] == 1 and data["hours"] < self.sbr_limit)
            ]
            if not candidates:
                return "", 126
            return self._shift_sbr(candidates[0], int(shift_next.group(1)))
        reset_status = re.fullmatch(r"SBRRSST=(\d{2})", command)
        if reset_status:
            number = int(reset_status.group(1))
            if number not in self.sbr_spots:
                return "", 78
            if self.sbr_spots[number]["status"] == 2:
                self.sbr_spots[number]["status"] = 1
            return str(number), 0
        if command in {"CF", "CWR", "SBRCWR"}:
            self.fault_history, self.warning = "0|0", 0
            return "0", 0
        if command.startswith("D=") or command.startswith("NP="):
            return command.rsplit("=", 1)[-1], 0
        return "", 77

    def _shift_sbr(self, target: int, mark_current: int) -> tuple[str, int]:
        if target not in self.sbr_spots:
            return "", 78
        if target == self.current_sbr_spot:
            return "", 96
        target_data = self.sbr_spots[target]
        if target_data["status"] not in (0, 1):
            return "", 96
        if target_data["status"] == 1 and target_data["hours"] >= self.sbr_limit:
            return "", 96
        self.sbr_spots[self.current_sbr_spot]["status"] = 1 if mark_current == 0 else 2
        self.current_sbr_spot = target
        self.sbr_spots[target]["status"] = 4
        # The connected controller has been observed completing the physical
        # move while returning undocumented status 73. Simulate that response
        # so the UI's no-retry/manual-verification path remains covered.
        return str(target), 73
