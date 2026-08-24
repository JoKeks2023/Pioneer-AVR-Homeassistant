"""Pioneer AVR command encoding and response parsing."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from .const import SOURCES, VOLUME_MAX, VOLUME_MIN


class ProtocolError(ValueError):
    """Raised when the receiver returns an invalid protocol value."""


class ResponseKind(StrEnum):
    """Kinds of state response understood by this integration."""

    POWER = "power"
    VOLUME = "volume"
    MUTE = "mute"
    SOURCE = "source"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ReceiverState:
    """Current main-zone receiver state."""

    power: bool | None = None
    volume_raw: int | None = None
    muted: bool | None = None
    source_code: str | None = None

    @property
    def volume_level(self) -> float | None:
        """Return the Home Assistant volume level."""
        if self.volume_raw is None:
            return None
        return self.volume_raw / VOLUME_MAX

    @property
    def source(self) -> str | None:
        """Return the friendly source name."""
        if self.source_code is None:
            return None
        return SOURCES.get(self.source_code, f"Input {self.source_code}")


@dataclass(frozen=True, slots=True)
class ParsedResponse:
    """A parsed receiver response."""

    kind: ResponseKind
    value: bool | int | str | None
    raw: str


def encode_command(command: str) -> bytes:
    """Encode a Pioneer command for the wire."""
    command = command.strip("\r\n")
    if not command or not command.isascii():
        raise ProtocolError("command must be non-empty ASCII")
    return command.encode("ascii") + b"\r"


def parse_response(raw: str) -> ParsedResponse:
    """Parse one response line."""
    line = raw.strip("\r\n")
    if line.startswith("PWR"):
        value = line[3:]
        if value == "0":
            return ParsedResponse(ResponseKind.POWER, True, line)
        if value in {"1", "2"}:
            return ParsedResponse(ResponseKind.POWER, False, line)
        raise ProtocolError(f"invalid power response: {line!r}")

    if line.startswith("VOL"):
        value = line[3:]
        if not value.isdigit():
            raise ProtocolError(f"invalid volume response: {line!r}")
        volume = int(value)
        if not VOLUME_MIN <= volume <= VOLUME_MAX:
            raise ProtocolError(f"volume outside VSX-827 range: {volume}")
        return ParsedResponse(ResponseKind.VOLUME, volume, line)

    if line.startswith("MUT"):
        value = line[3:]
        if value == "0":
            return ParsedResponse(ResponseKind.MUTE, True, line)
        if value == "1":
            return ParsedResponse(ResponseKind.MUTE, False, line)
        raise ProtocolError(f"invalid mute response: {line!r}")

    if line.startswith("FN"):
        value = line[2:]
        if len(value) != 2 or not value.isdigit():
            raise ProtocolError(f"invalid source response: {line!r}")
        return ParsedResponse(ResponseKind.SOURCE, value, line)

    return ParsedResponse(ResponseKind.UNKNOWN, None, line)


def apply_response(state: ReceiverState, response: ParsedResponse) -> ReceiverState:
    """Return a state updated by a parsed response."""
    if response.kind is ResponseKind.POWER:
        return replace(state, power=bool(response.value))
    if response.kind is ResponseKind.VOLUME:
        return replace(state, volume_raw=int(response.value))
    if response.kind is ResponseKind.MUTE:
        return replace(state, muted=bool(response.value))
    if response.kind is ResponseKind.SOURCE:
        return replace(state, source_code=str(response.value))
    return state


def volume_command(level: float) -> str:
    """Create a set-volume command from a normalized level."""
    clamped = min(1.0, max(0.0, level))
    return f"{round(clamped * VOLUME_MAX):03d}VL"


def source_command(code: str) -> str:
    """Create an input-selection command."""
    if len(code) != 2 or not code.isdigit():
        raise ProtocolError(f"invalid source code: {code!r}")
    return f"{code}FN"

