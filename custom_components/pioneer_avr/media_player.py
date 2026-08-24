"""AV receiver entity for Pioneer AVR."""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL, SOUND_MODE_COMMANDS, SOURCE_CODES
from .coordinator import PioneerAVRCoordinator


async def async_setup_entry(
    hass: Any,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Pioneer AV receiver entity."""
    async_add_entities([PioneerAVRMediaPlayer(entry, entry.runtime_data.coordinator)])


class PioneerAVRMediaPlayer(
    CoordinatorEntity[PioneerAVRCoordinator], MediaPlayerEntity
):
    """Representation of a Pioneer VSX-827 AV receiver."""

    _attr_device_class = MediaPlayerDeviceClass.RECEIVER
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.SELECT_SOUND_MODE
    )

    def __init__(self, entry: ConfigEntry, coordinator: PioneerAVRCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_main"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=entry.title,
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )

    @property
    def state(self) -> MediaPlayerState | None:
        """Return receiver power state."""
        if self.coordinator.data.power is None:
            return None
        return (
            MediaPlayerState.ON
            if self.coordinator.data.power
            else MediaPlayerState.OFF
        )

    @property
    def volume_level(self) -> float | None:
        """Return normalized receiver volume."""
        return self.coordinator.client.volume_level

    @property
    def available(self) -> bool:
        """Keep a powered-off receiver available when configured to do so."""
        return self.coordinator.receiver_available

    @property
    def assumed_state(self) -> bool:
        """Indicate when off is inferred from network disappearance."""
        return self.coordinator.assumed_off

    @property
    def is_volume_muted(self) -> bool | None:
        """Return receiver mute state."""
        return self.coordinator.data.muted

    @property
    def source(self) -> str | None:
        """Return current receiver input."""
        return self.coordinator.data.source

    @property
    def source_list(self) -> list[str]:
        """Return receiver inputs that can be selected directly."""
        return [name for name, code in SOURCE_CODES.items() if code not in {"46", "47"}]

    @property
    def sound_mode(self) -> None:
        """Return no mode because the VSX-827 has no mode status query."""
        return None

    @property
    def sound_mode_list(self) -> list[str]:
        """Return documented listening-mode command groups."""
        return list(SOUND_MODE_COMMANDS)

    async def async_turn_on(self) -> None:
        await self.coordinator.client.set_power(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        await self.coordinator.client.set_power(False)
        self.coordinator.async_assume_power_off()

    async def async_volume_up(self) -> None:
        await self.coordinator.client.volume_up()
        await self.coordinator.async_request_refresh()

    async def async_volume_down(self) -> None:
        await self.coordinator.client.volume_down()
        await self.coordinator.async_request_refresh()

    async def async_mute_volume(self, mute: bool) -> None:
        await self.coordinator.client.set_mute(mute)
        await self.coordinator.async_request_refresh()

    async def async_select_source(self, source: str) -> None:
        await self.coordinator.client.select_input(source)
        await self.coordinator.async_request_refresh()

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        await self.coordinator.client.set_sound_mode(sound_mode)
