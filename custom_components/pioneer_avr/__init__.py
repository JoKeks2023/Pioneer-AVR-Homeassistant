"""Pioneer AVR Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .const import DEFAULT_PORT, DEFAULT_SCAN_INTERVAL, DEFAULT_TIMEOUT

PLATFORMS = ["media_player"]


@dataclass(slots=True)
class PioneerAVRRuntimeData:
    """Runtime objects associated with a config entry."""

    client: Any
    coordinator: Any


async def async_setup_entry(hass: Any, entry: Any) -> bool:
    """Set up Pioneer AVR from a config entry."""
    from homeassistant.const import CONF_HOST

    from .client import PioneerAVRClient
    from .coordinator import PioneerAVRCoordinator

    client = PioneerAVRClient(
        entry.data[CONF_HOST],
        entry.data.get("port", DEFAULT_PORT),
        DEFAULT_TIMEOUT,
    )
    coordinator = PioneerAVRCoordinator(
        hass, client, update_interval=DEFAULT_SCAN_INTERVAL
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = PioneerAVRRuntimeData(client, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: Any, entry: Any) -> bool:
    """Unload a Pioneer AVR config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.coordinator.async_shutdown()
    return True
