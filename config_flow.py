"""Snapcast config flow."""

import logging
import socket

import snapcast.control
from snapcast.control.server import CONTROL_PORT
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT

from .const import DEFAULT_TITLE, DOMAIN

_LOGGER = logging.getLogger(__name__)

SNAPCAST_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=CONTROL_PORT): int,
    }
)


class SnapcastConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Snapcast."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Handle the initial (and only) step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match(user_input)
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            error = await self._async_validate_connection(host, port)
            if error == "invalid_host":
                errors["base"] = "invalid_host"
            elif error == "cannot_connect":
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=DEFAULT_TITLE, data=user_input
                )

        return self.async_show_form(
            step_id="user",
            data_schema=SNAPCAST_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict | None = None
    ) -> ConfigFlowResult:
        """Handle updating the host and port of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await self._async_validate_connection(
                user_input[CONF_HOST], user_input[CONF_PORT]
            )
            if error is None:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=user_input,
                    reason="reconfigure_success",
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=entry.data.get(CONF_HOST, "")
                    ): str,
                    vol.Required(
                        CONF_PORT, default=entry.data.get(CONF_PORT, CONTROL_PORT)
                    ): int,
                }
            ),
            errors=errors,
        )

    async def _async_validate_connection(self, host: str, port: int) -> str | None:
        """Probe a Snapcast endpoint and return a translated error key."""
        try:
            client = await snapcast.control.create_server(
                self.hass.loop, host, port, reconnect=False
            )
        except socket.gaierror:
            return "invalid_host"
        except OSError:
            return "cannot_connect"
        client.stop()
        return None
