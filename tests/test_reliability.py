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


class SteppingReceiver:
    """Fake VSX-827: VU/VD move by two raw half-steps, nnnVL is ignored."""

    def __init__(self, volume: int, power: bool = True) -> None:
        self.volume = volume
        self.power = power
        self.commands: list[str] = []

    async def handle(self, reader, writer) -> None:  # noqa: ANN001
        try:
            while line := await reader.readuntil(b"\r"):
                command = line.decode().strip()
                self.commands.append(command)
                if command == "VU":
                    self.volume += 2
                elif command == "VD":
                    self.volume -= 2
                if command in {"VU", "VD", "?VOL"}:
                    writer.write(f"VOL{self.volume:03d}\r\n".encode())
                elif command == "?PWR":
                    writer.write(b"PWR0\r\n" if self.power else b"PWR1\r\n")
                elif command in STATE_REPLIES:
                    writer.write(STATE_REPLIES[command])
                else:
                    writer.write(b"R\r\n")
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass


async def _stepping_client(receiver: SteppingReceiver):  # noqa: ANN202
    server, port = await _start(receiver.handle)
    client = PioneerAVRClient(
        "127.0.0.1", port, 0.5, volume_min_raw=1, volume_max_raw=161
    )
    client.VOLUME_SETTLE = 0.05
    await client.query_state()
    return server, client


@pytest.mark.asyncio
async def test_set_volume_reaches_target_with_two_raw_steps() -> None:
    receiver = SteppingReceiver(volume=85)
    server, client = await _stepping_client(receiver)
    try:
        await client.set_volume((95 - 1) / 160)  # raw 95 = five VU steps
        assert receiver.volume == 95
        assert receiver.commands.count("VU") == 5
        assert not any(command.endswith("VL") for command in receiver.commands)

        await client.set_volume((79 - 1) / 160)
        assert receiver.volume == 79
        assert receiver.commands.count("VD") == 8
    finally:
        await client.disconnect()
        server.close()


@pytest.mark.asyncio
async def test_set_volume_never_raises_more_than_10_db_per_call() -> None:
    receiver = SteppingReceiver(volume=41)
    server, client = await _stepping_client(receiver)
    try:
        await client.set_volume(1.0)
        assert receiver.volume == 41 + 20
        assert receiver.commands.count("VU") == 10
    finally:
        await client.disconnect()
        server.close()


@pytest.mark.asyncio
async def test_set_volume_refuses_when_receiver_is_off() -> None:
    receiver = SteppingReceiver(volume=85, power=False)
    server, client = await _stepping_client(receiver)
    try:
        with pytest.raises(PioneerAVRProtocolError, match="off"):
            await client.set_volume(0.9)
        assert "VU" not in receiver.commands
    finally:
        await client.disconnect()
        server.close()


@pytest.mark.asyncio
async def test_refused_connection_explains_single_client_limit() -> None:
    server, port = await _start(lambda reader, writer: None)
    server.close()
    await server.wait_closed()
    client = PioneerAVRClient("127.0.0.1", port, 0.5)
    with pytest.raises(PioneerAVRConnectionError, match="only one control"):
        await client.query_state()
