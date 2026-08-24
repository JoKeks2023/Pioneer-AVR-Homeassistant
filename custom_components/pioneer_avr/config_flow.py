"""Config flow for Pioneer AVR."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.ssdp import SsdpServiceInfo
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.data_entry_flow import FlowResult

from .client import (
    PioneerAVRClient,
    PioneerAVRConnectionError,
    PioneerAVRProtocolError,
)
from .const import DEFAULT_NAME, DEFAULT_PORT, DEFAULT_TIMEOUT, DOMAIN


async def _async_validate(host: str, port: int) -> None:
    """Validate an endpoint and close the validation connection."""
    client = PioneerAVRClient(host, port, DEFAULT_TIMEOUT)
    try:
        await client.query_state()
    finally:
        await client.disconnect()


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
    ) -> FlowResult:
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
    ) -> FlowResult:
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
    ) -> FlowResult:
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
    ) -> FlowResult:
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
    """Placeholder options flow for future model-specific capabilities."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Explain that connection changes use reconfigure."""
        if user_input is not None:
            return self.async_create_entry(title="", data={})
        return self.async_show_form(step_id="init", data_schema=vol.Schema({}))
