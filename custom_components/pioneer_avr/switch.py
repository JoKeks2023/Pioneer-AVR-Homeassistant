"""Switch that releases the receiver's single control connection."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_PAUSE_MINUTES, DEFAULT_PAUSE_MINUTES
from .coordinator import PioneerAVRCoordinator, device_info


async def async_setup_entry(
    hass: Any,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the control-connection switch."""
    async_add_entities(
        [PioneerAVRConnectionSwitch(entry, entry.runtime_data.coordinator)]
    )


class PioneerAVRConnectionSwitch(
    CoordinatorEntity[PioneerAVRCoordinator], SwitchEntity
):
    """On: Home Assistant holds the connection. Off: released for a while."""

    _attr_has_entity_name = True
    _attr_translation_key = "control_connection"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, coordinator: PioneerAVRCoordinator) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_control_connection"
        self._attr_device_info = device_info(entry)

    @property
    def available(self) -> bool:
        """Stay usable even while the receiver itself is unreachable."""
        return True

    @property
    def is_on(self) -> bool:
        """Return whether Home Assistant holds the control connection."""
        return not self.coordinator.paused

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose when a pause ends."""
        until = self.coordinator.paused_until
        return {"paused_until": until.isoformat() if until else None}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_resume()

    async def async_turn_off(self, **kwargs: Any) -> None:
        minutes = int(
            self._entry.options.get(CONF_PAUSE_MINUTES, DEFAULT_PAUSE_MINUTES)
        )
        await self.coordinator.async_pause(minutes)
