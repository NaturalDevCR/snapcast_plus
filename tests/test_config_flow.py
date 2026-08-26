"""Tests for the Snapcast config flow."""

import socket
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.snapcast.const import DOMAIN

USER_INPUT = {CONF_HOST: "127.0.0.1", CONF_PORT: 1705}


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """A reachable server creates an entry titled like the official one."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    with patch(
        "snapcast.control.create_server",
        AsyncMock(return_value=MagicMock()),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Snapcast"
    assert result["data"] == USER_INPUT


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    """OSError surfaces as cannot_connect and the form is shown again."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    with patch(
        "snapcast.control.create_server",
        AsyncMock(side_effect=OSError),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_invalid_host(hass: HomeAssistant) -> None:
    """DNS failure surfaces as invalid_host."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    with patch(
        "snapcast.control.create_server",
        AsyncMock(side_effect=socket.gaierror),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_host"}


async def test_reconfigure_updates_existing_entry(hass: HomeAssistant) -> None:
    """Reconfigure validates and updates the existing config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Snapcast",
        data=USER_INPUT,
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )
    assert result["type"] is FlowResultType.FORM

    with patch(
        "snapcast.control.create_server",
        AsyncMock(return_value=MagicMock()),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "snapcast.local", "port": 1704}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_success"
    assert entry.data == {"host": "snapcast.local", "port": 1704}


async def test_reconfigure_reports_connection_error(hass: HomeAssistant) -> None:
    """A failed reconfigure leaves the form open with a translated error."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Snapcast",
        data=USER_INPUT,
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )

    with patch(
        "snapcast.control.create_server",
        AsyncMock(side_effect=OSError),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "snapcast.local", "port": 1704}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data == USER_INPUT
