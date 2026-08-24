"""Data coordinator for Pioneer AVR."""

from __future__ import annotations

import logging
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
        update_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )
        self.client = client
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
        return state

    @callback
    def _async_handle_push(self, state: ReceiverState) -> None:
        """Apply an unsolicited state response immediately."""
        self.async_set_updated_data(state)

    async def async_shutdown(self) -> None:
        """Release client resources."""
        self._remove_client_listener()
        await self.client.disconnect()

