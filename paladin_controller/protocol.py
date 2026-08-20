"""Paladin RS-232 framing, parsing, and human-readable status values."""

from __future__ import annotations

from dataclasses import dataclass
import re


MIN_COMMAND_INTERVAL_SECONDS = 0.220

OPERATING_STATUSES = {
    0: "Ramp-up oscillator",
    1: "Equilibration oscillator",
    2: "Checking IR oscillator",
    3: "Reserved state 3",
    4: "Reserved state 4",
    5: "Reserved state 5",
    6: "Reserved state 6",
    7: "Ramp-up light loop",
    8: "Normal operation",
    9: "Reserved state 9",
    10: "Ramp-down oscillator",
    11: "Standby",
    12: "Warm-up",
    13: "Alignment mode wait",
    14: "Alignment mode ready",
}

SYSTEM_MESSAGES = {
    0: "OK",
    73: "Undocumented controller status 73",
    77: "Bad data format",
    78: "Range error",
    96: "SBR shifting not allowed",
    118: "Adjustment is at lower limit",
    119: "Adjustment is at upper limit",
    120: "Allowed only in standby",
    123: "UV power is out of range",
    125: "Time to shift to next spot",
    126: "Last spot in use",
    130: "Allowed only in normal operation",
    131: "UV power is not reliable in alignment mode",
    132: "Alignment mode not available",
    134: "Output power OK; power headroom below 5%",
    135: "Chiller fault",
    136: "Head humidity too high",
    140: "Internal slave fault",
    143: "Internal master fault",
    150: "Laser head cover is open",
    151: "Allowed only in standby/warm-up",
    152: "SBR fault",
    156: "Laser diodes unintentionally enabled",
    157: "Watchdog does not work",
    159: "Beam shutter always open",
    160: "Beam shutter communication fault",
    161: "Beam shutter defect or wrong status",
    162: "Flow-control fault in security loop",
    163: "Plausibility fault in security loop",
    164: "Flash-memory fault",
    165: "Laser head not supported",
    166: "Laser/laser-diode mismatch",
    167: "Laser-diode wavelength mismatch",
    168: "Battery is low",
    169: "Baud-rate change not supported",
    170: "Wrong baud rate",
    171: "Common Service Interface not enabled",
    172: "Amplifier diodes inconsistent",
    173: "Laser warm-up too long",
    174: "Laser ramp-up too long",
    175: "Power-supply/laser-diode count mismatch",
    176: "SBR temperature above limit",
    177: "Time to shift to next SBR spot",
    178: "Shifter in use",
    179: "Last SBR spot in use",
    180: "Check ignored",
    181: "CDA flow off",
    182: "Head lifetime warning",
    183: "Laser-diode lifetime warning",
    184: "Power-supply lifetime warning",
    186: "SHG optimization due",
    190: "SBR time limit",
    191: "Not allowed to set THG/FHG temperature",
    193: "Shifter alignment done",
    194: "Shifter out of range",
    201: "Shifter fault",
    202: "Shifter loop open",
    203: "Shifter at limit",
    204: "Shifter operation fault",
    205: "Shifter power-amplifier fault",
    206: "Battery defect",
    208: "Shifter operation fault",
    219: "Spot time limit",
    221: "Plausibility check incorrect",
}


class ProtocolError(ValueError):
    """Raised when a command or response cannot be framed safely."""


@dataclass(frozen=True)
class ParsedResponse:
    raw: str
    value: str
    fault_code: int | None
    fault_message: str

    @property
    def ok(self) -> bool:
        return self.fault_code in (None, 0)


@dataclass(frozen=True)
class FaultHistoryRecord:
    code: int
    head_hours: float
    message: str


def normalize_command(command: str) -> str:
    """Return one ASCII Paladin command without its line terminator."""
    cleaned = command.strip().rstrip(";\r\n").strip()
    if not cleaned:
        raise ProtocolError("Command is empty")
    if any(char in cleaned for char in "\r\n;"):
        raise ProtocolError("Send one command at a time; embedded terminators are not allowed")
    try:
        cleaned.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ProtocolError("Commands must contain ASCII characters only") from exc
    return cleaned


def frame_command(command: str) -> bytes:
    """Frame a command for the controller (CR terminated, except reset '~')."""
    cleaned = normalize_command(command)
    return cleaned.encode("ascii") if cleaned == "~" else (cleaned + "\r").encode("ascii")


def parse_response(raw: str | bytes, command: str | None = None) -> ParsedResponse:
    """Parse default-mode ``value:fault;`` responses and tolerate terminal mode."""
    if isinstance(raw, bytes):
        text = raw.decode("latin-1", errors="replace")
    else:
        text = raw
    original = text
    text = text.replace("\x00", "").strip()
    if not text:
        raise ProtocolError("Controller returned no response")

    # Remove prompt-only lines from terminal-mode responses.
    lines = [line.strip() for line in re.split(r"[\r\n]+", text) if line.strip()]
    lines = [line for line in lines if not line.lower().endswith("paladin>")]
    compact = " ".join(lines).strip().rstrip(";").strip()

    if command:
        normalized = normalize_command(command)
        echo_prefix = normalized + ":"
        if compact.upper().startswith(echo_prefix.upper()):
            compact = compact[len(echo_prefix) :]

    value = compact
    fault_code: int | None = None
    fault_message = "No numeric status returned"
    if ":" in compact:
        candidate_value, candidate_fault = compact.rsplit(":", 1)
        if re.fullmatch(r"[-+]?\d+", candidate_fault.strip()):
            value = candidate_value.strip()
            fault_code = int(candidate_fault)
            fault_message = SYSTEM_MESSAGES.get(fault_code, f"Controller message {fault_code}")
    return ParsedResponse(original, value, fault_code, fault_message)


def status_name(value: str | int) -> str:
    try:
        code = int(str(value).strip())
    except ValueError:
        return f"Unknown ({value})"
    return OPERATING_STATUSES.get(code, f"Unknown state {code}")


def parse_fault_history(value: str) -> list[FaultHistoryRecord]:
    """Parse ``?LF`` pairs of fault number and related laser-head hours."""
    fields = [field.strip() for field in value.split("|") if field.strip()]
    if not fields or fields == ["0"]:
        return []
    if len(fields) % 2:
        raise ProtocolError("Fault history has an odd number of fields")
    records: list[FaultHistoryRecord] = []
    for index in range(0, len(fields), 2):
        try:
            code = int(fields[index])
            hours = float(fields[index + 1])
        except ValueError as exc:
            raise ProtocolError("Fault history contains a non-numeric field") from exc
        records.append(FaultHistoryRecord(code, hours, SYSTEM_MESSAGES.get(code, f"Controller message {code}")))
    return records
