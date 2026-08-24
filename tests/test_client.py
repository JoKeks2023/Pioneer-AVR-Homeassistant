"""Tests for the reusable Pioneer AVR TCP client."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.pioneer_avr.client import (
    PioneerAVRClient,
    PioneerAVRProtocolError,
)


@pytest.mark.asyncio
async def test_query_and_commands_with_fragmented_unsolicited_responses() -> None:
    received: list[str] = []
    volume = 80
    muted = False
    source = "25"

    async def receiver(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        nonlocal muted, source, volume
        try:
            while command_bytes := await reader.readuntil(b"\r"):
                command = command_bytes.decode().strip()
                received.append(command)
                if command == "?PWR":
                    payload = b"VOL075\rPWR0\r"
                elif command == "?VOL":
                    payload = f"VOL{volume:03d}\r".encode()
                elif command == "?MUT":
                    payload = f"MUT{0 if muted else 1}\r".encode()
                elif command == "?FN":
                    payload = f"FN{source}\r".encode()
                elif command.endswith("VL"):
                    volume = int(command[:3])
                    payload = f"VOL{volume:03d}\r".encode()
                elif command == "VU":
                    volume += 1
                    payload = f"VOL{volume:03d}\r".encode()
                elif command == "VD":
                    volume -= 1
                    payload = f"VOL{volume:03d}\r".encode()
                elif command == "MO":
                    muted = True
                    payload = b"MUT0\r"
                elif command == "MF":
                    muted = False
                    payload = b"MUT1\r"
                elif command.endswith("FN"):
                    source = command[:2]
                    payload = f"FN{source}\r".encode()
                else:
                    payload = b""
                if payload:
                    writer.write(payload[:3])
                    await writer.drain()
                    writer.write(payload[3:])
                    await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(receiver, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = PioneerAVRClient("127.0.0.1", port, 1)
    try:
        state = await client.query_state()
        assert state.power is True
        assert state.volume_raw == 80
        assert state.muted is False
        assert state.source == "BD"
        await client.set_power(False)
        await client.volume_down()
        await client.set_mute(True)
        await client.select_input("TV")
        await asyncio.sleep(0)
        assert "064VL" not in received
        assert received.count("VD") == 1
        assert "MO" in received
        assert "05FN" in received
        assert client.volume_control_mode == "step"
    finally:
        await client.disconnect()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_rejects_malformed_power_response() -> None:
    class InvalidTransport:
        connected = True

        def add_listener(self, listener):  # noqa: ANN001, ANN202
            return lambda: None

        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def request(self, command: str, expected_prefix: str) -> str:
            return "PWR9"

    client = PioneerAVRClient("invalid")
    client._transport = InvalidTransport()  # type: ignore[assignment]  # noqa: SLF001
    with pytest.raises(PioneerAVRProtocolError):
        await client.query_state()


@pytest.mark.asyncio
async def test_rejects_unknown_source_without_connecting() -> None:
    client = PioneerAVRClient("invalid")
    with pytest.raises(PioneerAVRProtocolError):
        await client.select_input("Phono")


@pytest.mark.asyncio
async def test_exact_volume_uses_individually_confirmed_steps() -> None:
    class StepTransport:
        connected = True

        def __init__(self) -> None:
            self.volume = 19
            self.commands: list[str] = []
            self.listener = None

        def add_listener(self, listener):  # noqa: ANN001, ANN202
            self.listener = listener
            return lambda: None

        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def send(self, command: str) -> None:
            self.commands.append(command)
            if command == "VD":
                self.volume -= 1
            elif command == "VU":
                self.volume += 1
            if self.listener is not None:
                self.listener(f"VOL{self.volume:03d}")

        async def request(self, command: str, expected_prefix: str) -> str:
            return {
                "?PWR": "PWR0",
                "?VOL": f"VOL{self.volume:03d}",
                "?MUT": "MUT1",
                "?FN": "FN49",
            }[command]

    transport = StepTransport()
    client = PioneerAVRClient("invalid")
    client._transport = transport  # type: ignore[assignment]  # noqa: SLF001
    transport.listener = client._handle_response  # noqa: SLF001
    await client.set_volume(17 / 161)

    assert transport.commands == ["VD", "VD"]
    assert client.state.volume_raw == 17
    assert client.volume_control_mode == "step"


@pytest.mark.asyncio
async def test_sound_mode_group_sends_documented_command_once() -> None:
    class CommandTransport:
        connected = True

        def __init__(self) -> None:
            self.commands: list[str] = []

        def add_listener(self, listener):  # noqa: ANN001, ANN202
            return lambda: None

        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def send(self, command: str) -> None:
            self.commands.append(command)

    transport = CommandTransport()
    client = PioneerAVRClient("invalid")
    client._transport = transport  # type: ignore[assignment]  # noqa: SLF001
    await client.set_sound_mode("Auto / Direct")

    assert transport.commands == ["0005SR"]


@pytest.mark.asyncio
async def test_mute_retries_when_receiver_ignores_first_command() -> None:
    class IntermittentTransport:
        connected = True

        def __init__(self) -> None:
            self.mute_commands = 0

        def add_listener(self, listener):  # noqa: ANN001, ANN202
            return lambda: None

        async def connect(self) -> None:
            return None

        async def disconnect(self) -> None:
            return None

        async def send(self, command: str) -> None:
            if command == "MO":
                self.mute_commands += 1

        async def request(self, command: str, expected_prefix: str) -> str:
            responses = {
                "?PWR": "PWR0",
                "?VOL": "VOL019",
                "?MUT": "MUT0" if self.mute_commands >= 2 else "MUT1",
                "?FN": "FN49",
            }
            return responses[command]

    transport = IntermittentTransport()
    client = PioneerAVRClient("invalid")
    client._transport = transport  # type: ignore[assignment]  # noqa: SLF001
    await client.set_mute(True)

    assert transport.mute_commands == 2
    assert client.state.muted is True
