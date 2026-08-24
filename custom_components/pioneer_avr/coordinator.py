"""Data coordinator for Pioneer AVR."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import (
    PioneerAVRClient,
    PioneerAVRConnectionError,
    PioneerAVRProtocolError,
)
from .const import DOMAIN
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

    async def _async_update_data(self) -> ReceiverState:
        try:
            state = await self.client.query_state()
        except (PioneerAVRConnectionError, PioneerAVRProtocolError) as err:
            self.last_error = type(err).__name__
            raise UpdateFailed("Unable to update Pioneer AVR") from err
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
        self._remove_client_listener()
        await self.client.disconnect()
        await super().async_shutdown()
