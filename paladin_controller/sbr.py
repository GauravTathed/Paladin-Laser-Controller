"""Parsing and presentation helpers for Paladin SBR spot data."""

from __future__ import annotations

from dataclasses import dataclass

from .protocol import ProtocolError


SBR_CONDITIONS = {
    0: "GOOD",
    1: "USED",
    2: "BAD",
    4: "IN USE",
}


@dataclass(frozen=True)
class SbrSpot:
    number: int
    status: int
    hours: float

    @property
    def condition(self) -> str:
        return SBR_CONDITIONS.get(self.status, f"UNKNOWN ({self.status})")


@dataclass(frozen=True)
class SbrSnapshot:
    maximum_spots: int
    columns: int
    rows: int
    spots: tuple[SbrSpot, ...]

    def spot(self, number: int) -> SbrSpot | None:
        return next((spot for spot in self.spots if spot.number == number), None)


def parse_sbr_all(value: str) -> SbrSnapshot:
    """Parse ``?SBRALL``: max, X, Y, followed by status/hour pairs."""
    fields = [field.strip() for field in value.split("|") if field.strip()]
    if len(fields) < 3:
        raise ProtocolError("SBR data is missing its max/X/Y header")
    try:
        maximum_spots, columns, rows = (int(fields[0]), int(fields[1]), int(fields[2]))
    except ValueError as exc:
        raise ProtocolError("SBR max/X/Y values must be integers") from exc
    payload = fields[3:]
    expected_spots = columns * rows
    if expected_spots <= 0 or maximum_spots <= 0:
        raise ProtocolError("SBR geometry must contain at least one spot")
    if len(payload) < expected_spots * 2:
        raise ProtocolError(f"SBR data contains {len(payload) // 2} spots; expected {expected_spots}")
    spots: list[SbrSpot] = []
    for number in range(1, expected_spots + 1):
        offset = (number - 1) * 2
        try:
            status = int(payload[offset])
            hours = float(payload[offset + 1])
        except ValueError as exc:
            raise ProtocolError(f"SBR spot {number} has invalid status or hours") from exc
        spots.append(SbrSpot(number, status, hours))
    return SbrSnapshot(maximum_spots, columns, rows, tuple(spots))

