"""Shared fixtures for Snapcast Plus tests.

The repo is flat (HACS ``content_in_root``), but Home Assistant's loader
imports custom integrations as ``custom_components.<domain>``.  A symlink
``custom_components/snapcast -> repo root`` (gitignored) bridges the two
layouts.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
_CC_DIR = ROOT / "custom_components"
_LINK = _CC_DIR / "snapcast"
_CC_DIR.mkdir(exist_ok=True)
if not _LINK.exists():
    _LINK.symlink_to(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading the integration from custom_components in every test."""
    return


class FakeSnapserver:
    """Stand-in for snapcast.control.server.Snapserver.

    Stores the callbacks the coordinator registers so tests can fire
    connect/disconnect/update events, and serves clients from a dict.
    """

    def __init__(self) -> None:
        self.clients_by_id: dict[str, MagicMock] = {}
        self.groups_by_id: dict[str, MagicMock] = {}
        self.on_update = None
        self.on_connect = None
        self.on_disconnect = None
        self.on_new_client = None
        self.start = AsyncMock()
        self.stop = MagicMock()

    @property
    def clients(self):
        return list(self.clients_by_id.values())

    @property
    def groups(self):
        return list(self.groups_by_id.values())

    def client(self, identifier):
        return self.clients_by_id[identifier]

    def group(self, identifier):
        return self.groups_by_id[identifier]

    def stream(self, identifier):
        raise KeyError(identifier)

    def set_on_update_callback(self, cb):
        self.on_update = cb

    def set_new_client_callback(self, cb):
        self.on_new_client = cb

    def set_on_connect_callback(self, cb):
        self.on_connect = cb

    def set_on_disconnect_callback(self, cb):
        self.on_disconnect = cb


def make_group(
    identifier: str = "group-a",
    name: str = "Living Room",
    stream: str = "stream_a",
    stream_status: str = "playing",
    muted: bool = False,
    client_ids: list[str] | None = None,
) -> MagicMock:
    """Build a mock Snapgroup."""
    group = MagicMock()
    group.identifier = identifier
    group.friendly_name = name
    group.stream = stream
    group.stream_status = stream_status
    group.muted = muted
    group.volume = 50
    group.clients = client_ids or []
    group.streams_by_name = MagicMock(return_value={})
    group.set_stream = AsyncMock()
    group.add_client = AsyncMock()
    group.remove_client = AsyncMock()
    group.set_volume = AsyncMock()
    group.set_muted = AsyncMock()
    group.snapshot = MagicMock()
    group.restore = AsyncMock()
    return group


def make_client(
    identifier: str = "aa:bb:cc",
    name: str = "Living Room",
    volume: int = 50,
    muted: bool = False,
    connected: bool = True,
    latency: int = 10,
    group: MagicMock | None = None,
) -> MagicMock:
    """Build a mock Snapclient."""
    client = MagicMock()
    client.identifier = identifier
    client.friendly_name = name
    client.volume = volume
    client.muted = muted
    client.connected = connected
    client.latency = latency
    client.group = group if group is not None else make_group(
        client_ids=[identifier]
    )
    client.set_volume = AsyncMock()
    client.set_muted = AsyncMock()
    client.set_latency = AsyncMock()
    client.snapshot = MagicMock()
    client.restore = AsyncMock()
    return client


@pytest.fixture
def fake_server() -> FakeSnapserver:
    """A fake Snapserver with one connected client."""
    server = FakeSnapserver()
    client = make_client()
    server.clients_by_id[client.identifier] = client
    server.groups_by_id[client.group.identifier] = client.group
    return server
