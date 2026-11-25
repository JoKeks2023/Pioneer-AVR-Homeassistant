"""AV receiver entity for Pioneer AVR."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import PioneerAVRConnectionError, PioneerAVRError
from .const import DOMAIN, SOUND_MODE_COMMANDS, SOURCE_CODES
from .coordinator import PioneerAVRCoordinator, device_info


async def _run(command: Awaitable[None]) -> None:
    """Run a client command and report failures as Home Assistant errors."""
    try:
        await command
    except PioneerAVRError as err:
        key = (
            "cannot_connect"
            if isinstance(err, PioneerAVRConnectionError)
            else "command_failed"
        )
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders={"error": str(err) or type(err).__name__},
        ) from err


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
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.SELECT_SOUND_MODE
    )

    def __init__(self, entry: ConfigEntry, coordinator: PioneerAVRCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_main"
        self._attr_device_info = device_info(entry)

    @property
    def state(self) -> MediaPlayerState | None:
        """Return receiver power state."""
        if self.coordinator.data.power is None:
            return None
        return (
            MediaPlayerState.ON if self.coordinator.data.power else MediaPlayerState.OFF
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
        """Indicate inferred state: off after disappearance, or paused."""
        return self.coordinator.assumed_off or self.coordinator.paused

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

    async def _execute(self, command: Callable[[], Awaitable[None]]) -> None:
        """Resume a paused connection, then run the command."""
        await self.coordinator.async_resume()
        await _run(command())

    async def async_turn_on(self) -> None:
        await self._execute(lambda: self.coordinator.client.set_power(True))
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        await self._execute(lambda: self.coordinator.client.set_power(False))
        self.coordinator.async_assume_power_off()

    async def async_volume_up(self) -> None:
        await self._execute(lambda: self.coordinator.client.volume_up())
        await self.coordinator.async_request_refresh()

    async def async_volume_down(self) -> None:
        await self._execute(lambda: self.coordinator.client.volume_down())
        await self.coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float) -> None:
        await self._execute(lambda: self.coordinator.client.set_volume(volume))
        await self.coordinator.async_request_refresh()

    async def async_mute_volume(self, mute: bool) -> None:
        await self._execute(lambda: self.coordinator.client.set_mute(mute))
        await self.coordinator.async_request_refresh()

    async def async_select_source(self, source: str) -> None:
        await self._execute(lambda: self.coordinator.client.select_input(source))
        await self.coordinator.async_request_refresh()

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        await self._execute(lambda: self.coordinator.client.set_sound_mode(sound_mode))
