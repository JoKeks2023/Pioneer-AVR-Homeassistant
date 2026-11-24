"""Reliability tests: silent receivers, reconnects and confirmed power-on."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.pioneer_avr.client import (
    PioneerAVRClient,
    PioneerAVRConnectionError,
    PioneerAVRProtocolError,
)

STATE_REPLIES = {
    "?VOL": b"VOL080\r\n",
    "?MUT": b"MUT1\r\n",
    "?FN": b"FN05\r\n",
}


async def _start(handler):  # noqa: ANN001, ANN202
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


@pytest.mark.asyncio
async def test_reconnects_after_receiver_goes_silent() -> None:
    connections = 0

    async def receiver(reader, writer) -> None:  # noqa: ANN001
        nonlocal connections
        connections += 1
        silent = connections == 1
        try:
            while line := await reader.readuntil(b"\r"):
                if silent:
                    continue  # half-open: socket stays up, nothing answers
                command = line.decode().strip()
                writer.write(STATE_REPLIES.get(command, b"PWR0\r\n"))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass

    server, port = await _start(receiver)
    client = PioneerAVRClient("127.0.0.1", port, 0.3)
    try:
        with pytest.raises(PioneerAVRConnectionError):
            await client.query_state()
        assert not client.connected

        state = await client.query_state()
        assert state.power is True
        assert connections == 2
    finally:
        await client.disconnect()
        server.close()


@pytest.mark.asyncio
async def test_reconnects_after_receiver_closes_connection() -> None:
    connections = 0

    async def receiver(reader, writer) -> None:  # noqa: ANN001
        nonlocal connections
        connections += 1
        if connections == 1:
            writer.close()
            return
        try:
            while line := await reader.readuntil(b"\r"):
                command = line.decode().strip()
                writer.write(STATE_REPLIES.get(command, b"PWR0\r\n"))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass

    server, port = await _start(receiver)
    client = PioneerAVRClient("127.0.0.1", port, 0.3)
    try:
        await client.connect()
        for _ in range(50):
            if not client.connected:
                break
            await asyncio.sleep(0.01)
        assert not client.connected

        state = await client.query_state()
        assert state.power is True
        assert connections == 2
    finally:
        await client.disconnect()
        server.close()


@pytest.mark.asyncio
async def test_power_on_wakes_receiver_and_retries_until_confirmed() -> None:
    received: list[str] = []
    power_on = False

    async def receiver(reader, writer) -> None:  # noqa: ANN001
        nonlocal power_on
        try:
            while line := await reader.readuntil(b"\r"):
                command = line.decode().strip()
                received.append(command)
                if command == "PO" and received.count("PO") >= 2:
                    power_on = True  # first PO from standby is ignored
                elif command == "?PWR":
                    writer.write(b"PWR0\r\n" if power_on else b"PWR1\r\n")
                    await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass

    server, port = await _start(receiver)
    client = PioneerAVRClient("127.0.0.1", port, 0.3)
    client.POWER_ON_SETTLE = 0.01
    try:
        await client.set_power(True)
        assert client.state.power is True
        assert received.count("PO") == 2
        # Every PO is preceded by a bare CR that wakes the receiver CPU.
        for index, command in enumerate(received):
            if command == "PO":
                assert received[index - 1] == ""
    finally:
        await client.disconnect()
        server.close()


@pytest.mark.asyncio
async def test_power_on_fails_when_receiver_never_confirms() -> None:
    async def receiver(reader, writer) -> None:  # noqa: ANN001
        try:
            while line := await reader.readuntil(b"\r"):
                if line.strip() == b"?PWR":
                    writer.write(b"PWR1\r\n")
                    await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass

    server, port = await _start(receiver)
    client = PioneerAVRClient("127.0.0.1", port, 0.3)
    client.POWER_ON_SETTLE = 0.01
    try:
        with pytest.raises(PioneerAVRProtocolError, match="power on"):
            await client.set_power(True)
    finally:
        await client.disconnect()
        server.close()
