"""End-to-end tests inside Home Assistant against a fake receiver."""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.pioneer_avr.const import (
    CONF_MAX_VOLUME_RAW,
    CONF_VOLUME_MAX_RAW,
    CONF_VOLUME_MIN_RAW,
    CONF_VOLUME_STEP_DB,
)

MP = "media_player.pioneer_vsx_827"
SWITCH = "switch.pioneer_vsx_827_control_connection"


@pytest.fixture(autouse=True)
def fast_volume(monkeypatch):  # noqa: ANN001
    from custom_components.pioneer_avr.client import PioneerAVRClient

    monkeypatch.setattr(PioneerAVRClient, "VOLUME_SETTLE", 0.05)


async def _setup(hass: HomeAssistant, entry) -> None:  # noqa: ANN001
    # SSDP discovery is irrelevant here; mark the dependency as loaded.
    hass.config.components.add("ssdp")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_creates_receiver_and_connection_switch(
    hass: HomeAssistant, receiver, make_entry
) -> None:
    await _setup(hass, make_entry())
    assert hass.states.get(MP).state == STATE_ON
    assert hass.states.get(SWITCH).state == STATE_ON
    assert receiver.active == 1


async def test_pause_releases_the_only_connection_and_resumes(
    hass: HomeAssistant, receiver, make_entry
) -> None:
    await _setup(hass, make_entry())

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": SWITCH}, blocking=True
    )
    for _ in range(50):
        if receiver.active == 0:
            break
        await asyncio.sleep(0.02)
    assert receiver.active == 0
    assert hass.states.get(SWITCH).state == STATE_OFF
    assert hass.states.get(SWITCH).attributes["paused_until"] is not None
    player = hass.states.get(MP)
    assert player.state == STATE_ON
    assert player.attributes.get("assumed_state") is True

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": SWITCH}, blocking=True
    )
    assert receiver.active == 1
    assert hass.states.get(SWITCH).state == STATE_ON


async def test_command_while_paused_resumes_connection(
    hass: HomeAssistant, receiver, make_entry
) -> None:
    await _setup(hass, make_entry())
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": SWITCH}, blocking=True
    )
    await hass.services.async_call(
        "media_player", "volume_down", {"entity_id": MP}, blocking=True
    )
    assert receiver.volume == 83
    assert hass.states.get(SWITCH).state == STATE_ON


async def test_slider_respects_maximum_volume(
    hass: HomeAssistant, receiver, make_entry
) -> None:
    await _setup(hass, make_entry(**{CONF_MAX_VOLUME_RAW: 91}))
    await hass.services.async_call(
        "media_player",
        "volume_set",
        {"entity_id": MP, "volume_level": 1.0},
        blocking=True,
    )
    assert receiver.volume == 91
    await hass.services.async_call(
        "media_player", "volume_up", {"entity_id": MP}, blocking=True
    )
    assert receiver.volume == 91


async def test_volume_step_size(hass: HomeAssistant, receiver, make_entry) -> None:
    await _setup(hass, make_entry(**{CONF_VOLUME_STEP_DB: 3}))
    await hass.services.async_call(
        "media_player", "volume_up", {"entity_id": MP}, blocking=True
    )
    assert receiver.volume == 91
    await hass.services.async_call(
        "media_player", "volume_down", {"entity_id": MP}, blocking=True
    )
    assert receiver.volume == 85


async def test_volume_wizard(hass: HomeAssistant, receiver, make_entry) -> None:
    entry = make_entry()
    await _setup(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "volume_quiet"}
    )
    assert result["step_id"] == "volume_quiet"
    assert result["description_placeholders"]["current"] == "-38 dB"

    receiver.volume = 41
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["step_id"] == "volume_loud"

    receiver.volume = 101
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["step_id"] == "volume_limits"
    schema = result["data_schema"].schema
    defaults = {str(key): key.default() for key in schema}
    assert defaults[CONF_MAX_VOLUME_RAW] == "-30"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_MAX_VOLUME_RAW: "-30", CONF_VOLUME_STEP_DB: "2"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options[CONF_VOLUME_MIN_RAW] == 41
    assert entry.options[CONF_VOLUME_MAX_RAW] == 101
    assert entry.options[CONF_MAX_VOLUME_RAW] == 101
    assert entry.options[CONF_VOLUME_STEP_DB] == 2


async def test_wizard_rejects_loud_below_quiet(
    hass: HomeAssistant, receiver, make_entry
) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "volume_quiet"}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    receiver.volume = 61
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "invalid_volume_range"}


async def test_general_options(hass: HomeAssistant, receiver, make_entry) -> None:
    entry = make_entry()
    await _setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "general"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"assume_off_when_unavailable": False, "pause_minutes": "30"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["pause_minutes"] == 30
    assert entry.options["assume_off_when_unavailable"] is False
