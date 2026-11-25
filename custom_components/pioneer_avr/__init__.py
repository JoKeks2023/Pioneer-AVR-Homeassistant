"""Pioneer AVR Home Assistant integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .const import (
    CONF_ASSUME_OFF_WHEN_UNAVAILABLE,
    CONF_MAX_VOLUME_RAW,
    CONF_VOLUME_MAX_RAW,
    CONF_VOLUME_MIN_RAW,
    CONF_VOLUME_STEP_DB,
    DEFAULT_ASSUME_OFF_WHEN_UNAVAILABLE,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    VOLUME_MAX,
    VOLUME_MIN,
)

PLATFORMS = ["media_player", "switch"]


@dataclass(slots=True)
class PioneerAVRRuntimeData:
    """Runtime objects associated with a config entry."""

    client: Any
    coordinator: Any


async def async_setup_entry(hass: Any, entry: Any) -> bool:
    """Set up Pioneer AVR from a config entry."""
    from homeassistant.const import CONF_HOST
    from homeassistant.exceptions import ConfigEntryNotReady

    from .client import PioneerAVRClient
    from .coordinator import PioneerAVRCoordinator

    client = PioneerAVRClient(
        entry.data[CONF_HOST],
        entry.data.get("port", DEFAULT_PORT),
        DEFAULT_TIMEOUT,
        volume_min_raw=entry.options.get(CONF_VOLUME_MIN_RAW, VOLUME_MIN),
        volume_max_raw=entry.options.get(CONF_VOLUME_MAX_RAW, VOLUME_MAX),
        max_volume_raw=entry.options.get(CONF_MAX_VOLUME_RAW),
        volume_step_db=entry.options.get(CONF_VOLUME_STEP_DB, 1),
    )
    assume_off = entry.options.get(
        CONF_ASSUME_OFF_WHEN_UNAVAILABLE,
        DEFAULT_ASSUME_OFF_WHEN_UNAVAILABLE,
    )
    coordinator = PioneerAVRCoordinator(
        hass,
        client,
        assume_off_when_unavailable=assume_off,
        update_interval=DEFAULT_SCAN_INTERVAL,
    )
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        if not assume_off:
            await coordinator.async_shutdown()
            raise
        coordinator.async_assume_power_off()
    entry.runtime_data = PioneerAVRRuntimeData(client, coordinator)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload_entry(hass: Any, entry: Any) -> None:
    """Reload the entry after options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: Any, entry: Any) -> bool:
    """Unload a Pioneer AVR config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.coordinator.async_shutdown()
    return True
