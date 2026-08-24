"""Reusable asynchronous client for Pioneer VSX-827 receivers."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

from .const import (
    SOUND_MODE_COMMANDS,
    SOURCE_CODES,
    SOURCES,
    VOLUME_MAX,
    VOLUME_MIN,
)
from .protocol import (
    ProtocolError,
    ReceiverState,
    ResponseKind,
    apply_response,
    parse_response,
    source_command,
)
from .transport import PioneerTCPTransport, TransportError, TransportTimeout

_LOGGER = logging.getLogger(__name__)


class PioneerAVRError(Exception):
    """Base Pioneer AVR client error."""


class PioneerAVRConnectionError(PioneerAVRError):
    """The receiver could not be reached."""


class PioneerAVRProtocolError(PioneerAVRError):
    """The endpoint did not speak the expected protocol."""


class PioneerAVRClient:
    """Control one Pioneer VSX-827 main zone over TCP."""

    QUERY_COMMANDS = (
        ("?PWR", "PWR", ResponseKind.POWER),
        ("?VOL", "VOL", ResponseKind.VOLUME),
        ("?MUT", "MUT", ResponseKind.MUTE),
        ("?FN", "FN", ResponseKind.SOURCE),
    )
    ACTION_ATTEMPTS = 4

    def __init__(
        self,
        host: str,
        port: int = 8102,
        timeout: float = 5.0,
        *,
        volume_min_raw: int = VOLUME_MIN,
        volume_max_raw: int = VOLUME_MAX,
    ) -> None:
        if not VOLUME_MIN <= volume_min_raw < volume_max_raw <= VOLUME_MAX:
            raise ValueError("invalid calibrated volume range")
        self._transport = PioneerTCPTransport(host, port, timeout)
        self._transport.add_listener(self._handle_response)
        self._state = ReceiverState()
        self._listeners: list[Callable[[ReceiverState], None]] = []
        self._volume_min_raw = volume_min_raw
        self._volume_max_raw = volume_max_raw
        # Live VSX-827 validation showed that nnnVL is ignored. Only individual
        # VU/VD operations are safe; exact volume is not exposed.
        self._direct_volume_supported = False

    @property
    def connected(self) -> bool:
        """Return whether the TCP transport is connected."""
        return self._transport.connected

    @property
    def state(self) -> ReceiverState:
        """Return the last known receiver state."""
        return self._state

    @property
    def sources(self) -> list[str]:
        """Return selectable source names."""
        return list(SOURCE_CODES)

    @property
    def volume_control_mode(self) -> str:
        """Return how exact volume is implemented for this receiver session."""
        if self._direct_volume_supported is True:
            return "direct"
        if self._direct_volume_supported is False:
            return "step"
        return "unknown"

    @property
    def volume_range_raw(self) -> tuple[int, int]:
        """Return the calibrated raw volume endpoints."""
        return self._volume_min_raw, self._volume_max_raw

    @property
    def volume_level(self) -> float | None:
        """Return calibrated volume normalized for Home Assistant."""
        raw = self._state.volume_raw
        if raw is None:
            return None
        span = self._volume_max_raw - self._volume_min_raw
        return min(1.0, max(0.0, (raw - self._volume_min_raw) / span))

    def add_state_listener(
        self, listener: Callable[[ReceiverState], None]
    ) -> Callable[[], None]:
        """Register a state listener."""
        self._listeners.append(listener)

        def remove() -> None:
            with contextlib.suppress(ValueError):
                self._listeners.remove(listener)

        return remove

    async def connect(self) -> None:
        """Connect to the receiver."""
        try:
            await self._transport.connect()
        except TransportError as err:
            raise PioneerAVRConnectionError from err

    async def disconnect(self) -> None:
        """Disconnect from the receiver."""
        await self._transport.disconnect()

    async def query_state(self) -> ReceiverState:
        """Refresh all basic state supported by the VSX-827."""
        await self.connect()
        power_seen = False
        for command, prefix, expected_kind in self.QUERY_COMMANDS:
            try:
                response = await self._transport.request(command, prefix)
                try:
                    parsed = parse_response(response)
                except ProtocolError as err:
                    raise PioneerAVRProtocolError(
                        f"invalid {prefix} response"
                    ) from err
                if parsed.kind is not expected_kind:
                    raise PioneerAVRProtocolError(
                        f"unexpected response to {command}"
                    )
                self._handle_response(response)
                power_seen |= prefix == "PWR"
            except TransportTimeout:
                if prefix == "PWR":
                    raise PioneerAVRProtocolError(
                        "receiver did not answer the power query"
                    ) from None
                _LOGGER.debug("Receiver did not answer optional %s query", prefix)
            except TransportError as err:
                raise PioneerAVRConnectionError from err
        if not power_seen:
            raise PioneerAVRProtocolError("no Pioneer power response received")
        return self._state

    async def set_power(self, power: bool) -> None:
        """Set main-zone power."""
        await self._send("PO" if power else "PF")

    async def volume_up(self) -> None:
        """Send one main-zone volume-up command without retrying it."""
        await self._send("VU")

    async def volume_down(self) -> None:
        """Send one main-zone volume-down command without retrying it."""
        await self._send("VD")

    async def set_volume(self, level: float) -> None:
        """Safely emulate exact volume with individually confirmed steps."""
        clamped = min(1.0, max(0.0, level))
        target = round(
            self._volume_min_raw
            + clamped * (self._volume_max_raw - self._volume_min_raw)
        )
        state = await self.query_state()
        current = state.volume_raw
        if current is None:
            raise PioneerAVRProtocolError("receiver did not report its volume")
        while current != target:
            expected = current + 1 if target > current else current - 1
            command = "VU" if target > current else "VD"
            state = await self._send_volume_step(command, expected)
            current = state.volume_raw
            if current is None:
                raise PioneerAVRProtocolError("receiver did not report its volume")

    async def set_mute(self, muted: bool) -> None:
        """Set main-zone mute."""
        await self._send_and_confirm(
            "MO" if muted else "MF",
            lambda state: state.muted is muted,
            "mute on" if muted else "mute off",
        )

    async def select_input(self, source: str) -> None:
        """Select a friendly input source."""
        try:
            code = SOURCE_CODES[source]
        except KeyError as err:
            raise PioneerAVRProtocolError(f"unknown source: {source}") from err
        # AirPlay and DMR are status values but cannot be selected directly.
        if code in {"46", "47"}:
            raise PioneerAVRProtocolError(f"source cannot be selected: {source}")
        await self._send_and_confirm(
            source_command(code),
            lambda state: state.source_code == code,
            f"select source {source}",
        )

    async def set_sound_mode(self, mode: str) -> None:
        """Select or cycle a documented VSX-827 listening-mode group."""
        try:
            command = SOUND_MODE_COMMANDS[mode]
        except KeyError as err:
            raise PioneerAVRProtocolError(f"unknown sound mode: {mode}") from err
        # The VSX-827 returns only a generic R acknowledgement and provides no
        # query for current mode, so do not claim a confirmed state here.
        await self._send(command)

    async def send_raw(self, command: str, expected_prefix: str = "") -> str:
        """Send a command and return its next matching response for debugging."""
        await self.connect()
        try:
            return await self._transport.request(command, expected_prefix)
        except TransportError as err:
            raise PioneerAVRConnectionError from err

    async def _send(self, command: str) -> None:
        await self.connect()
        try:
            await self._transport.send(command)
            # Pioneer specifies a 100 ms inter-command delay for the 2012 API.
            await asyncio.sleep(0.1)
        except TransportError as err:
            raise PioneerAVRConnectionError from err

    async def _send_and_confirm(
        self,
        command: str,
        predicate: Callable[[ReceiverState], bool],
        operation: str,
    ) -> ReceiverState:
        """Send an idempotent command until queried state confirms it."""
        for attempt in range(1, self.ACTION_ATTEMPTS + 1):
            await self._send(command)
            state = await self.query_state()
            if predicate(state):
                return state
            _LOGGER.debug(
                "Receiver ignored %s attempt %d; retrying", operation, attempt
            )
        raise PioneerAVRProtocolError(
            f"receiver did not confirm {operation} after "
            f"{self.ACTION_ATTEMPTS} attempts"
        )

    async def _send_volume_step(
        self, command: str, expected_volume: int
    ) -> ReceiverState:
        """Send one non-idempotent volume step without ever retrying it."""
        loop = asyncio.get_running_loop()
        confirmed: asyncio.Future[ReceiverState] = loop.create_future()

        def handle_state(state: ReceiverState) -> None:
            if state.volume_raw == expected_volume and not confirmed.done():
                confirmed.set_result(state)

        remove_listener = self.add_state_listener(handle_state)
        try:
            await self._send(command)
            if self._state.volume_raw == expected_volume:
                return self._state
            try:
                return await asyncio.wait_for(confirmed, 1.5)
            except TimeoutError:
                await asyncio.sleep(0.5)
                state = await self.query_state()
                if state.volume_raw == expected_volume:
                    return state
                raise PioneerAVRProtocolError(
                    f"volume step expected {expected_volume}, "
                    f"received {state.volume_raw!r}; command was not retried"
                ) from None
        finally:
            remove_listener()

    def _handle_response(self, raw: str) -> None:
        try:
            response = parse_response(raw)
        except ProtocolError:
            _LOGGER.debug("Ignoring malformed Pioneer response")
            return
        new_state = apply_response(self._state, response)
        if new_state == self._state:
            return
        self._state = new_state
        for listener in tuple(self._listeners):
            listener(new_state)


__all__ = [
    "PioneerAVRClient",
    "PioneerAVRConnectionError",
    "PioneerAVRError",
    "PioneerAVRProtocolError",
    "ReceiverState",
    "SOURCES",
]
