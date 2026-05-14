"""Base entity for Snapcast."""

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SnapcastUpdateCoordinator


class SnapcastCoordinatorEntity(CoordinatorEntity[SnapcastUpdateCoordinator]):
    """Coordinator entity for Snapcast."""

    @property
    def available(self) -> bool:
        """Return if the coordinator is connected."""
        return self.coordinator.last_update_success
