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
    POWER_ON_ATTEMPTS = 3
    # Hardware probe 2026-11-25: one VU/VD moves the VSX-827 by exactly two raw
    # half-steps (1 dB). Steps sent 100 ms apart (see _send) are all applied.
    VOLUME_STEP_RAW = 2
    VOLUME_SETTLE = 0.6
    VOLUME_SET_ROUNDS = 3
    # Never raise the volume by more than 10 dB in one set_volume call.
    VOLUME_MAX_RAISE_STEPS = 10
    POWER_ON_SETTLE = 1.5

    def __init__(
        self,
        host: str,
        port: int = 8102,
        timeout: float = 5.0,
        *,
        volume_min_raw: int = VOLUME_MIN,
        volume_max_raw: int = VOLUME_MAX,
        max_volume_raw: int | None = None,
        volume_step_db: int = 1,
    ) -> None:
        if not VOLUME_MIN <= volume_min_raw < volume_max_raw <= VOLUME_MAX:
            raise ValueError("invalid calibrated volume range")
        if max_volume_raw is not None and not VOLUME_MIN < max_volume_raw <= VOLUME_MAX:
            raise ValueError("invalid maximum volume")
        if volume_step_db < 1:
            raise ValueError("invalid volume step")
        self._max_volume_raw = max_volume_raw
        self._volume_step_db = volume_step_db
        self._transport = PioneerTCPTransport(host, port, timeout)
        self._transport.add_listener(self._handle_response)
        self._state = ReceiverState()
        self._listeners: list[Callable[[ReceiverState], None]] = []
        self._volume_min_raw = volume_min_raw
        self._volume_max_raw = volume_max_raw
        self._volume_lock = asyncio.Lock()
        self._volume_target: float | None = None

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
        """Return how exact volume is implemented."""
        return "confirmed_steps"

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

    def add_raw_listener(self, listener: Callable[[str], None]) -> Callable[[], None]:
        """Register a listener for every raw response line (debugging)."""
        return self._transport.add_listener(listener)

    async def connect(self) -> None:
        """Connect to the receiver."""
        try:
            await self._transport.connect()
        except TransportError as err:
            raise PioneerAVRConnectionError(str(err)) from err

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
                    raise PioneerAVRProtocolError(f"invalid {prefix} response") from err
                if parsed.kind is not expected_kind:
                    raise PioneerAVRProtocolError(f"unexpected response to {command}")
                self._handle_response(response)
                power_seen |= prefix == "PWR"
            except TransportTimeout as err:
                if prefix == "PWR":
                    # A silent receiver usually means a dead or half-open
                    # connection; drop it so the next attempt reconnects.
                    await self._transport.disconnect()
                    raise PioneerAVRConnectionError(
                        "receiver did not answer the power query"
                    ) from err
                _LOGGER.debug("Receiver did not answer optional %s query", prefix)
            except TransportError as err:
                raise PioneerAVRConnectionError(str(err)) from err
        if not power_seen:
            raise PioneerAVRProtocolError("no Pioneer power response received")
        return self._state

    async def set_power(self, power: bool) -> None:
        """Set main-zone power.

        Power-on wakes the receiver CPU with a bare CR first, as required by
        the 2012 Pioneer IP/RS-232 document, and is confirmed with ``?PWR``.
        Power-off is sent once and not confirmed: the VSX-827 may drop off the
        network right after switching off.
        """
        if not power:
            await self._send("PF")
            return
        for attempt in range(1, self.POWER_ON_ATTEMPTS + 1):
            await self.connect()
            try:
                await self._transport.wake()
                await asyncio.sleep(0.1)
                await self._transport.send("PO")
                await asyncio.sleep(self.POWER_ON_SETTLE)
                response = await self._transport.request("?PWR", "PWR")
            except TransportTimeout:
                _LOGGER.debug("No power reply after power-on attempt %d", attempt)
                await self._transport.disconnect()
                continue
            except TransportError as err:
                raise PioneerAVRConnectionError(str(err)) from err
            self._handle_response(response)
            if self._state.power is True:
                return
            _LOGGER.debug("Receiver ignored power-on attempt %d; retrying", attempt)
        raise PioneerAVRProtocolError(
            f"receiver did not confirm power on after {self.POWER_ON_ATTEMPTS} attempts"
        )

    @property
    def max_volume_raw(self) -> int | None:
        """Return the configured maximum raw volume, if any."""
        return self._max_volume_raw

    async def volume_up(self) -> None:
        """Raise the volume by the configured step size (1 dB per VU).

        With a maximum volume configured, the current volume is read first and
        only as many steps are sent as fit below the limit.
        """
        steps = self._volume_step_db
        if self._max_volume_raw is not None:
            current = await self._query_volume()
            steps = min(
                steps, max(0, (self._max_volume_raw - current) // self.VOLUME_STEP_RAW)
            )
            if steps == 0:
                _LOGGER.debug("Volume up skipped: maximum volume reached")
                return
        for _ in range(steps):
            await self._send("VU")

    async def volume_down(self) -> None:
        """Lower the volume by the configured step size (1 dB per VD)."""
        for _ in range(self._volume_step_db):
            await self._send("VD")

    async def set_volume(self, level: float) -> None:
        """Move to a calibrated volume level with confirmed 1 dB steps.

        The VSX-827 ignores ``nnnVL``, so the target is reached with VU/VD.
        Each round re-reads the actual volume before stepping, so a step is
        never blindly repeated. While a move is running, a newer target
        replaces the old one instead of queueing another move.
        """
        self._volume_target = min(1.0, max(0.0, level))
        if self._volume_lock.locked():
            return
        async with self._volume_lock:
            ceiling: int | None = None
            for _ in range(self.VOLUME_SET_ROUNDS):
                current = await self._query_volume()
                if ceiling is None:
                    ceiling = (
                        current + self.VOLUME_MAX_RAISE_STEPS * self.VOLUME_STEP_RAW
                    )
                target = self._target_raw(self._volume_target)
                target = min(target, ceiling)
                if self._max_volume_raw is not None:
                    target = min(target, self._max_volume_raw)
                # Round towards the current level so a step never overshoots
                # the target (and therefore never the maximum volume).
                delta = abs(target - current) // self.VOLUME_STEP_RAW
                steps = delta if target > current else -delta
                if steps == 0:
                    return
                command = "VU" if steps > 0 else "VD"
                for _ in range(abs(steps)):
                    await self._send(command)
                await asyncio.sleep(self.VOLUME_SETTLE)
            _LOGGER.debug(
                "Volume target not reached after %d rounds", self.VOLUME_SET_ROUNDS
            )

    def _target_raw(self, level: float) -> int:
        span = self._volume_max_raw - self._volume_min_raw
        return round(self._volume_min_raw + level * span)

    async def _query_volume(self) -> int:
        await self.connect()
        try:
            response = await self._transport.request("?VOL", "VOL")
        except TransportError as err:
            raise PioneerAVRConnectionError(str(err)) from err
        self._handle_response(response)
        if self._state.power is False:
            raise PioneerAVRProtocolError("receiver is off")
        if self._state.volume_raw is None:
            raise PioneerAVRProtocolError("receiver did not report its volume")
        return self._state.volume_raw

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
            raise PioneerAVRConnectionError(str(err)) from err

    async def _send(self, command: str) -> None:
        await self.connect()
        try:
            await self._transport.send(command)
            # Pioneer specifies a 100 ms inter-command delay for the 2012 API.
            await asyncio.sleep(0.1)
        except TransportError as err:
            raise PioneerAVRConnectionError(str(err)) from err

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
