"""Tests for Snapcast Plus: setup, entities, and reconnection behavior."""

import asyncio
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from conftest import FakeSnapserver, make_client, make_group
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.snapcast.const import DOMAIN
from custom_components.snapcast.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.snapcast.media_player import SnapcastGroupDevice

MEDIA_PLAYER_ID = "media_player.living_room_snapcast_client"
SENSOR_ID = "sensor.living_room_latency"
GROUP_ID = "media_player.living_room_snapcast_group"
ZONE_ID = "media_player.casa_snapcast_zone"


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
            server.groups_by_id = dict(created[-1].groups_by_id)
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


async def test_group_volume_uses_snapcast_relative_adjustment(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """Group volume delegates proportional adjustment to Snapcast itself."""
    await setup_entry(hass, config_entry)

    group = hass.states.get(GROUP_ID)
    assert group is not None
    assert group.attributes["volume_level"] == 0.5

    await hass.services.async_call(
        "media_player",
        "volume_set",
        {"entity_id": GROUP_ID, "volume_level": 0.37},
        blocking=True,
    )
    fake_server.group("group-a").set_volume.assert_awaited_once_with(37)

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "snapshot", {"entity_id": GROUP_ID}, blocking=True
        )


async def test_client_volume_push_updates_group_slider(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """A Client.OnVolumeChanged push (no full sync) refreshes the group slider.

    python-snapcast delivers per-client/per-group changes through the
    object's own callback (client.set_callback / group.set_callback), not
    through the coordinator's set_on_update_callback (Server.OnUpdate only).
    The coordinator must wire those object callbacks itself.
    """
    await setup_entry(hass, config_entry)
    client = fake_server.client("aa:bb:cc")
    group = fake_server.group("group-a")

    client.volume = 80
    group.volume = 80

    callback = client.set_callback.call_args.args[0]
    callback(client)
    await hass.async_block_till_done()

    updated = hass.states.get(GROUP_ID)
    assert updated.attributes["volume_level"] == 0.8


async def test_group_volume_push_updates_client_slider(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """A Group-driven per-client push refreshes that client's own slider."""
    await setup_entry(hass, config_entry)
    client = fake_server.client("aa:bb:cc")

    client.volume = 65

    callback = client.set_callback.call_args.args[0]
    callback(client)
    await hass.async_block_till_done()

    updated = hass.states.get(MEDIA_PLAYER_ID)
    assert updated.attributes["volume_level"] == 0.65


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
        "media_player",
        "volume_mute",
        {"entity_id": GROUP_ID, "is_volume_muted": True},
        blocking=True,
    )
    new_group.set_muted.assert_awaited_once_with(True)


async def test_group_with_partial_member_overlap_gets_a_new_entity(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """A changed membership must not inherit a previous group identity."""
    await setup_entry(hass, config_entry)

    fake_server.groups_by_id = {
        "group-b": make_group("group-b", client_ids=["aa:bb:cc", "dd:ee:ff"])
    }
    fake_server.on_update()
    await hass.async_block_till_done()

    assert config_entry.runtime_data.group_bindings == {
        "group-a": None,
        "group-b": "group-b",
    }
    assert hass.states.get(GROUP_ID).state == STATE_UNAVAILABLE


async def test_reconcile_group_service_reuses_old_entity(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """An explicit choice moves a new group back to an unavailable entity."""
    await setup_entry(hass, config_entry)

    fake_server.groups_by_id = {
        "group-b": make_group("group-b", client_ids=["aa:bb:cc", "dd:ee:ff"])
    }
    fake_server.on_update()
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    new_entity_id = registry.async_get_entity_id(
        "media_player",
        DOMAIN,
        SnapcastGroupDevice.build_unique_id("127.0.0.1:1705", "group-b"),
    )
    assert new_entity_id is not None

    await hass.services.async_call(
        DOMAIN,
        "reconcile_group",
        {"old_entity_id": GROUP_ID, "new_entity_id": new_entity_id},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert config_entry.runtime_data.group_bindings == {"group-a": "group-b"}
    assert registry.async_get(new_entity_id) is None
    assert hass.states.get(GROUP_ID).state == "playing"


async def test_cleanup_groups_removes_only_historical_entities(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """Explicit cleanup prunes unavailable group history, not live groups."""
    await setup_entry(hass, config_entry)

    fake_server.groups_by_id = {
        "group-b": make_group("group-b", client_ids=["aa:bb:cc", "dd:ee:ff"])
    }
    fake_server.on_update()
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    new_entity_id = registry.async_get_entity_id(
        "media_player",
        DOMAIN,
        SnapcastGroupDevice.build_unique_id("127.0.0.1:1705", "group-b"),
    )
    assert new_entity_id is not None
    assert registry.async_get(GROUP_ID) is not None

    await hass.services.async_call(DOMAIN, "cleanup_groups", blocking=True)
    await hass.async_block_till_done()

    assert config_entry.runtime_data.group_bindings == {"group-b": "group-b"}
    assert registry.async_get(GROUP_ID) is None
    assert registry.async_get(new_entity_id) is not None


async def test_zone_controls_current_groups_of_its_clients(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """A persistent zone follows its client to the group it is in now."""
    await setup_entry(hass, config_entry)

    await hass.services.async_call(
        DOMAIN,
        "create_zone",
        {"name": "Casa", "clients": [MEDIA_PLAYER_ID]},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get(ZONE_ID) is not None
    await hass.services.async_call(
        "media_player",
        "volume_mute",
        {"entity_id": ZONE_ID, "is_volume_muted": True},
        blocking=True,
    )
    fake_server.group("group-a").set_muted.assert_awaited_once_with(True)

    replacement = make_group("group-b", client_ids=["aa:bb:cc"])
    fake_server.client("aa:bb:cc").group = replacement
    fake_server.groups_by_id = {"group-b": replacement}
    fake_server.on_update()
    await hass.async_block_till_done()

    await hass.services.async_call(
        "media_player",
        "volume_mute",
        {"entity_id": ZONE_ID, "is_volume_muted": False},
        blocking=True,
    )
    replacement.set_muted.assert_awaited_once_with(False)


async def test_zone_can_be_renamed_and_removed(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """Zone administration persists edits and removes the entity cleanly."""
    await setup_entry(hass, config_entry)
    await hass.services.async_call(
        DOMAIN,
        "create_zone",
        {"name": "Casa", "clients": [MEDIA_PLAYER_ID]},
        blocking=True,
    )
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN,
        "update_zone",
        {"zone_entity_id": ZONE_ID, "name": "Casa Principal"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(ZONE_ID).attributes["friendly_name"] == (
        "Casa Principal Snapcast Zone"
    )

    await hass.services.async_call(
        DOMAIN,
        "remove_zone",
        {"zone_entity_id": ZONE_ID},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(ZONE_ID) is None


async def test_zone_selects_a_source_shared_by_its_current_groups(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """Zone source selection resolves the live group source by name."""
    await setup_entry(hass, config_entry)
    stream = MagicMock()
    stream.identifier = "radio_id"
    fake_server.group("group-a").streams_by_name.return_value = {"Radio": stream}

    await hass.services.async_call(
        DOMAIN,
        "create_zone",
        {"name": "Casa", "clients": [MEDIA_PLAYER_ID]},
        blocking=True,
    )
    await hass.services.async_call(
        "media_player",
        "select_source",
        {"entity_id": ZONE_ID, "source": "Radio"},
        blocking=True,
    )

    fake_server.group("group-a").set_stream.assert_awaited_once_with("radio_id")


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


async def test_diagnostics_redact_snapcast_identifiers(
    hass: HomeAssistant, config_entry, snapserver_factory, fake_server
) -> None:
    """Diagnostics expose health counts without host or device identifiers."""
    await setup_entry(hass, config_entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)

    assert diagnostics["connection"] == {
        "connected": True,
        "last_update_success": True,
        "reconnect_delay": 1,
        "reconnect_attempts": 0,
        "last_response_time": config_entry.runtime_data.last_response_time,
        "last_disconnect_time": None,
        "last_error_type": None,
    }
    assert diagnostics["connection"]["last_response_time"] is not None
    assert diagnostics["entities"] == {"clients": 1, "groups": 1, "stale_clients": 0}
    assert diagnostics["persistence"] == {
        "zones": 0,
        "group_bindings": 1,
        "historical_groups": 0,
    }
    serialized = repr(diagnostics)
    assert "127.0.0.1" not in serialized
    assert "aa:bb:cc" not in serialized


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


def test_service_metadata_describes_extended_services() -> None:
    """Every registered Snapcast service is discoverable in the service UI."""
    metadata = yaml.safe_load((Path(__file__).parents[1] / "services.yaml").read_text())

    assert {
        "snapshot",
        "restore",
        "set_latency",
        "reconcile_group",
        "create_zone",
        "update_zone",
        "remove_zone",
        "cleanup_groups",
    } <= metadata.keys()
    assert metadata["reconcile_group"]["fields"]["old_entity_id"]["required"]
    assert metadata["create_zone"]["fields"]["clients"]["required"]


async def test_new_client_callback_accepts_library_argument(
    hass, config_entry, snapserver_factory, fake_server
):
    """A genuinely new ID can be discovered through the real callback signature."""
    await setup_entry(hass, config_entry)
    client = make_client(identifier="new-client", name="Kitchen")
    fake_server.clients_by_id[client.identifier] = client
    fake_server.on_new_client(client)
    await hass.async_block_till_done()
    assert hass.states.get("media_player.kitchen_snapcast_client").state == "playing"


async def test_poll_refreshes_server_state(
    hass, config_entry, snapserver_factory, fake_server
):
    """A missed push is repaired by an authoritative status response."""
    await setup_entry(hass, config_entry)
    client = fake_server.client("aa:bb:cc")
    fake_server.synchronize.side_effect = lambda _: setattr(client, "connected", False)
    await config_entry.runtime_data.async_refresh()
    assert hass.states.get(MEDIA_PLAYER_ID).state == "off"
    fake_server.status.assert_awaited()


@pytest.mark.parametrize("response", [(None, None), ({}, None), (None, {"code": -1})])
async def test_bad_status_starts_reconnection(
    hass, config_entry, snapserver_factory, fake_server, response
):
    """Invalid responses close the old connection and leave entities unavailable."""
    await setup_entry(hass, config_entry)
    fake_server.status.return_value = response
    await config_entry.runtime_data.async_refresh()
    assert not config_entry.runtime_data.connected
    assert hass.states.get(MEDIA_PLAYER_ID).state == STATE_UNAVAILABLE
    fake_server.stop.assert_called_once()
    assert config_entry.runtime_data._reconnect_task is not None


async def test_silent_status_is_bounded(
    hass, config_entry, snapserver_factory, fake_server
):
    """An open but silent peer cannot keep the entry healthy indefinitely."""
    await setup_entry(hass, config_entry)

    async def never_reply():
        await asyncio.Event().wait()

    fake_server.status.side_effect = never_reply
    with patch(
        "custom_components.snapcast.coordinator.CONNECTION_TIMEOUT_SECONDS", 0.01
    ):
        await config_entry.runtime_data.async_refresh()
    assert not config_entry.runtime_data.connected
    assert hass.states.get(MEDIA_PLAYER_ID).state == STATE_UNAVAILABLE
    fake_server.stop.assert_called_once()


async def test_startup_timeout_closes_partial_connection(
    hass, config_entry, snapserver_factory, fake_server
):
    """A peer that never answers startup is stopped before HA retries setup."""

    async def never_start():
        await asyncio.Event().wait()

    fake_server.start.side_effect = never_start
    with patch(
        "custom_components.snapcast.coordinator.CONNECTION_TIMEOUT_SECONDS", 0.01
    ):
        await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    fake_server.stop.assert_called_once()
    assert fake_server.on_disconnect is None


async def test_frozen_last_seen_marks_client_unavailable_and_recovers(
    hass, config_entry, snapserver_factory, fake_server
):
    """A connected flag cannot hide a frozen heartbeat; advancing it recovers."""
    client = fake_server.client("aa:bb:cc")
    client._client = {"lastSeen": {"sec": 100, "usec": 0}}
    await setup_entry(hass, config_entry)
    coordinator = config_entry.runtime_data
    with patch.object(hass.loop, "time", return_value=hass.loop.time() + 61):
        await coordinator.async_refresh()
        assert hass.states.get(MEDIA_PLAYER_ID).state == STATE_UNAVAILABLE
        assert coordinator.client_is_stale(client)
        client._client["lastSeen"]["sec"] = 101
        await coordinator.async_refresh()
        assert hass.states.get(MEDIA_PLAYER_ID).state == "playing"


async def test_late_object_callback_does_not_resurrect_entities(
    hass, config_entry, snapserver_factory, fake_server
):
    """An old per-object callback after a disconnect cannot claim recovery."""
    await setup_entry(hass, config_entry)
    client = fake_server.client("aa:bb:cc")
    callback = client.set_callback.call_args.args[0]
    fake_server.on_disconnect(OSError("lost"))
    callback(client)
    assert hass.states.get(MEDIA_PLAYER_ID).state == STATE_UNAVAILABLE
    assert not config_entry.runtime_data.last_update_success


async def test_unload_awaits_inflight_reconnect(
    hass, config_entry, snapserver_factory, fake_server
):
    """Unloading while startup awaits I/O cancels it and closes both transports."""
    await setup_entry(hass, config_entry)
    fake_server.on_disconnect(OSError("lost"))
    coordinator = config_entry.runtime_data
    entered = asyncio.Event()

    async def blocked_connect():
        entered.set()
        await asyncio.Event().wait()

    with patch.object(coordinator, "_connect", side_effect=blocked_connect):
        await asyncio.wait_for(entered.wait(), 2)
        task = coordinator._reconnect_task
        assert await hass.config_entries.async_unload(config_entry.entry_id)
        assert task.done()
        assert coordinator.server is None
        assert not coordinator.connected


async def test_real_tcp_peer_stops_answering(hass, socket_enabled):
    """A real JSON-RPC connection that goes silent is closed and retried."""
    import json

    writers = []
    handlers = []
    requests = []
    silent = False

    async def serve(reader, writer):
        writers.append(writer)
        handlers.append(asyncio.current_task())
        try:
            while line := await reader.readline():
                request = json.loads(line)
                requests.append(request["method"])
                if silent:
                    continue
                status = {
                    "server": {
                        "server": {"snapserver": {"version": "0.35.0"}},
                        "groups": [],
                        "streams": [],
                    }
                }
                writer.write(
                    (
                        json.dumps(
                            {"id": request["id"], "jsonrpc": "2.0", "result": status}
                        )
                        + "\r\n"
                    ).encode()
                )
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    listener = await asyncio.start_server(serve, "127.0.0.1", 0)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Snapcast",
        data={
            CONF_HOST: "127.0.0.1",
            CONF_PORT: listener.sockets[0].getsockname()[1],
        },
    )
    try:
        await setup_entry(hass, entry)
        assert entry.state is ConfigEntryState.LOADED
        assert requests.count("Server.GetStatus") >= 2
        silent = True
        with patch(
            "custom_components.snapcast.coordinator.CONNECTION_TIMEOUT_SECONDS", 0.01
        ):
            await entry.runtime_data.async_refresh()
        assert not entry.runtime_data.connected
        assert not entry.runtime_data.last_update_success
        assert entry.runtime_data.server is None
        assert requests.count("Server.GetStatus") >= 3
        assert entry.runtime_data._reconnect_task is not None
        assert await hass.config_entries.async_unload(entry.entry_id)
    finally:
        listener.close()
        await listener.wait_closed()
        for writer in writers:
            writer.close()
        if handlers:
            await asyncio.gather(*handlers)
