"""Asynchronous transport for Pioneer AVR receivers."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

from .protocol import encode_command

_LOGGER = logging.getLogger(__name__)


class TransportError(ConnectionError):
    """Base transport error."""


class TransportTimeout(TransportError):
    """The receiver did not answer in time."""


class PioneerTCPTransport:
    """Persistent, serialized TCP transport."""

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._command_lock = asyncio.Lock()
        self._pending: tuple[str, asyncio.Future[str]] | None = None
        self._listeners: list[Callable[[str], None]] = []

    @property
    def connected(self) -> bool:
        """Return whether the connection is open."""
        return self._writer is not None and not self._writer.is_closing()

    def add_listener(self, listener: Callable[[str], None]) -> Callable[[], None]:
        """Register a raw response listener."""
        self._listeners.append(listener)

        def remove() -> None:
            with contextlib.suppress(ValueError):
                self._listeners.remove(listener)

        return remove

    async def connect(self) -> None:
        """Open the receiver connection."""
        if self.connected:
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), self.timeout
            )
        except (OSError, TimeoutError) as err:
            raise TransportError(f"cannot connect to {self.host}:{self.port}") from err
        self._listener_task = asyncio.create_task(
            self._listen(), name="pioneer_avr_listener"
        )

    async def disconnect(self) -> None:
        """Close the receiver connection."""
        task = self._listener_task
        self._listener_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        writer = self._writer
        self._reader = None
        self._writer = None
        if writer is not None:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
        self._fail_pending(TransportError("transport disconnected"))

    async def send(self, command: str) -> None:
        """Send a command without waiting for a particular response."""
        async with self._command_lock:
            await self._ensure_connected()
            assert self._writer is not None
            self._writer.write(encode_command(command))
            try:
                await asyncio.wait_for(self._writer.drain(), self.timeout)
            except (OSError, TimeoutError) as err:
                await self.disconnect()
                raise TransportError("failed to send receiver command") from err

    async def request(self, command: str, expected_prefix: str) -> str:
        """Send a command and wait for the matching response."""
        async with self._command_lock:
            await self._ensure_connected()
            loop = asyncio.get_running_loop()
            future: asyncio.Future[str] = loop.create_future()
            self._pending = (expected_prefix, future)
            assert self._writer is not None
            self._writer.write(encode_command(command))
            try:
                await asyncio.wait_for(self._writer.drain(), self.timeout)
                return await asyncio.wait_for(future, self.timeout)
            except TimeoutError as err:
                if self._pending is not None and self._pending[1] is future:
                    self._pending = None
                response_type = expected_prefix or "raw"
                raise TransportTimeout(f"no {response_type} response") from err
            except OSError as err:
                await self.disconnect()
                raise TransportError("receiver connection failed") from err

    async def _ensure_connected(self) -> None:
        if not self.connected:
            await self.connect()

    async def _listen(self) -> None:
        assert self._reader is not None
        try:
            while True:
                wire_line = await self._reader.readuntil(b"\r")
                line = wire_line.decode("ascii", errors="replace").strip("\r\n")
                if not line:
                    continue
                _LOGGER.debug("Received Pioneer response prefix: %s", line[:3])
                for listener in tuple(self._listeners):
                    listener(line)
                if self._pending is not None:
                    prefix, future = self._pending
                    if line.startswith(prefix):
                        self._pending = None
                        if not future.done():
                            future.set_result(line)
        except asyncio.CancelledError:
            raise
        except (OSError, asyncio.IncompleteReadError) as err:
            _LOGGER.debug("Pioneer listener stopped: %s", err)
            self._fail_pending(TransportError("receiver closed the connection"))
            self._reader = None
            self._writer = None

    def _fail_pending(self, error: Exception) -> None:
        if self._pending is None:
            return
        _, future = self._pending
        self._pending = None
        if not future.done():
            future.set_exception(error)
