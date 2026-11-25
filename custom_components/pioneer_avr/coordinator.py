"""Data coordinator for Pioneer AVR."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import (
    PioneerAVRClient,
    PioneerAVRConnectionError,
    PioneerAVRProtocolError,
)
from .const import DOMAIN, MANUFACTURER, MODEL
from .protocol import ReceiverState

_LOGGER = logging.getLogger(__name__)


class PioneerAVRCoordinator(DataUpdateCoordinator[ReceiverState]):
    """Coordinate polling and pushed state for a Pioneer receiver."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: PioneerAVRClient,
        *,
        assume_off_when_unavailable: bool,
        update_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )
        self.client = client
        self.assume_off_when_unavailable = assume_off_when_unavailable
        self.assumed_off = False
        self.last_error: str | None = None
        self._remove_client_listener = client.add_state_listener(
            self._async_handle_push
        )
        self.paused_until: datetime | None = None
        self._cancel_resume: Callable[[], None] | None = None

    @property
    def paused(self) -> bool:
        """Return whether the control connection is released on purpose."""
        return self.paused_until is not None

    async def async_pause(self, minutes: int) -> None:
        """Release the only receiver connection so another client can use it."""
        self._cancel_scheduled_resume()
        self.paused_until = dt_util.utcnow() + timedelta(minutes=minutes)
        await self.client.disconnect()
        self._cancel_resume = async_call_later(
            self.hass, minutes * 60, self._async_resume_later
        )
        _LOGGER.debug("Control connection paused for %d minutes", minutes)
        self.async_update_listeners()

    async def async_resume(self) -> None:
        """Reconnect after a pause; no-op when not paused."""
        if not self.paused:
            return
        self._cancel_scheduled_resume()
        self.paused_until = None
        _LOGGER.debug("Control connection resumed")
        await self.async_refresh()

    async def _async_resume_later(self, _now: datetime) -> None:
        self._cancel_resume = None
        await self.async_resume()

    def _cancel_scheduled_resume(self) -> None:
        if self._cancel_resume is not None:
            self._cancel_resume()
            self._cancel_resume = None

    async def _async_update_data(self) -> ReceiverState:
        if self.paused:
            # Keep the last known state without touching the receiver.
            return self.data if self.data is not None else self.client.state
        try:
            state = await self.client.query_state()
        except (PioneerAVRConnectionError, PioneerAVRProtocolError) as err:
            self.last_error = type(err).__name__
            raise UpdateFailed(f"Unable to update Pioneer AVR: {err}") from err
        self.last_error = None
        self.assumed_off = False
        return state

    @callback
    def _async_handle_push(self, state: ReceiverState) -> None:
        """Apply an unsolicited state response immediately."""
        self.assumed_off = False
        self.async_set_updated_data(state)

    @property
    def receiver_available(self) -> bool:
        """Return availability while preserving an assumed off state."""
        return self.last_update_success or (
            self.assume_off_when_unavailable
            and self.data is not None
            and self.data.power is False
        )

    @callback
    def async_assume_power_off(self) -> None:
        """Keep the entity off when the receiver drops off the network."""
        state = self.data if self.data is not None else self.client.state
        self.assumed_off = True
        self.async_set_updated_data(replace(state, power=False))

    async def async_shutdown(self) -> None:
        """Release client resources."""
        self._cancel_scheduled_resume()
        self._remove_client_listener()
        await self.client.disconnect()
        await super().async_shutdown()


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return the shared device description for all entities of an entry."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        manufacturer=MANUFACTURER,
        model=MODEL,
        name=entry.title,
        configuration_url=f"http://{entry.data[CONF_HOST]}",
    )
