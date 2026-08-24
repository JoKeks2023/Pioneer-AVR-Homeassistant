"""Tests for the Pioneer AVR wire protocol."""

from __future__ import annotations

import pytest

from custom_components.pioneer_avr.protocol import (
    ProtocolError,
    ReceiverState,
    ResponseKind,
    apply_response,
    encode_command,
    parse_response,
    source_command,
)


@pytest.mark.parametrize(
    ("raw", "kind", "value"),
    [
        ("PWR0\r\n", ResponseKind.POWER, True),
        ("PWR1", ResponseKind.POWER, False),
        ("PWR2", ResponseKind.POWER, False),
        ("VOL080", ResponseKind.VOLUME, 80),
        ("MUT0", ResponseKind.MUTE, True),
        ("MUT1", ResponseKind.MUTE, False),
        ("FN25", ResponseKind.SOURCE, "25"),
    ],
)
def test_parse_response(raw: str, kind: ResponseKind, value: object) -> None:
    parsed = parse_response(raw)
    assert parsed.kind is kind
    assert parsed.value == value


def test_apply_response_and_friendly_source() -> None:
    state = apply_response(ReceiverState(), parse_response("FN25"))
    assert state.source_code == "25"
    assert state.source == "BD"


def test_unknown_response_is_ignored() -> None:
    parsed = parse_response("RGC0")
    assert parsed.kind is ResponseKind.UNKNOWN
    state = ReceiverState(power=True)
    assert apply_response(state, parsed) is state


@pytest.mark.parametrize("raw", ["PWR9", "VOLabc", "VOL999", "MUT8", "FN1"])
def test_invalid_responses(raw: str) -> None:
    with pytest.raises(ProtocolError):
        parse_response(raw)


def test_command_encoding_and_builders() -> None:
    assert encode_command("?PWR") == b"?PWR\r"
    assert source_command("05") == "05FN"
