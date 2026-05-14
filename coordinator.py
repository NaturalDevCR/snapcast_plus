"""Data update coordinator for Snapcast server with auto-reconnection."""

import asyncio
from datetime import timedelta
import logging

from snapcast.control.server import Snapserver

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

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
        self.last_update_success = False

    @property
    def server(self) -> Snapserver | None:
        """Get the Snapserver object."""
        return self._server

    @property
    def host_id(self) -> str:
        """Unique host identifier: host:port."""
        return f"{self.host}:{self.port}"

    async def _async_setup(self) -> None:
        """Perform async setup for the coordinator."""
        await self._connect()

    async def _connect(self) -> None:
        """Create a fresh Snapserver and connect to the host."""
        self._server = Snapserver(self.hass.loop, self.host, self.port, False)
        self._server.set_on_update_callback(self._on_update)
        self._server.set_new_client_callback(self._on_update)
        self._server.set_on_connect_callback(self._on_connect)
        self._server.set_on_disconnect_callback(self._on_disconnect)
        await self._server.start()

    def _on_update(self) -> None:
        """Snapserver: data updated (push)."""
        self.last_update_success = True
        self.async_update_listeners()

    def _on_connect(self) -> None:
        """Snapserver: websocket connected."""
        self.last_update_success = True
        self._reconnect_delay = 1
        _LOGGER.info(
            "Connected to Snapcast server at %s:%s", self.host, self.port
        )
        self.async_update_listeners()

    def _on_disconnect(self, ex: Exception) -> None:
        """Snapserver: websocket disconnected.  Start reconnection loop."""
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
            self._reconnect_task = self.hass.async_create_task(
                self._reconnect_loop()
            )

    async def _reconnect_loop(self) -> None:
        """Continuously attempt reconnection with exponential backoff."""
        while not self.last_update_success:
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
        if self.last_update_success:
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
        """Polling fallback — just push data to entities if connected."""
        if self.last_update_success and self._server is not None:
            self.async_update_listeners()

    async def disconnect(self) -> None:
        """Fully disconnect and cancel any pending reconnection."""
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
