"""Thread-safe serial transport with the timing required by the Paladin manual."""

from __future__ import annotations

import time
from typing import Any

from .protocol import MIN_COMMAND_INTERVAL_SECONDS, ParsedResponse, ProtocolError, frame_command, normalize_command, parse_response


class TransportError(RuntimeError):
    pass


def available_serial_ports() -> list[str]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return sorted(port.device for port in list_ports.comports())


class SerialTransport:
    """Owns one pyserial connection; callers should use it from one worker thread."""

    def __init__(self, port: str, baudrate: int = 9600, timeout: float = 2.5):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial: Any | None = None
        self._last_write = 0.0

    @property
    def is_open(self) -> bool:
        return bool(self._serial and self._serial.is_open)

    def open(self) -> None:
        try:
            import serial
        except ImportError as exc:
            raise TransportError("pyserial is not installed. Run: python -m pip install -e .") from exc
        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.10,
                write_timeout=1.0,
            )
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
        except Exception as exc:
            self._serial = None
            raise TransportError(f"Could not open {self.port}: {exc}") from exc

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None

    def _respect_interval(self) -> None:
        delay = MIN_COMMAND_INTERVAL_SECONDS - (time.monotonic() - self._last_write)
        if delay > 0:
            time.sleep(delay)

    def send(self, command: str) -> ParsedResponse:
        if not self.is_open:
            raise TransportError("Serial port is not connected")
        normalized = normalize_command(command)
        self._respect_interval()
        assert self._serial is not None
        try:
            self._serial.write(frame_command(normalized))
            self._serial.flush()
            self._last_write = time.monotonic()
            if normalized == "~":
                return ParsedResponse("", "Communication buffers reset", 0, "OK")
            raw = self._read_reply()
            return parse_response(raw, normalized)
        except ProtocolError:
            raise
        except Exception as exc:
            raise TransportError(f"Serial communication failed: {exc}") from exc

    def _read_reply(self) -> bytes:
        assert self._serial is not None
        deadline = time.monotonic() + self.timeout
        received = bytearray()
        prompt_seen_at: float | None = None
        while time.monotonic() < deadline:
            waiting = max(int(getattr(self._serial, "in_waiting", 0)), 1)
            chunk = self._serial.read(waiting)
            if chunk:
                received.extend(chunk)
                if b";" in received:
                    break
                if b"Paladin>" in received:
                    prompt_seen_at = prompt_seen_at or time.monotonic()
            elif prompt_seen_at is not None and time.monotonic() - prompt_seen_at >= 0.10:
                break
        if not received:
            raise TransportError(f"No reply received within {self.timeout:.1f} s")
        return bytes(received)

