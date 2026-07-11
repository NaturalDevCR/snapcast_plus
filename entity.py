"""Base entity for Snapcast."""

from snapcast.control.client import Snapclient

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SnapcastUpdateCoordinator


class SnapcastCoordinatorEntity(CoordinatorEntity[SnapcastUpdateCoordinator]):
    """Coordinator entity for Snapcast."""

    def __init__(
        self, coordinator: SnapcastUpdateCoordinator, device_id: str
    ) -> None:
        """Initialise entity.  device_id is the Snapcast client identifier."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._host_id = coordinator.host_id

    def _get_device(self) -> Snapclient | None:
        """Fetch a **fresh** Snapclient from the coordinator's server.

        This is the key fix vs the official integration: we never hold a
        stale reference across reconnection cycles.
        """
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
