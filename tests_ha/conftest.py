"""Fixtures for Home Assistant integration tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pioneer_avr.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):  # noqa: ANN001
    """Load custom_components/ in every test."""
    return


class FakeReceiver:
    """VSX-827 lookalike: one client at a time, 1 dB = 2 raw per VU/VD."""

    def __init__(self) -> None:
        self.volume = 85
        self.power = True
        self.commands: list[str] = []
        self.connections = 0
        self.active = 0
        self.port = 0
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        assert self._server is not None
        self._server.close()

    async def _handle(self, reader, writer) -> None:  # noqa: ANN001
        self.connections += 1
        self.active += 1
        try:
            while line := await reader.readuntil(b"\r"):
                command = line.decode().strip()
                self.commands.append(command)
                if command == "VU":
                    self.volume += 2
                elif command == "VD":
                    self.volume -= 2
                elif command == "PO":
                    self.power = True
                elif command == "PF":
                    self.power = False
                reply = {
                    "?PWR": f"PWR{0 if self.power else 1}",
                    "?MUT": "MUT1",
                    "?FN": "FN25",
                }.get(command)
                if command in {"VU", "VD", "?VOL"}:
                    reply = f"VOL{self.volume:03d}"
                if reply is None:
                    reply = "R"
                writer.write(reply.encode() + b"\r\n")
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self.active -= 1
            writer.close()


@pytest.fixture
async def receiver(socket_enabled) -> AsyncIterator[FakeReceiver]:  # noqa: ANN001, ARG001
    fake = FakeReceiver()
    await fake.start()
    yield fake
    await fake.stop()


@pytest.fixture
def make_entry(receiver: FakeReceiver):  # noqa: ANN201
    def _make(**options):  # noqa: ANN003, ANN202
        return MockConfigEntry(
            domain=DOMAIN,
            title="Pioneer VSX-827",
            unique_id="uuid:test",
            data={"host": "127.0.0.1", "port": receiver.port},
            options=options,
        )

    return _make
