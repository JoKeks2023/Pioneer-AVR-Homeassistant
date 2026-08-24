"""Config flow for Pioneer AVR."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT

if TYPE_CHECKING:
    from homeassistant.helpers.service_info.ssdp import SsdpServiceInfo

from .client import (
    PioneerAVRClient,
    PioneerAVRConnectionError,
    PioneerAVRProtocolError,
    ReceiverState,
)
from .const import (
    CONF_ASSUME_OFF_WHEN_UNAVAILABLE,
    CONF_CALIBRATE_VOLUME,
    CONF_VOLUME_MAX_RAW,
    CONF_VOLUME_MIN_RAW,
    DEFAULT_ASSUME_OFF_WHEN_UNAVAILABLE,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DOMAIN,
)


async def _async_query_state(host: str, port: int) -> ReceiverState:
    """Query an endpoint and close the validation connection."""
    client = PioneerAVRClient(host, port, DEFAULT_TIMEOUT)
    try:
        return await client.query_state()
    finally:
        await client.disconnect()


async def _async_validate(host: str, port: int) -> None:
    """Validate an endpoint using the normal runtime protocol."""
    await _async_query_state(host, port)


class PioneerAVRConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Pioneer AVR config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_host: str | None = None
        self._discovered_port = DEFAULT_PORT
        self._discovered_name = DEFAULT_NAME

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow."""
        return PioneerAVROptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle manual setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            if self._endpoint_configured(host, port):
                return self.async_abort(reason="already_configured")
            try:
                await _async_validate(host, port)
            except PioneerAVRConnectionError:
                errors["base"] = "cannot_connect"
            except PioneerAVRProtocolError:
                errors["base"] = "invalid_receiver"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=DEFAULT_NAME,
                    data={CONF_HOST: host, CONF_PORT: port},
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HOST,
                    default=(user_input or {}).get(CONF_HOST, ""),
                ): str,
                vol.Required(
                    CONF_PORT,
                    default=(user_input or {}).get(CONF_PORT, DEFAULT_PORT),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_ssdp(
        self, discovery_info: SsdpServiceInfo
    ) -> config_entries.ConfigFlowResult:
        """Handle a precisely matched VSX-827 SSDP discovery."""
        host = urlsplit(discovery_info.ssdp_location).hostname
        if host is None:
            return self.async_abort(reason="invalid_discovery")

        upnp = discovery_info.upnp
        model = str(upnp.get("modelName", "")).strip()
        manufacturer = str(upnp.get("manufacturer", "")).strip()
        if model != "VSX-827/SYXE8" or manufacturer != "PIONEER CORPORATION":
            return self.async_abort(reason="invalid_discovery")

        port_value = upnp.get("X_ipRemoteTcpPort", DEFAULT_PORT)
        try:
            port = int(port_value)
        except (TypeError, ValueError):
            port = DEFAULT_PORT

        unique_id = discovery_info.ssdp_udn or discovery_info.ssdp_usn.split(
            "::", 1
        )[0]
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: host, CONF_PORT: port}
        )
        if self._endpoint_configured(host, port):
            return self.async_abort(reason="already_configured")

        self._discovered_host = host
        self._discovered_port = port
        self._discovered_name = str(upnp.get("friendlyName", DEFAULT_NAME)).strip()
        self.context["title_placeholders"] = {"name": self._discovered_name}
        return await self.async_step_ssdp_confirm()

    async def async_step_ssdp_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Confirm a discovered receiver."""
        if self._discovered_host is None:
            return self.async_abort(reason="invalid_discovery")
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _async_validate(
                    self._discovered_host, self._discovered_port
                )
            except PioneerAVRConnectionError:
                errors["base"] = "cannot_connect"
            except PioneerAVRProtocolError:
                errors["base"] = "invalid_receiver"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=self._discovered_name,
                    data={
                        CONF_HOST: self._discovered_host,
                        CONF_PORT: self._discovered_port,
                    },
                )
        return self.async_show_form(
            step_id="ssdp_confirm",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"name": self._discovered_name},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Update receiver connection settings."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            if self._endpoint_configured(host, port, exclude_entry_id=entry.entry_id):
                return self.async_abort(reason="already_configured")
            try:
                await _async_validate(host, port)
            except PioneerAVRConnectionError:
                errors["base"] = "cannot_connect"
            except PioneerAVRProtocolError:
                errors["base"] = "invalid_receiver"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_HOST: host, CONF_PORT: port},
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HOST,
                    default=(user_input or {}).get(CONF_HOST, entry.data[CONF_HOST]),
                ): str,
                vol.Required(
                    CONF_PORT,
                    default=(user_input or {}).get(
                        CONF_PORT, entry.data.get(CONF_PORT, DEFAULT_PORT)
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            }
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )

    def _endpoint_configured(
        self, host: str, port: int, exclude_entry_id: str | None = None
    ) -> bool:
        normalized_host = host.casefold()
        return any(
            entry.entry_id != exclude_entry_id
            and entry.data.get(CONF_HOST, "").casefold() == normalized_host
            and entry.data.get(CONF_PORT, DEFAULT_PORT) == port
            for entry in self._async_current_entries()
        )


class PioneerAVROptionsFlow(config_entries.OptionsFlow):
    """Configure offline behavior and calibrated volume endpoints."""

    def __init__(self) -> None:
        self._pending_options: dict[str, Any] = {}
        self._calibration_min_raw: int | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure receiver behavior or start volume calibration."""
        if user_input is not None:
            self._pending_options = dict(self.config_entry.options)
            self._pending_options[CONF_ASSUME_OFF_WHEN_UNAVAILABLE] = user_input[
                CONF_ASSUME_OFF_WHEN_UNAVAILABLE
            ]
            if user_input[CONF_CALIBRATE_VOLUME]:
                return await self.async_step_calibration_min()
            return self.async_create_entry(title="", data=self._pending_options)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ASSUME_OFF_WHEN_UNAVAILABLE,
                        default=self.config_entry.options.get(
                            CONF_ASSUME_OFF_WHEN_UNAVAILABLE,
                            DEFAULT_ASSUME_OFF_WHEN_UNAVAILABLE,
                        ),
                    ): bool,
                    vol.Required(CONF_CALIBRATE_VOLUME, default=False): bool,
                }
            ),
        )

    async def async_step_calibration_min(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Capture the quiet endpoint selected on the receiver."""
        errors: dict[str, str] = {}
        if user_input is not None:
            state, error = await self._async_read_calibration_state()
            if error is not None:
                errors["base"] = error
            elif state.volume_raw is None:
                errors["base"] = "volume_not_reported"
            else:
                self._calibration_min_raw = state.volume_raw
                return await self.async_step_calibration_max()
        return self.async_show_form(
            step_id="calibration_min",
            data_schema=vol.Schema({}),
            errors=errors,
        )

    async def async_step_calibration_max(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Capture the loud endpoint selected on the receiver."""
        assert self._calibration_min_raw is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            state, error = await self._async_read_calibration_state()
            if error is not None:
                errors["base"] = error
            elif state.volume_raw is None:
                errors["base"] = "volume_not_reported"
            elif state.volume_raw <= self._calibration_min_raw:
                errors["base"] = "invalid_volume_range"
            else:
                self._pending_options[CONF_VOLUME_MIN_RAW] = (
                    self._calibration_min_raw
                )
                self._pending_options[CONF_VOLUME_MAX_RAW] = state.volume_raw
                return self.async_create_entry(
                    title="", data=self._pending_options
                )
        return self.async_show_form(
            step_id="calibration_max",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={
                "minimum": str(self._calibration_min_raw)
            },
        )

    async def _async_read_calibration_state(
        self,
    ) -> tuple[ReceiverState | None, str | None]:
        """Read the current receiver state for a calibration step."""
        try:
            runtime = getattr(self.config_entry, "runtime_data", None)
            if runtime is not None:
                state = await runtime.client.query_state()
            else:
                state = await _async_query_state(
                    self.config_entry.data[CONF_HOST],
                    self.config_entry.data.get(CONF_PORT, DEFAULT_PORT),
                )
        except PioneerAVRConnectionError:
            return None, "cannot_connect"
        except PioneerAVRProtocolError:
            return None, "invalid_receiver"
        except Exception:  # noqa: BLE001
            return None, "unknown"
        return state, None
