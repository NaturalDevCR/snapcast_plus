"""Media player entities for Snapcast clients.

Key design decision vs the official integration:
Instead of storing a Snapclient reference (which becomes stale after
reconnection), every property/action that needs the device fetches a
fresh reference via self._get_device() from the coordinator's current
Snapserver.  This eliminates the class of bugs where entities stop
responding after a server reconnect.
"""

from collections.abc import Mapping
import logging
from typing import Any

from snapcast.control.client import Snapclient

from homeassistant.components.media_player import (
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CLIENT_PREFIX, CLIENT_SUFFIX, DOMAIN
from .coordinator import SnapcastConfigEntry, SnapcastUpdateCoordinator
from .entity import SnapcastCoordinatorEntity

STREAM_STATUS: dict[str, MediaPlayerState | None] = {
    "idle": MediaPlayerState.IDLE,
    "playing": MediaPlayerState.PLAYING,
    "unknown": None,
}

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: SnapcastConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up media_player entities for every Snapcast client."""

    coordinator = config_entry.runtime_data
    known_client_ids: set[str] = set()

    @callback
    def _update_clients() -> None:
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
            _LOGGER.debug(
                "New snapcast clients: %s",
                [
                    coordinator.server.client(cid).friendly_name
                    for cid in ids_to_add
                ],
            )
            async_add_entities(
                SnapcastClientDevice(coordinator, cid)
                for cid in ids_to_add
            )

        if ids_to_remove:
            _LOGGER.debug(
                "Removed snapcast client IDs: %s",
                list(ids_to_remove),
            )
            entity_registry = er.async_get(hass)
            for cid in ids_to_remove:
                if entity_id := entity_registry.async_get_entity_id(
                    MEDIA_PLAYER_DOMAIN,
                    DOMAIN,
                    SnapcastClientDevice.build_unique_id(
                        coordinator.host_id, cid
                    ),
                ):
                    entity_registry.async_remove(entity_id)

    _update_clients()
    coordinator.async_add_listener(_update_clients)


# ---------------------------------------------------------------------------
# Media player entity
# ---------------------------------------------------------------------------


class SnapcastClientDevice(SnapcastCoordinatorEntity, MediaPlayerEntity):
    """A Snapcast client exposed as a Home Assistant media_player."""

    _attr_should_poll = False
    _attr_supported_features = (
        MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.GROUPING
    )
    _attr_media_content_type = MediaType.MUSIC
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER

    def __init__(
        self,
        coordinator: SnapcastUpdateCoordinator,
        device_id: str,
    ) -> None:
        """Initialise entity.  device_id is the Snapcast client identifier."""
        super().__init__(coordinator)

        self._device_id = device_id
        self._host_id = coordinator.host_id
        self._attr_unique_id = self.build_unique_id(self._host_id, device_id)

        device = self._get_device()
        self._attr_name = (
            f"{device.friendly_name} {CLIENT_SUFFIX}"
            if device
            else f"{device_id} {CLIENT_SUFFIX}"
        )

    @classmethod
    def build_unique_id(cls, host_id: str, device_id: str) -> str:
        """Build a unique entity ID for a given client."""
        return f"{CLIENT_PREFIX}{host_id}_{device_id}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_device(self) -> Snapclient | None:
        """Fetch a **fresh** Snapclient from the coordinator's server.

        This is the key fix: we never hold a stale reference across
        reconnection cycles.
        """
        server = self.coordinator.server
        if server is None:
            return None
        try:
            return server.client(self._device_id)
        except (KeyError, AttributeError):
            return None

    @property
    def _current_group(self):
        """Return the group the client currently belongs to."""
        device = self._get_device()
        if device is None:
            return None
        return device.group

    # ------------------------------------------------------------------
    # Entity availability
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Available if the coordinator is connected and the client exists."""
        if not self.coordinator.last_update_success:
            return False
        return self._get_device() is not None

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def state(self) -> MediaPlayerState | None:
        """Return the current playback state."""
        device = self._get_device()
        if device is None or not device.connected:
            return MediaPlayerState.OFF

        group = device.group
        if self.is_volume_muted or group is None or group.muted:
            return MediaPlayerState.IDLE

        return STREAM_STATUS.get(group.stream_status, MediaPlayerState.IDLE)

    # ------------------------------------------------------------------
    # Volume
    # ------------------------------------------------------------------

    @property
    def volume_level(self) -> float:
        """Volume level (0.0 -> 1.0)."""
        device = self._get_device()
        if device is None:
            return 0.0
        return device.volume / 100.0

    @property
    def is_volume_muted(self) -> bool:
        """Is volume muted?"""
        device = self._get_device()
        if device is None:
            return False
        return device.muted

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume level."""
        device = self._get_device()
        if device is None:
            return
        await device.set_volume(round(volume * 100))
        self.async_write_ha_state()

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute."""
        device = self._get_device()
        if device is None:
            return
        await device.set_muted(mute)
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Source (stream) selection
    # ------------------------------------------------------------------

    @property
    def source(self) -> str | None:
        """Current stream name."""
        group = self._current_group
        if group is None:
            return None
        return group.stream

    @property
    def source_list(self) -> list[str]:
        """Available stream names."""
        group = self._current_group
        if group is None:
            return []
        return list(group.streams_by_name().keys())

    async def async_select_source(self, source: str) -> None:
        """Switch to a different stream."""
        group = self._current_group
        if group is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="select_source_no_group",
                translation_placeholders={
                    "entity_id": self.entity_id,
                    "source": source,
                },
            )

        streams = group.streams_by_name()
        if source in streams:
            await group.set_stream(streams[source].identifier)
            self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Grouping
    # ------------------------------------------------------------------

    @property
    def group_members(self) -> list[str] | None:
        """Entities in the same Snapcast group."""
        group = self._current_group
        if group is None:
            return None

        entity_registry = er.async_get(self.hass)
        result: list[str] = []
        for client_id in group.clients:
            eid = entity_registry.async_get_entity_id(
                MEDIA_PLAYER_DOMAIN,
                DOMAIN,
                self.build_unique_id(self.coordinator.host_id, client_id),
            )
            if eid:
                result.append(eid)
        return result

    async def async_join_players(self, group_members: list[str]) -> None:
        """Add other entities to this client's group."""
        group = self._current_group
        if group is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="join_players_no_group",
                translation_placeholders={"entity_id": self.entity_id},
            )

        entity_registry = er.async_get(self.hass)
        unique_id_prefix = self.build_unique_id(self.coordinator.host_id, "")

        for entity_id in group_members:
            entity = entity_registry.async_get(entity_id)
            if entity is None or entity.unique_id == self.unique_id:
                continue

            if not entity.unique_id.startswith(CLIENT_PREFIX):
                raise ServiceValidationError(
                    f"Entity '{entity_id}' is not a Snapcast client."
                )
            if not entity.unique_id.startswith(unique_id_prefix):
                raise ServiceValidationError(
                    f"Entity '{entity_id}' does not belong to the same"
                    " Snapcast server."
                )

            identifier = entity.unique_id.removeprefix(unique_id_prefix)
            try:
                await group.add_client(identifier)
            except KeyError as ex:
                raise ServiceValidationError(
                    f"Client '{identifier}' does not exist on the server."
                ) from ex

        self.async_write_ha_state()

    async def async_unjoin_player(self) -> None:
        """Remove this client from its current group."""
        group = self._current_group
        if group is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unjoin_no_group",
                translation_placeholders={"entity_id": self.entity_id},
            )

        await group.remove_client(self._device_id)
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Snapcast-specific services
    # ------------------------------------------------------------------

    async def async_snapshot(self) -> None:
        """Take a snapshot of the client state."""
        device = self._get_device()
        if device is None:
            return
        device.snapshot()

    async def async_restore(self) -> None:
        """Restore a previously saved snapshot."""
        device = self._get_device()
        if device is None:
            return
        await device.restore()
        self.async_write_ha_state()

    async def async_set_latency(self, latency: int) -> None:
        """Set client latency in milliseconds."""
        device = self._get_device()
        if device is None:
            return
        await device.set_latency(latency)
        self.async_write_ha_state()

    # ------------------------------------------------------------------
    # Metadata / media info
    # ------------------------------------------------------------------

    @property
    def latency(self) -> int | None:
        """Current latency in milliseconds."""
        device = self._get_device()
        if device is None:
            return None
        return device.latency

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Additional state attributes."""
        lat = self.latency
        if lat is not None:
            return {"latency": lat}
        return {}

    def _stream_metadata(self) -> dict[str, Any]:
        """Raw metadata dict of the current stream."""
        group = self._current_group
        if group is None:
            return {}
        server = self.coordinator.server
        if server is None:
            return {}
        try:
            stream = server.stream(group.stream)
            if stream and stream.metadata:
                return stream.metadata
        except KeyError:
            pass
        return {}

    @property
    def media_title(self) -> str | None:
        """Title of current playing media."""
        return self._stream_metadata().get("title")

    @property
    def media_image_url(self) -> str | None:
        """Image URL of current playing media."""
        return self._stream_metadata().get("artUrl")

    @property
    def media_artist(self) -> str | None:
        """Artist."""
        value = self._stream_metadata().get("artist")
        return ", ".join(value) if value else None

    @property
    def media_album_name(self) -> str | None:
        """Album name."""
        return self._stream_metadata().get("album")

    @property
    def media_album_artist(self) -> str | None:
        """Album artist."""
        value = self._stream_metadata().get("albumArtist")
        return ", ".join(value) if value else None

    @property
    def media_track(self) -> int | None:
        """Track number."""
        value = self._stream_metadata().get("trackNumber")
        return int(value) if value is not None else None

    @property
    def media_duration(self) -> int | None:
        """Duration in seconds."""
        value = self._stream_metadata().get("duration")
        return int(value) if value is not None else None

    @property
    def media_position(self) -> int | None:
        """Position in seconds."""
        group = self._current_group
        if group is None:
            return None
        server = self.coordinator.server
        if server is None:
            return None
        try:
            stream = server.stream(group.stream)
            if stream and stream.properties:
                value = stream.properties.get("position")
                if value is not None:
                    return int(value)
        except KeyError:
            pass
        return None
