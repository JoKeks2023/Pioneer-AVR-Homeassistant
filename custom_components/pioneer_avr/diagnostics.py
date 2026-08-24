"""Diagnostics for Pioneer AVR."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return sanitized config entry diagnostics."""
    runtime = entry.runtime_data
    state = runtime.coordinator.data
    return {
        "entry": async_redact_data(dict(entry.data), {CONF_HOST}),
        "connected": runtime.client.connected,
        "volume_control_mode": runtime.client.volume_control_mode,
        "last_update_success": runtime.coordinator.last_update_success,
        "last_error": runtime.coordinator.last_error,
        "state": {
            "power": state.power,
            "volume_raw": state.volume_raw,
            "muted": state.muted,
            "source_code": state.source_code,
        },
        "capabilities": [
            "power",
            "volume_state",
            "volume_step",
            "volume_set_safe_emulation",
            "mute",
            "source",
            "listening_mode_groups",
        ],
    }
