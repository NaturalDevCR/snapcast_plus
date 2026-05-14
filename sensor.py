"""Sensor entities for Snapcast clients."""

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CLIENT_PREFIX, DOMAIN, LATENCY_SUFFIX
from .coordinator import SnapcastConfigEntry, SnapcastUpdateCoordinator
from .entity import SnapcastCoordinatorEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: SnapcastConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensor entities for every Snapcast client."""

    coordinator = config_entry.runtime_data
    known_client_ids: set[str] = set()

    @callback
    def _update_sensors() -> None:
        if coordinator.server is None:
            return

        current_ids = {c.identifier for c in coordinator.server.clients}

        ids_to_add = current_ids - known_client_ids
        ids_to_remove = known_client_ids - current_ids

        known_client_ids.difference_update(ids_to_remove)
        known_client_ids.update(ids_to_add)

        if not (ids_to_add or ids_to_remove):
            return

        if ids_to_add:
            _LOGGER.debug("New snapcast latency sensors: %s", list(ids_to_add))
            async_add_entities(
                SnapcastLatencySensor(coordinator, cid)
                for cid in ids_to_add
            )

        if ids_to_remove:
            _LOGGER.debug("Removed snapcast latency sensor IDs: %s", list(ids_to_remove))
            entity_registry = er.async_get(hass)
            for cid in ids_to_remove:
                if entity_id := entity_registry.async_get_entity_id(
                    "sensor",
                    DOMAIN,
                    SnapcastLatencySensor.build_unique_id(coordinator.host_id, cid),
                ):
                    entity_registry.async_remove(entity_id)

    _update_sensors()
    coordinator.async_add_listener(_update_sensors)


class SnapcastLatencySensor(SnapcastCoordinatorEntity, SensorEntity):
    """Sensor reporting the latency of a Snapcast client in milliseconds."""

    _attr_native_unit_of_measurement = UnitOfTime.MILLISECONDS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: SnapcastUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialise latency sensor."""
        super().__init__(coordinator)

        self._device_id = device_id
        self._host_id = coordinator.host_id
        self._attr_unique_id = self.build_unique_id(self._host_id, device_id)

        device = self._get_device()
        self._attr_name = (
            f"{device.friendly_name} {LATENCY_SUFFIX}"
            if device
            else f"{device_id} {LATENCY_SUFFIX}"
        )

    @classmethod
    def build_unique_id(cls, host_id: str, device_id: str) -> str:
        """Build a unique entity ID."""
        return f"{CLIENT_PREFIX}{host_id}_{device_id}_latency"

    def _get_device(self):
        """Fetch a fresh Snapclient from the coordinator's server."""
        server = self.coordinator.server
        if server is None:
            return None
        try:
            return server.client(self._device_id)
        except (KeyError, AttributeError):
            return None

    @property
    def available(self) -> bool:
        """Available if the coordinator is connected and the client exists."""
        if not self.coordinator.last_update_success:
            return False
        return self._get_device() is not None

    @property
    def native_value(self) -> int | None:
        """Return the current latency in milliseconds."""
        device = self._get_device()
        if device is None:
            return None
        return device.latency
