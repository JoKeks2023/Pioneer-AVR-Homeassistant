"""Config flow for Pioneer AVR."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

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
    CONF_MAX_VOLUME_RAW,
    CONF_PAUSE_MINUTES,
    CONF_VOLUME_MAX_RAW,
    CONF_VOLUME_MIN_RAW,
    CONF_VOLUME_STEP_DB,
    DEFAULT_ASSUME_OFF_WHEN_UNAVAILABLE,
    DEFAULT_NAME,
    DEFAULT_PAUSE_MINUTES,
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    DEFAULT_VOLUME_STEP_DB,
    DOMAIN,
    MAX_VOLUME_NONE,
    PAUSE_MINUTES_CHOICES,
    VOLUME_STEP_DB_CHOICES,
    db_to_raw,
    max_volume_option,
    max_volume_options,
    parse_max_volume_option,
    raw_to_db,
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

        unique_id = discovery_info.ssdp_udn or discovery_info.ssdp_usn.split("::", 1)[0]
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})
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
                await _async_validate(self._discovered_host, self._discovered_port)
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


def _dropdown(options: list[str], translation_key: str) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            mode=SelectSelectorMode.DROPDOWN,
            translation_key=translation_key,
        )
    )


def _format_db(raw: int | None) -> str:
    if raw is None:
        return "?"
    return f"{raw_to_db(raw):g} dB"


class PioneerAVROptionsFlow(config_entries.OptionsFlow):
    """Options menu: general settings and the volume wizard."""

    def __init__(self) -> None:
        self._quiet_raw: int | None = None
        self._loud_raw: int | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Show the options menu."""
        return self.async_show_menu(
            step_id="init", menu_options=["general", "volume_quiet"]
        )

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Offline behaviour and connection pause length."""
        options = self.config_entry.options
        if user_input is not None:
            return self.async_create_entry(
                data={
                    **options,
                    CONF_ASSUME_OFF_WHEN_UNAVAILABLE: user_input[
                        CONF_ASSUME_OFF_WHEN_UNAVAILABLE
                    ],
                    CONF_PAUSE_MINUTES: int(user_input[CONF_PAUSE_MINUTES]),
                }
            )
        return self.async_show_form(
            step_id="general",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ASSUME_OFF_WHEN_UNAVAILABLE,
                        default=options.get(
                            CONF_ASSUME_OFF_WHEN_UNAVAILABLE,
                            DEFAULT_ASSUME_OFF_WHEN_UNAVAILABLE,
                        ),
                    ): bool,
                    vol.Required(
                        CONF_PAUSE_MINUTES,
                        default=str(
                            options.get(CONF_PAUSE_MINUTES, DEFAULT_PAUSE_MINUTES)
                        ),
                    ): _dropdown(
                        [str(m) for m in PAUSE_MINUTES_CHOICES], "pause_minutes"
                    ),
                }
            ),
        )

    async def async_step_volume_quiet(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Wizard 1/3: capture the quietest level as slider 0 %."""
        return await self._async_capture_step("volume_quiet", user_input)

    async def async_step_volume_loud(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Wizard 2/3: capture the loudest wanted level as slider 100 %."""
        return await self._async_capture_step("volume_loud", user_input)

    async def _async_capture_step(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        state, error = await self._async_read_state()
        if user_input is not None:
            if error is not None:
                errors["base"] = error
            elif state.volume_raw is None:
                errors["base"] = "volume_not_reported"
            elif step_id == "volume_quiet":
                self._quiet_raw = state.volume_raw
                return await self.async_step_volume_loud()
            elif state.volume_raw <= (self._quiet_raw or 0):
                errors["base"] = "invalid_volume_range"
            else:
                self._loud_raw = state.volume_raw
                return await self.async_step_volume_limits()
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={
                "current": _format_db(state.volume_raw if state else None),
                "quiet": _format_db(self._quiet_raw),
            },
        )

    async def async_step_volume_limits(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Wizard 3/3: maximum volume and step size."""
        assert self._quiet_raw is not None and self._loud_raw is not None
        options = self.config_entry.options
        if user_input is not None:
            max_volume = user_input[CONF_MAX_VOLUME_RAW]
            return self.async_create_entry(
                data={
                    **options,
                    CONF_VOLUME_MIN_RAW: self._quiet_raw,
                    CONF_VOLUME_MAX_RAW: self._loud_raw,
                    CONF_MAX_VOLUME_RAW: parse_max_volume_option(max_volume),
                    CONF_VOLUME_STEP_DB: int(user_input[CONF_VOLUME_STEP_DB]),
                }
            )
        # Preselect the loudest level, rounded down to a whole dB.
        loud_option = max_volume_option(
            db_to_raw(math.floor(raw_to_db(self._loud_raw)))
        )
        max_options = max_volume_options()
        return self.async_show_form(
            step_id="volume_limits",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MAX_VOLUME_RAW,
                        default=loud_option
                        if loud_option in max_options
                        else MAX_VOLUME_NONE,
                    ): _dropdown([MAX_VOLUME_NONE, *max_options], "max_volume"),
                    vol.Required(
                        CONF_VOLUME_STEP_DB,
                        default=str(
                            options.get(CONF_VOLUME_STEP_DB, DEFAULT_VOLUME_STEP_DB)
                        ),
                    ): _dropdown(
                        [str(step) for step in VOLUME_STEP_DB_CHOICES], "volume_step_db"
                    ),
                }
            ),
            description_placeholders={
                "quiet": _format_db(self._quiet_raw),
                "loud": _format_db(self._loud_raw),
            },
        )

    async def _async_read_state(
        self,
    ) -> tuple[ReceiverState | None, str | None]:
        """Read the current receiver state, preferring the running client."""
        try:
            runtime = getattr(self.config_entry, "runtime_data", None)
            if runtime is not None:
                await runtime.coordinator.async_resume()
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
