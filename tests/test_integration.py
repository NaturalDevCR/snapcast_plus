"""Tests for Snapcast Plus: setup, entities, and reconnection behavior."""

import asyncio
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.snapcast.const import DOMAIN

from conftest import FakeSnapserver, make_group

MEDIA_PLAYER_ID = "media_player.living_room_snapcast_client"
SENSOR_ID = "sensor.living_room_latency"
GROUP_ID = "media_player.living_room_snapcast_group"


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A config entry identical to what the official integration stores."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Snapcast",
        data={CONF_HOST: "127.0.0.1", CONF_PORT: 1705},
    )


@pytest.fixture
def snapserver_factory(fake_server):
    """Patch the Snapserver constructor in the coordinator.

    The first construction returns ``fake_server``; later constructions
    (reconnects) return fresh FakeSnapservers sharing the same clients,
    mirroring how the real library builds new objects per connection.
    """
    created: list[FakeSnapserver] = []

    def _factory(*args, **kwargs):
        if not created:
            server = fake_server
        else:
            server = FakeSnapserver()
            server.clients_by_id = dict(created[-1].clients_by_id)
        created.append(server)
        return server

    with patch(
        "custom_components.snapcast.coordinator.Snapserver",
        side_effect=_factory,
    ):
        yield created


async def setup_entry(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Add the entry to hass and set it up."""
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


# ---------------------------------------------------------------------------
# Setup / teardown
# ---------------------------------------------------------------------------


async def test_setup_creates_entities(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """Each client gets a media_player and a latency sensor."""
    await setup_entry(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED

    player = hass.states.get(MEDIA_PLAYER_ID)
    assert player is not None
    assert player.state == "playing"
    assert player.attributes["latency"] == 10
    assert player.attributes["volume_level"] == 0.5

    sensor = hass.states.get(SENSOR_ID)
    assert sensor is not None
    assert sensor.state == "10"


async def test_setup_creates_controllable_group_entity(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """Each Snapcast group is a controllable media player."""
    await setup_entry(hass, config_entry)

    group = hass.states.get(GROUP_ID)
    assert group is not None
    assert group.state == "playing"

    await hass.services.async_call(
        "media_player",
        "volume_mute",
        {"entity_id": GROUP_ID, "is_volume_muted": True},
        blocking=True,
    )
    fake_server.group("group-a").set_muted.assert_awaited_once_with(True)


async def test_group_entity_only_controls_mute_and_source(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """Groups must not expose operations that change client volumes."""
    await setup_entry(hass, config_entry)

    group = hass.states.get(GROUP_ID)
    assert group is not None
    assert "volume_level" not in group.attributes

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "media_player", "volume_set",
            {"entity_id": GROUP_ID, "volume_level": 0.25}, blocking=True,
        )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "snapshot", {"entity_id": GROUP_ID}, blocking=True
        )


async def test_group_entity_rebinds_when_snapcast_changes_group_id(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """A group keeps its Home Assistant entity when Snapcast replaces its ID."""
    await setup_entry(hass, config_entry)
    new_group = make_group("group-b", client_ids=["aa:bb:cc"])
    fake_server.groups_by_id = {"group-b": new_group}
    fake_server.on_update()
    await hass.async_block_till_done()

    assert hass.states.get(GROUP_ID) is not None
    await hass.services.async_call(
        "media_player", "volume_mute",
        {"entity_id": GROUP_ID, "is_volume_muted": True}, blocking=True,
    )
    new_group.set_muted.assert_awaited_once_with(True)


async def test_setup_retries_when_server_unreachable(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """Connection failure on setup puts the entry in retry state."""
    fake_server.start.side_effect = OSError("connection refused")

    await setup_entry(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_disconnects(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """Unloading the entry stops the server connection."""
    await setup_entry(hass, config_entry)

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED
    fake_server.stop.assert_called_once()


# ---------------------------------------------------------------------------
# Disconnection / reconnection — the core value of this integration
# ---------------------------------------------------------------------------


async def test_disconnect_marks_entities_unavailable(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """A server disconnect immediately flips entities to unavailable."""
    await setup_entry(hass, config_entry)

    fake_server.on_disconnect(Exception("connection lost"))
    await hass.async_block_till_done()

    assert hass.states.get(MEDIA_PLAYER_ID).state == STATE_UNAVAILABLE
    assert hass.states.get(SENSOR_ID).state == STATE_UNAVAILABLE


async def test_poll_does_not_resurrect_disconnected_entities(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server, freezer
) -> None:
    """Regression: the 45s polling fallback must not mark entities
    available again (nor abort the reconnect loop) while disconnected.

    The base DataUpdateCoordinator sets last_update_success = True after
    any _async_update_data that does not raise; the coordinator must raise
    UpdateFailed while disconnected.
    """
    await setup_entry(hass, config_entry)
    coordinator = config_entry.runtime_data

    fake_server.on_disconnect(Exception("connection lost"))
    await hass.async_block_till_done()

    freezer.tick(timedelta(seconds=46))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert coordinator.last_update_success is False
    assert hass.states.get(MEDIA_PLAYER_ID).state == STATE_UNAVAILABLE
    assert hass.states.get(SENSOR_ID).state == STATE_UNAVAILABLE


async def test_reconnect_restores_entities(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """After a disconnect the coordinator builds a fresh Snapserver and
    entities recover once it connects."""
    await setup_entry(hass, config_entry)

    fake_server.on_disconnect(Exception("connection lost"))
    await hass.async_block_till_done()
    assert hass.states.get(MEDIA_PLAYER_ID).state == STATE_UNAVAILABLE

    # The reconnect loop backs off 1s (real time) before its first attempt.
    await asyncio.sleep(1.2)
    await hass.async_block_till_done()

    assert len(snapserver_factory) == 2, "expected a fresh Snapserver"
    new_server = snapserver_factory[-1]
    new_server.start.assert_awaited()
    # The old (stale) server was torn down.
    fake_server.stop.assert_called_once()

    # The real library fires on_connect during start().
    new_server.on_connect()
    await hass.async_block_till_done()

    assert hass.states.get(MEDIA_PLAYER_ID).state == "playing"
    assert hass.states.get(SENSOR_ID).state == "10"


async def test_client_rename_is_reflected(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """Renaming a client on the Snapcast server updates the friendly name."""
    await setup_entry(hass, config_entry)

    fake_server.client("aa:bb:cc").friendly_name = "Kitchen"
    fake_server.on_update()
    await hass.async_block_till_done()

    state = hass.states.get(MEDIA_PLAYER_ID)
    assert state.attributes["friendly_name"] == "Kitchen Snapcast Client"


# ---------------------------------------------------------------------------
# Commands and services
# ---------------------------------------------------------------------------


async def test_volume_and_mute_commands(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """volume_set and volume_mute reach the (fresh) Snapclient."""
    await setup_entry(hass, config_entry)
    client = fake_server.client("aa:bb:cc")

    await hass.services.async_call(
        "media_player",
        "volume_set",
        {"entity_id": MEDIA_PLAYER_ID, "volume_level": 0.37},
        blocking=True,
    )
    client.set_volume.assert_awaited_once_with(37)

    await hass.services.async_call(
        "media_player",
        "volume_mute",
        {"entity_id": MEDIA_PLAYER_ID, "is_volume_muted": True},
        blocking=True,
    )
    client.set_muted.assert_awaited_once_with(True)


async def test_select_source(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """select_source resolves the stream by name and sets it on the group."""
    await setup_entry(hass, config_entry)
    client = fake_server.client("aa:bb:cc")
    stream = MagicMock()
    stream.identifier = "radio_id"
    client.group.streams_by_name.return_value = {"Radio": stream}

    await hass.services.async_call(
        "media_player",
        "select_source",
        {"entity_id": MEDIA_PLAYER_ID, "source": "Radio"},
        blocking=True,
    )
    client.group.set_stream.assert_awaited_once_with("radio_id")


async def test_set_latency_service(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """The snapcast.set_latency service (official-compatible) works."""
    await setup_entry(hass, config_entry)
    client = fake_server.client("aa:bb:cc")

    await hass.services.async_call(
        DOMAIN,
        "set_latency",
        {"entity_id": MEDIA_PLAYER_ID, "latency": 42},
        blocking=True,
    )
    client.set_latency.assert_awaited_once_with(42)


async def test_snapshot_and_restore_services(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """snapcast.snapshot / snapcast.restore reach the client."""
    await setup_entry(hass, config_entry)
    client = fake_server.client("aa:bb:cc")

    await hass.services.async_call(
        DOMAIN, "snapshot", {"entity_id": MEDIA_PLAYER_ID}, blocking=True
    )
    client.snapshot.assert_called_once()

    await hass.services.async_call(
        DOMAIN, "restore", {"entity_id": MEDIA_PLAYER_ID}, blocking=True
    )
    client.restore.assert_awaited_once()
