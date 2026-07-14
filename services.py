"""Snapcast services."""

import voluptuous as vol

from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import config_validation as cv, service

from .const import CLIENT_PREFIX, DOMAIN, GROUP_PREFIX, ZONE_PREFIX

SERVICE_SNAPSHOT = "snapshot"
SERVICE_RESTORE = "restore"
SERVICE_SET_LATENCY = "set_latency"
SERVICE_RECONCILE_GROUP = "reconcile_group"
SERVICE_CREATE_ZONE = "create_zone"
SERVICE_UPDATE_ZONE = "update_zone"
SERVICE_REMOVE_ZONE = "remove_zone"

ATTR_LATENCY = "latency"
ATTR_OLD_ENTITY_ID = "old_entity_id"
ATTR_NEW_ENTITY_ID = "new_entity_id"
ATTR_NAME = "name"
ATTR_CLIENTS = "clients"
ATTR_ZONE_ENTITY_ID = "zone_entity_id"


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register Snapcast-specific entity services."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SNAPSHOT,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema=None,
        func="async_snapshot",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_RESTORE,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema=None,
        func="async_restore",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SET_LATENCY,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={vol.Required(ATTR_LATENCY): cv.positive_int},
        func="async_set_latency",
    )

    async def async_reconcile_group(call: ServiceCall) -> None:
        """Explicitly assign a live group to an unavailable group entity."""
        registry = er.async_get(hass)
        old_entity_id = call.data[ATTR_OLD_ENTITY_ID]
        new_entity_id = call.data[ATTR_NEW_ENTITY_ID]
        old_entry = registry.async_get(old_entity_id)
        new_entry = registry.async_get(new_entity_id)

        if (
            old_entity_id == new_entity_id
            or old_entry is None
            or new_entry is None
            or old_entry.domain != MEDIA_PLAYER_DOMAIN
            or new_entry.domain != MEDIA_PLAYER_DOMAIN
            or old_entry.platform != DOMAIN
            or new_entry.platform != DOMAIN
            or old_entry.config_entry_id != new_entry.config_entry_id
            or old_entry.unique_id is None
            or new_entry.unique_id is None
            or not old_entry.unique_id.startswith(GROUP_PREFIX)
            or not new_entry.unique_id.startswith(GROUP_PREFIX)
        ):
            raise ServiceValidationError(
                "Both entities must be different Snapcast groups from the same server."
            )

        config_entry = hass.config_entries.async_get_entry(old_entry.config_entry_id)
        if config_entry is None or config_entry.domain != DOMAIN:
            raise ServiceValidationError("The Snapcast configuration entry is unavailable.")
        coordinator = config_entry.runtime_data
        old_logical_id = coordinator.logical_group_id_from_unique_id(old_entry.unique_id)
        new_logical_id = coordinator.logical_group_id_from_unique_id(new_entry.unique_id)
        if old_logical_id is None or new_logical_id is None:
            raise ServiceValidationError("Both entities must belong to this Snapcast server.")

        try:
            await coordinator.async_reassign_group(old_logical_id, new_logical_id)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err

        registry.async_remove(new_entity_id)
        await hass.config_entries.async_reload(config_entry.entry_id)

    hass.services.async_register(
        DOMAIN,
        SERVICE_RECONCILE_GROUP,
        async_reconcile_group,
        schema=vol.Schema({
            vol.Required(ATTR_OLD_ENTITY_ID): cv.entity_id,
            vol.Required(ATTR_NEW_ENTITY_ID): cv.entity_id,
        }),
    )

    def resolve_client_entities(entity_ids: list[str]):
        """Resolve selected client entities to one loaded Snapcast entry."""
        registry = er.async_get(hass)
        resolved = []
        for entity_id in entity_ids:
            entity = registry.async_get(entity_id)
            if (
                entity is None
                or entity.domain != MEDIA_PLAYER_DOMAIN
                or entity.platform != DOMAIN
                or entity.unique_id is None
                or not entity.unique_id.startswith(CLIENT_PREFIX)
            ):
                raise ServiceValidationError(
                    "Zones can only contain Snapcast client media_player entities."
                )
            config_entry = hass.config_entries.async_get_entry(entity.config_entry_id)
            if config_entry is None or config_entry.domain != DOMAIN:
                raise ServiceValidationError("The Snapcast configuration entry is unavailable.")
            coordinator = config_entry.runtime_data
            client_id = coordinator.client_id_from_unique_id(entity.unique_id)
            if client_id is None:
                raise ServiceValidationError(f"Client '{entity_id}' is unavailable.")
            resolved.append((config_entry, coordinator, client_id))

        config_entry, coordinator, _ = resolved[0]
        if any(entry.entry_id != config_entry.entry_id for entry, _, _ in resolved):
            raise ServiceValidationError("All zone clients must belong to one Snapcast server.")
        return config_entry, coordinator, [client_id for _, _, client_id in resolved]

    def resolve_zone_entity(entity_id: str):
        """Resolve a zone entity to its loaded coordinator and stored ID."""
        entity = er.async_get(hass).async_get(entity_id)
        if (
            entity is None
            or entity.domain != MEDIA_PLAYER_DOMAIN
            or entity.platform != DOMAIN
            or entity.unique_id is None
            or not entity.unique_id.startswith(ZONE_PREFIX)
        ):
            raise ServiceValidationError("The entity must be a Snapcast zone.")
        config_entry = hass.config_entries.async_get_entry(entity.config_entry_id)
        if config_entry is None or config_entry.domain != DOMAIN:
            raise ServiceValidationError("The Snapcast configuration entry is unavailable.")
        coordinator = config_entry.runtime_data
        zone_id = coordinator.zone_id_from_unique_id(entity.unique_id)
        if zone_id is None:
            raise ServiceValidationError("The Snapcast zone no longer exists.")
        return entity, config_entry, coordinator, zone_id

    async def async_create_zone(call: ServiceCall) -> None:
        """Create a stable zone from Snapcast client entities."""
        _, coordinator, client_ids = resolve_client_entities(call.data[ATTR_CLIENTS])
        await coordinator.async_create_zone(call.data[ATTR_NAME], client_ids)

    async def async_update_zone(call: ServiceCall) -> None:
        """Rename a zone or replace its selected client entities."""
        _, config_entry, coordinator, zone_id = resolve_zone_entity(
            call.data[ATTR_ZONE_ENTITY_ID]
        )
        client_ids = None
        if ATTR_CLIENTS in call.data:
            client_entry, _, client_ids = resolve_client_entities(call.data[ATTR_CLIENTS])
            if client_entry.entry_id != config_entry.entry_id:
                raise ServiceValidationError("All zone clients must belong to one Snapcast server.")
        name = call.data.get(ATTR_NAME)
        if name is None and client_ids is None:
            raise ServiceValidationError("Provide a name or clients to update a zone.")
        await coordinator.async_update_zone(zone_id, name, client_ids)

    async def async_remove_zone(call: ServiceCall) -> None:
        """Remove a zone and reload its entry to remove the entity state."""
        entity, config_entry, coordinator, zone_id = resolve_zone_entity(
            call.data[ATTR_ZONE_ENTITY_ID]
        )
        await coordinator.async_remove_zone(zone_id)
        er.async_get(hass).async_remove(entity.entity_id)
        await hass.config_entries.async_reload(config_entry.entry_id)

    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_ZONE,
        async_create_zone,
        schema=vol.Schema({
            vol.Required(ATTR_NAME): vol.All(cv.string, vol.Length(min=1)),
            vol.Required(ATTR_CLIENTS): vol.All(cv.entity_ids, vol.Length(min=1)),
        }),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_ZONE,
        async_update_zone,
        schema=vol.Schema({
            vol.Required(ATTR_ZONE_ENTITY_ID): cv.entity_id,
            vol.Optional(ATTR_NAME): vol.All(cv.string, vol.Length(min=1)),
            vol.Optional(ATTR_CLIENTS): vol.All(cv.entity_ids, vol.Length(min=1)),
        }),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_ZONE,
        async_remove_zone,
        schema=vol.Schema({vol.Required(ATTR_ZONE_ENTITY_ID): cv.entity_id}),
    )
