# Snapcast Plus

Custom Home Assistant integration for [Snapcast](https://github.com/badaix/snapcast) — a multi-room synchronous audio solution.

Based on the official Home Assistant Snapcast integration with key bug fixes and reliability improvements.

## Why Snapcast Plus

The official integration has a fundamental architectural flaw: it stores `Snapclient` object references in entities and reuses them indefinitely. When the Snapcast server restarts or the WebSocket reconnects, those references become stale because the snapcast library creates new Python objects internally. The result: entities stop responding to commands, show wrong state, and cannot recover without restarting Home Assistant.

**Snapcast Plus** solves this by never holding onto object references. Every property and action that needs the client or group data fetches a fresh reference from the coordinator on each access. Here is a detailed comparison:

### Architecture

| Aspect | Official Integration | Snapcast Plus |
|---|---|---|
| **Client reference storage** | Stores `Snapclient` object in `self._device` — becomes stale after reconnect | Stores only `device_id` (string) — resolves a fresh `Snapclient` via `_get_device()` on every access |
| **Group reference** | `self._device.group` — stale after reconnect | `device.group` — resolved from fresh device each time |
| **Server reference** | `self._server` — never `None`, always the same object | `self._server` — set to `None` during reconnect, recreated from scratch on each connection |

### Reconnection

| Aspect | Official Integration | Snapcast Plus |
|---|---|---|
| **Reconnection strategy** | Delegated to the snapcast library (`reconnect=True`). The library reconnects the WebSocket internally but does not recreate `Snapclient`/`Snapgroup` objects, causing the stale reference problem. | Self-managed (`reconnect=False`). On disconnect, a background task attempts reconnection with exponential backoff (1s → 2s → 4s → … → 60s max). On success, a brand new `Snapserver` is created, so all child objects are fresh. |
| **Reconnect backoff** | Whatever the library does (no control) | Exponential backoff up to 60s max |
| **Reconnect task cleanup** | Not handled (no explicit task to cancel) | Reconnect task is cancelled cleanly on `disconnect()` |

### Updates

| Aspect | Official Integration | Snapcast Plus |
|---|---|---|
| **Update mechanism** | Push-only (`update_interval=None`). If a push callback is missed, entities can get stuck indefinitely. | Push + 45-second polling fallback (`update_interval=timedelta(seconds=45)`). Even if push fails, the state is refreshed periodically. |
| **On disconnect behavior** | Calls `async_set_update_error(ex)` — sets error flag but does not notify listeners for re-registration | Explicitly sets `last_update_success = False` AND calls `async_update_listeners()` so entities immediately know the server is gone |

### Entity availability

| Aspect | Official Integration | Snapcast Plus |
|---|---|---|
| **Base entity `available`** | Inherits default from `CoordinatorEntity` (checks `coordinator.last_update_success`) | Custom override in `SnapcastCoordinatorEntity` that checks `coordinator.last_update_success` |
| **Client entity `available`** | No additional checks beyond the base class | Also verifies the client still exists on the server (`_get_device() is not None`) — dual-layer safety |
| **Availability on disconnect** | Entities may remain `available=True` because `async_set_update_error` does not always propagate correctly to the entity level | Entities immediately become unavailable because `last_update_success = False` is set and listeners are notified |

### Defensive null-safety

| Aspect | Official Integration | Snapcast Plus |
|---|---|---|
| **Null guards on server** | Assumes `server` is always available — no `None` checks | Every method that accesses the server has `if server is None: return` guards |
| **Null guards on device** | Assumes `self._device` is always valid | `_get_device()` can return `None`; all callers handle it gracefully (return default values, skip operations) |

### Dynamic client detection

| Aspect | Official Integration | Snapcast Plus |
|---|---|---|
| **New clients** | Detected and entities created, BUT the new entity receives a `Snapclient` object that will become stale on the next reconnect | Entities store only `device_id`, so they survive reconnections and always resolve fresh data |
| **Removed clients** | Entities are removed from the registry | Same behavior |
| **`_update_clients` guard** | No guard for `server is None` | Checks `if coordinator.server is None: return` before iterating clients |

## Installation

### HACS (recommended)

1. Go to **HACS > Integrations > ⋮ > Custom repositories**
2. Add `https://github.com/NaturalDevCR/snapcast_plus` as type **Integration**
3. Search for "Snapcast Plus" and install
4. Restart Home Assistant

### Manual

Copy the `snapcast_plus` folder into your `custom_components` directory:

```
custom_components/
└── snapcast_plus/
    ├── __init__.py
    ├── config_flow.py
    ├── const.py
    ├── coordinator.py
    ├── entity.py
    ├── icons.json
    ├── manifest.json
    ├── media_player.py
    ├── sensor.py
    ├── services.py
    ├── services.yaml
    ├── strings.json
    └── translations/
```

Then restart Home Assistant.

## Configuration

After installation, go to **Settings > Devices & Services > Add Integration** and search for **Snapcast Plus**.

- **Host**: IP address or hostname of your Snapcast server
- **Port**: Snapcast control port (default: `1704`)

## Features

### Media player entities

Each Snapcast client appears as a `media_player` entity in Home Assistant, exposing:

- Volume control and mute
- Stream/source selection
- Media metadata (title, artist, album, cover art, duration, position)
- **Grouping** — join and unjoin players using Home Assistant's native speaker groups
- Media progress bar with position tracking

### Latency sensors

Each Snapcast client also gets a dedicated `sensor` entity reporting its current latency in milliseconds. This enables latency-based automations (e.g., alert when a speaker falls out of sync).

### Services

| Service | Description |
|---|---|
| `snapcast_plus.snapshot` | Take a snapshot of a client's current state |
| `snapcast_plus.restore` | Restore a previously saved snapshot |
| `snapcast_plus.set_latency` | Set client latency in milliseconds |

### Auto-discovery

Clients that connect to or disconnect from the Snapcast server are automatically added or removed from Home Assistant without restarting.

### Reconnection

If the Snapcast server restarts or the connection drops, the integration reconnects automatically with exponential backoff (1s → 2s → 4s → … → 60s max). All entities remain available and recover their state.

## Requirements

- Home Assistant **2024.2.0** or newer
- A running [Snapcast](https://github.com/badaix/snapcast) server (v0.27.0+)

### HA 2026.x compatibility

This integration is compatible with Home Assistant 2026.5+. The deprecated `extra_state_attributes` property has been replaced with dedicated `sensor` entities per client, following the modern HA architecture.

## Troubleshooting

| Problem | Solution |
|---|---|
| Entities show as unavailable | Check that the Snapcast server is running and reachable on the configured host:port |
| "Cannot connect" on setup | Verify the host address and port. Try the server IP instead of hostname |
| Volume not updating | The 45s polling fallback will pick it up. Push updates are instant |

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.

This project includes code derived from the [Home Assistant Snapcast integration](https://github.com/home-assistant/core/tree/dev/homeassistant/components/snapcast), copyright the Home Assistant project contributors.
