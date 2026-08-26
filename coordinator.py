"""Data update coordinator for Snapcast server with auto-reconnection."""

import asyncio
import logging
from datetime import timedelta
from uuid import uuid4

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from snapcast.control.server import Snapserver

_LOGGER = logging.getLogger(__name__)

type SnapcastConfigEntry = ConfigEntry["SnapcastUpdateCoordinator"]

MAX_RECONNECT_DELAY = 60
POLL_INTERVAL_SECONDS = 45


class SnapcastUpdateCoordinator(DataUpdateCoordinator[None]):
    """Data update coordinator with push updates and polling fallback.

    Key design decisions vs official integration:
    - Self-managed reconnection (reconnect=False on Snapserver) so that
      all Snapclient/Snapgroup objects are always fresh, avoiding stale
      callback references.
    - Exponential backoff on reconnect attempts (1s -> 2s -> 4s -> ... -> 60s).
    - A 45-second polling fallback so entities never get stuck even if
      push callbacks are missed.
    - Entity availability is derived from last_update_success.
    """

    config_entry: SnapcastConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: SnapcastConfigEntry) -> None:
        """Initialize coordinator."""
        host = config_entry.data[CONF_HOST]
        port = config_entry.data[CONF_PORT]

        super().__init__(
            hass,
            logger=_LOGGER,
            config_entry=config_entry,
            name=f"{host}:{port}",
            update_interval=timedelta(seconds=POLL_INTERVAL_SECONDS),
        )
        self.host = host
        self.port = port
        self._server: Snapserver | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._reconnect_delay = 1
        # Connection state must live outside last_update_success: the base
        # DataUpdateCoordinator overwrites last_update_success after every
        # poll, so it cannot be trusted as the "are we connected" signal.
        self._connected = False
        self.last_update_success = False
        self.group_bindings: dict[str, str | None] = {}
        self.group_members: dict[str, frozenset[str]] = {}
        self._group_store = Store[dict](hass, 1, f"snapcast_groups.{config_entry.entry_id}")
        self.zones: dict[str, dict[str, str | list[str]]] = {}
        self._zone_store = Store[dict](hass, 1, f"snapcast_zones.{config_entry.entry_id}")

    @property
    def server(self) -> Snapserver | None:
        """Get the Snapserver object."""
        return self._server

    @property
    def connected(self) -> bool:
        """Return whether the coordinator considers the server connected."""
        return self._connected

    @property
    def reconnect_delay(self) -> int:
        """Return the current exponential reconnect delay in seconds."""
        return self._reconnect_delay

    @property
    def host_id(self) -> str:
        """Unique host identifier: host:port."""
        return f"{self.host}:{self.port}"

    async def _async_setup(self) -> None:
        """Perform async setup for the coordinator."""
        if saved := await self._group_store.async_load():
            self.group_bindings = saved.get("bindings", {})
            self.group_members = {
                key: frozenset(value) for key, value in saved.get("members", {}).items()
            }
        if saved_zones := await self._zone_store.async_load():
            self.zones = saved_zones.get("zones", {})
        await self._connect()

    def reconcile_groups(self) -> None:
        """Rebind logical group IDs to current physical groups and persist them."""
        if self._server is None:
            return
        current = {group.identifier: frozenset(group.clients) for group in self._server.groups}
        for logical, physical in list(self.group_bindings.items()):
            if physical in current:
                self.group_members[logical] = current[physical]
            else:
                self.group_bindings[logical] = None
        for physical, members in current.items():
            if physical in self.group_bindings.values():
                continue
            exact = [
                logical
                for logical, old_members in self.group_members.items()
                if self.group_bindings.get(logical) is None
                and old_members == members
            ]
            if len(exact) == 1:
                logical = exact[0]
            else:
                logical = physical
            self.group_bindings[logical] = physical
            self.group_members[logical] = members
        self.hass.async_create_task(self._group_store.async_save({
            "bindings": self.group_bindings,
            "members": {key: sorted(value) for key, value in self.group_members.items()},
        }))

    async def async_reassign_group(
        self, old_logical_id: str, new_logical_id: str
    ) -> None:
        """Move an active group binding to an unavailable logical identity."""
        if self.group_bindings.get(old_logical_id) is not None:
            raise ValueError("The old group is still bound to a live Snapcast group.")
        physical_id = self.group_bindings.get(new_logical_id)
        if physical_id is None:
            raise ValueError("The new group is not currently available.")

        self.group_bindings[old_logical_id] = physical_id
        self.group_members[old_logical_id] = self.group_members[new_logical_id]
        del self.group_bindings[new_logical_id]
        self.group_members.pop(new_logical_id, None)
        await self._group_store.async_save({
            "bindings": self.group_bindings,
            "members": {
                key: sorted(members) for key, members in self.group_members.items()
            },
        })

    async def async_cleanup_groups(self) -> list[str]:
        """Delete unavailable historical group identities from storage."""
        removed = [
            logical_id
            for logical_id, physical_id in self.group_bindings.items()
            if physical_id is None
        ]
        if not removed:
            return []

        for logical_id in removed:
            self.group_bindings.pop(logical_id, None)
            self.group_members.pop(logical_id, None)
        await self._group_store.async_save({
            "bindings": self.group_bindings,
            "members": {
                key: sorted(members) for key, members in self.group_members.items()
            },
        })
        self.async_update_listeners()
        return removed

    def logical_group_id_from_unique_id(self, unique_id: str) -> str | None:
        """Return the stored logical ID represented by a group unique ID."""
        from .const import GROUP_PREFIX

        prefix = f"{GROUP_PREFIX}{self.host_id}_"
        if not unique_id.startswith(prefix):
            return None
        logical_id = unique_id.removeprefix(prefix)
        return logical_id if logical_id in self.group_bindings else None

    async def async_create_zone(self, name: str, client_ids: list[str]) -> str:
        """Persist a user-defined zone and notify entity listeners."""
        zone_id = uuid4().hex
        self.zones[zone_id] = {
            "name": name,
            "client_ids": list(dict.fromkeys(client_ids)),
        }
        await self._async_save_zones()
        self.async_update_listeners()
        return zone_id

    async def async_update_zone(
        self, zone_id: str, name: str | None, client_ids: list[str] | None
    ) -> None:
        """Persist edits to a user-defined zone."""
        zone = self.zones[zone_id]
        if name is not None:
            zone["name"] = name
        if client_ids is not None:
            zone["client_ids"] = list(dict.fromkeys(client_ids))
        await self._async_save_zones()
        self.async_update_listeners()

    async def async_remove_zone(self, zone_id: str) -> None:
        """Remove a persisted user-defined zone."""
        del self.zones[zone_id]
        await self._async_save_zones()

    async def _async_save_zones(self) -> None:
        """Write the current zone definitions to Home Assistant storage."""
        await self._zone_store.async_save({"zones": self.zones})

    def client_id_from_unique_id(self, unique_id: str) -> str | None:
        """Return a current client ID represented by an entity unique ID."""
        from .const import CLIENT_PREFIX

        prefix = f"{CLIENT_PREFIX}{self.host_id}_"
        if not unique_id.startswith(prefix):
            return None
        client_id = unique_id.removeprefix(prefix)
        if self._server is None:
            return None
        try:
            self._server.client(client_id)
        except (KeyError, AttributeError):
            return None
        return client_id

    def zone_id_from_unique_id(self, unique_id: str) -> str | None:
        """Return the stored zone ID represented by a zone unique ID."""
        from .const import ZONE_PREFIX

        prefix = f"{ZONE_PREFIX}{self.host_id}_"
        if not unique_id.startswith(prefix):
            return None
        zone_id = unique_id.removeprefix(prefix)
        return zone_id if zone_id in self.zones else None

    async def _connect(self) -> None:
        """Create a fresh Snapserver and connect to the host."""
        self._server = Snapserver(self.hass.loop, self.host, self.port, False)
        self._server.set_on_update_callback(self._on_update)
        self._server.set_new_client_callback(self._on_update)
        self._server.set_on_connect_callback(self._on_connect)
        self._server.set_on_disconnect_callback(self._on_disconnect)
        await self._server.start()
        self._connected = True
        self._wire_object_callbacks()

    def _wire_object_callbacks(self) -> None:
        """Subscribe to every client's and group's own push callback.

        python-snapcast delivers fine-grained changes (Client.OnVolumeChanged,
        Group.OnMute, ...) through the object's own callback, not through
        set_on_update_callback (Server.OnUpdate only). Without this, an
        individual client's volume changing does not refresh the group
        slider and vice versa, since no coordinator listener ever fires.
        """
        if self._server is None:
            return
        for client in self._server.clients:
            client.set_callback(self._on_object_update)
        for group in self._server.groups:
            group.set_callback(self._on_object_update)

    def _on_object_update(self, _obj) -> None:
        """Snapserver: a single client or group object changed (push)."""
        self.last_update_success = True
        self.async_update_listeners()

    def _on_update(self) -> None:
        """Snapserver: data updated (push)."""
        self.last_update_success = True
        self._wire_object_callbacks()
        self.async_update_listeners()

    def _on_connect(self) -> None:
        """Snapserver: websocket connected."""
        self._connected = True
        self.last_update_success = True
        self._reconnect_delay = 1
        _LOGGER.info(
            "Connected to Snapcast server at %s:%s", self.host, self.port
        )
        self.async_update_listeners()

    def _on_disconnect(self, ex: Exception) -> None:
        """Snapserver: websocket disconnected.  Start reconnection loop."""
        self._connected = False
        self.last_update_success = False
        self.async_update_listeners()
        _LOGGER.warning(
            "Disconnected from Snapcast server at %s:%s: %s",
            self.host,
            self.port,
            ex,
        )
        if self.hass.is_stopping:
            return
        if self._reconnect_task is None or self._reconnect_task.done():
            # Background task: a long-lived retry loop must not block
            # async_block_till_done() or delay HA shutdown; HA cancels
            # background tasks automatically on stop.
            self._reconnect_task = self.hass.async_create_background_task(
                self._reconnect_loop(),
                name=f"snapcast reconnect {self.host_id}",
            )

    async def _reconnect_loop(self) -> None:
        """Continuously attempt reconnection with exponential backoff."""
        while not self._connected:
            delay = min(self._reconnect_delay, MAX_RECONNECT_DELAY)
            _LOGGER.debug(
                "Reconnecting to %s:%s in %s seconds",
                self.host,
                self.port,
                delay,
            )
            await asyncio.sleep(delay)
            self._reconnect_delay = min(
                self._reconnect_delay * 2, MAX_RECONNECT_DELAY
            )

            try:
                await self._do_reconnect()
            except Exception:
                _LOGGER.exception(
                    "Reconnect to %s:%s failed, retrying",
                    self.host,
                    self.port,
                )

    async def _do_reconnect(self) -> None:
        """Attempt a single reconnection cycle."""
        if self._connected:
            return

        _LOGGER.debug("Attempting reconnect to %s:%s", self.host, self.port)

        if self._server is not None:
            old = self._server
            self._server = None
            old.set_on_update_callback(None)
            old.set_on_connect_callback(None)
            old.set_on_disconnect_callback(None)
            old.set_new_client_callback(None)
            old.stop()

        await self._connect()

    async def _async_update_data(self) -> None:
        """Polling fallback — push data to entities if connected.

        Raising UpdateFailed while disconnected keeps last_update_success
        False; the base coordinator would otherwise reset it to True after
        this method returns, marking entities available with stale data and
        aborting the reconnect loop.
        """
        if not self._connected or self._server is None:
            raise UpdateFailed(
                f"Not connected to Snapcast server at {self.host_id}"
            )
        self.async_update_listeners()

    async def disconnect(self) -> None:
        """Fully disconnect and cancel any pending reconnection."""
        self._connected = False
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            self._reconnect_task = None

        if self._server is not None:
            self._server.set_on_update_callback(None)
            self._server.set_on_connect_callback(None)
            self._server.set_on_disconnect_callback(None)
            self._server.set_new_client_callback(None)
            self._server.stop()
            self._server = None
