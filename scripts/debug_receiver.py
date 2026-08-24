#!/usr/bin/env python3
"""Standalone Pioneer VSX-827 TCP debugging utility."""

from __future__ import annotations

import argparse
import asyncio
import sys
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
    args = parser.parse_args()
    if not (args.command or args.query or args.validate):
        args.query = True
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
