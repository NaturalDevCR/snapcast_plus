"""Diagnostics for Snapcast Plus config entries."""

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import SnapcastUpdateCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry[SnapcastUpdateCoordinator]
) -> dict[str, Any]:
    """Return redacted health information for a Snapcast config entry."""
    del hass
    coordinator = entry.runtime_data
    server = coordinator.server
    historical_groups = sum(
        physical_id is None for physical_id in coordinator.group_bindings.values()
    )

    return {
        "connection": {
            "connected": coordinator.connected,
            "last_update_success": coordinator.last_update_success,
            "reconnect_delay": coordinator.reconnect_delay,
            "reconnect_attempts": coordinator.reconnect_attempts,
            "last_response_time": coordinator.last_response_time,
            "last_disconnect_time": coordinator.last_disconnect_time,
            "last_error_type": coordinator.last_connection_error,
        },
        "entities": {
            "clients": len(server.clients) if server is not None else 0,
            "groups": len(server.groups) if server is not None else 0,
            "stale_clients": sum(
                coordinator.client_is_stale(client) for client in server.clients
            )
            if server is not None
            else 0,
        },
        "persistence": {
            "zones": len(coordinator.zones),
            "group_bindings": len(coordinator.group_bindings),
            "historical_groups": historical_groups,
        },
    }
