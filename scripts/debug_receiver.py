#!/usr/bin/env python3
"""Standalone Pioneer VSX-827 TCP debugging utility."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from custom_components.pioneer_avr.client import (  # noqa: E402
    PioneerAVRClient,
    PioneerAVRError,
)
from custom_components.pioneer_avr.const import SOURCES  # noqa: E402


def _print_state(label: str, client: PioneerAVRClient) -> None:
    state = client.state
    print(
        f"{label}: power={state.power!r} volume_raw={state.volume_raw!r} "
        f"muted={state.muted!r} source={state.source!r}"
    )


async def _guarded_validate(client: PioneerAVRClient) -> None:
    """Exercise confirmed controls and restore the initial state."""
    original = await client.query_state()
    _print_state("Initial", client)

    try:
        if not original.power:
            print("Turning the receiver on for validation")
            await client.set_power(True)
            await asyncio.sleep(3)
            state = await client.query_state()
            if state.power is not True:
                raise PioneerAVRError("power-on validation failed")
            print("PASS power on")
        else:
            print("SKIP power cycle (receiver was initially on)")

        print("Testing mute on")
        await client.set_mute(True)
        state = await client.query_state()
        if state.muted is not True:
            raise PioneerAVRError("mute-on validation failed")
        print("PASS mute on")

        print("SKIP exact volume (not supported by VSX-827)")
        print("SKIP volume step mutation (single VU/VD commands are not retried)")

        original_source = original.source
        candidate = "CD" if original_source != "CD" else "Tuner"
        print(f"Testing input selection with {candidate}")
        await client.select_input(candidate)
        state = await client.query_state()
        if state.source != candidate:
            raise PioneerAVRError(
                f"input validation failed: expected {candidate!r}, "
                f"received {state.source!r}"
            )
        print("PASS input selection")
    finally:
        print("Restoring initial receiver state")
        if original.power:
            if original.source_code in SOURCES and original.source not in {
                "AirPlay",
                "DMR",
            }:
                await client.select_input(original.source)
            if original.muted is not None:
                await client.set_mute(original.muted)
        else:
            await client.set_power(False)
        await asyncio.sleep(0.5)
        await client.query_state()
        _print_state("Restored", client)


# The probe never raises the volume by more than this many raw half-steps
# (2 dB) above the starting level.
PROBE_MAX_RAISE = 4


async def _volume(client: PioneerAVRClient) -> int | None:
    await client.query_state()
    return client.state.volume_raw


async def _probe_step(
    client: PioneerAVRClient, label: str, commands: list[str], wake: bool
) -> int | None:
    """Send commands, log every raw reply for two seconds, return new volume."""
    transport = client._transport  # noqa: SLF001 - debugging tool
    before = await _volume(client)
    lines: list[tuple[float, str]] = []
    start = time.monotonic()
    remove = client.add_raw_listener(
        lambda line: lines.append((time.monotonic() - start, line))
    )
    try:
        for command in commands:
            if wake:
                await transport.wake()
                await asyncio.sleep(0.1)
            await transport.send(command)
            await asyncio.sleep(0.1)
        await asyncio.sleep(2)
    finally:
        remove()
    after = await _volume(client)
    replies = ", ".join(f"{t * 1000:.0f}ms {line}" for t, line in lines) or "none"
    print(f"{label}: {before} -> {after}  (replies: {replies})")
    return after


async def _restore_volume(client: PioneerAVRClient, target: int) -> None:
    for _ in range(20):
        current = await _volume(client)
        if current is None or current == target:
            break
        await client._transport.send("VD" if current > target else "VU")  # noqa: SLF001
        await asyncio.sleep(0.5)


async def _probe_volume(client: PioneerAVRClient) -> None:
    """Measure how the receiver reacts to the different volume commands."""
    original = await _volume(client)
    if client.state.power is not True or original is None:
        raise PioneerAVRError("switch the receiver on before probing volume")
    if original + PROBE_MAX_RAISE > 161:
        raise PioneerAVRError("volume too close to maximum for a safe probe")
    print(f"Start volume raw={original} (probe raises at most +{PROBE_MAX_RAISE})")
    try:
        await _probe_step(client, "VU", ["VU"], wake=False)
        await _probe_step(client, "VD", ["VD"], wake=False)
        await _probe_step(client, "CR+VU", ["VU"], wake=True)
        await _probe_step(client, "CR+VD", ["VD"], wake=True)
        await _probe_step(client, "VU x3 (100 ms)", ["VU", "VU", "VU"], wake=False)
        await _restore_volume(client, original)
        target = original + 2
        await _probe_step(client, f"{target:03d}VL", [f"{target:03d}VL"], wake=False)
        await _restore_volume(client, original)
        await _probe_step(client, f"CR+{target:03d}VL", [f"{target:03d}VL"], wake=True)
    finally:
        await _restore_volume(client, original)
        print(f"Restored volume raw={await _volume(client)} (start {original})")


async def _run(args: argparse.Namespace) -> int:
    client = PioneerAVRClient(args.host, args.port, args.timeout)
    try:
        await client.connect()
        print(f"Connected to Pioneer receiver on TCP port {args.port}")
        if args.command:
            response = await client.send_raw(args.command, args.expect)
            print(f"Raw response: {response}")
        if args.query:
            await client.query_state()
            _print_state("State", client)
        if args.validate:
            await _guarded_validate(client)
        if args.probe_volume:
            await _probe_volume(client)
    except PioneerAVRError as err:
        print(f"Error: {err or type(err).__name__}", file=sys.stderr)
        return 1
    finally:
        await client.disconnect()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="Receiver hostname or IP address")
    parser.add_argument("--port", type=int, default=8102)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--command", help="Send one raw Pioneer command")
    parser.add_argument(
        "--expect",
        default="",
        help="Only return a response beginning with this prefix",
    )
    parser.add_argument("--query", action="store_true", help="Query basic state")
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run guarded state-changing checks and restore initial state",
    )
    parser.add_argument(
        "--probe-volume",
        action="store_true",
        help="Measure VU/VD/VL behaviour (max +2 dB) and restore the volume",
    )
    args = parser.parse_args()
    if not (args.command or args.query or args.validate or args.probe_volume):
        args.query = True
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
