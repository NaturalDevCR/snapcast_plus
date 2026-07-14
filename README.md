# Snapcast Plus

A drop-in replacement for the official Home Assistant [Snapcast](https://www.home-assistant.io/integrations/snapcast) integration — same `domain`, same `unique_id`s, same services, same config flow, but with critical reliability fixes and quality-of-life improvements baked in.

## Why a drop-in replacement?

The official Snapcast integration has a fundamental architectural flaw: it stores `Snapclient` object references in entities and reuses them indefinitely. When the Snapcast server restarts or the WebSocket reconnects, those references become stale because the snapcast library creates new Python objects internally. The result: entities stop responding to commands, show wrong state, and cannot recover without restarting Home Assistant.

**Snapcast Plus** is published under the same integration domain (`snapcast`) with the same `unique_id` format (`snapcast_client_{host}:{port}_{client_id}`) and the same services (`snapcast.snapshot`, `snapcast.restore`, `snapcast.set_latency`). Home Assistant silently takes the new code over from the official one — no config migration, no entity renaming, no automation edits, no dashboard changes. Existing entries, entities, scripts, and templates keep working unchanged while every reliability issue is fixed underneath.

Here is a detailed comparison:

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

### Latency exposure

| Aspect | Official Integration | Snapcast Plus |
|---|---|---|
| **Latency access** | Exposed only as `extra_state_attributes["latency"]` on the media_player | Dedicated `sensor.snapcast_client_*_latency` entities (with proper `unit_of_measurement`, `device_class`, `state_class`) **and** still exposed as `extra_state_attributes["latency"]` on the media_player for full back-compat |

## Drop-in compatibility contract

These are deliberately kept identical to the official integration so the upgrade is invisible:

| Surface | Value |
|---|---|
| **Integration domain** | `snapcast` |
| **Media player unique_id** | `snapcast_client_{host}:{port}_{client_id}` |
| **Latency sensor unique_id** | `snapcast_client_{host}:{port}_{client_id}_latency` |
| **Config flow keys** | `host` (string), `port` (int, default `1704`) |
| **Config flow title** | `Snapcast` |
| **Services** | `snapcast.snapshot`, `snapcast.restore`, `snapcast.set_latency` |
| **`media_player` features** | `VOLUME_MUTE`, `VOLUME_SET`, `SELECT_SOURCE`, `GROUPING` |
| **`media_player` properties** | `state`, `volume_level`, `is_volume_muted`, `source`, `source_list`, `group_members`, `media_title`, `media_artist`, `media_album_name`, `media_album_artist`, `media_track`, `media_duration`, `media_position`, `media_image_url`, `extra_state_attributes["latency"]` |
| **Required HA version** | `2024.2.0+` |
| **Python dependency** | `snapcast==2.3.8` |

## Installation

### HACS (recommended)

1. Go to **HACS > Integrations > ⋮ > Custom repositories**
2. Add `https://github.com/NaturalDevCR/snapcast_plus` as type **Integration**
3. Search for "Snapcast" and install
4. Restart Home Assistant

Because `snapcast_plus` registers under the `snapcast` domain, Home Assistant automatically picks up any existing official Snapcast config entry on startup. Your existing media_player entities, dashboards, scripts, and automations keep working unchanged.

> Folder name is purely cosmetic. HACS will install the repo as `custom_components/snapcast_plus/`, but the integration registers as `snapcast`. If you prefer, rename the folder to `custom_components/snapcast/` — completely optional.

### Manual

Copy the contents of this repo into a folder under `custom_components/`:

```
custom_components/
└── snapcast_plus/      ← folder name is irrelevant, domain comes from manifest.json
    ├── __init__.py
    ├── manifest.json   ← declares `"domain": "snapcast"`
    ├── ...
```

Restart Home Assistant. The custom `snapcast` integration will take precedence over the built-in one.

## Configuration

After installation, go to **Settings > Devices & Services**. If you already had the official integration configured, your entry will be reused automatically. Otherwise, click **Add Integration** and search for **Snapcast**.

- **Host**: IP address or hostname of your Snapcast server
- **Port**: Snapcast control port (default: `1704`)

## Features

### Media player entities

Each Snapcast client appears as a `media_player` entity, exposing:

- Volume control and mute
- Stream/source selection
- Media metadata (title, artist, album, cover art, duration, position)
- **Grouping** — join and unjoin players using Home Assistant's native speaker groups
- Media progress bar with position tracking

### Dynamic Snapcast group entities

Each live Snapcast group also appears as a `media_player` entity. These are a
direct view of groups currently reported by the Snapcast server, so they are
useful for selecting a source, muting, or adjusting a specific, current
playback group.

Groups expose:

- Relative volume
- Mute / unmute
- Source selection

The group volume slider is the average of its clients' current volume. Moving
it delegates to Snapcast's native group-volume algorithm, which adjusts every
client **relatively** instead of assigning all clients the same value. A group
with clients at different levels therefore keeps those differences when its
volume changes; Snapcast proportionally moves each client toward 0 or 100.

The volume capability also makes Home Assistant show its native mute button in
the media-player dialog. Home Assistant places that button inside the volume
control rather than rendering a mute-only control.

Groups do **not** expose snapshot, restore, latency, or grouping controls. Use
client entities when individual, non-relative volume control is intended.

#### What happens when Snapcast changes a group?

Snapcast groups are dynamic: every client belongs to a group, and joining or
splitting clients can destroy a group and create another one with a different
ID. Snapcast Plus keeps a historical group entity automatically only when:

1. Snapcast keeps the same physical group ID; or
2. it replaces the ID but the new group has exactly the same complete set of
   client IDs.

It intentionally does not match a group by partial member overlap. For
example, after splitting `Kitchen + Bedroom`, it would be unsafe to guess that
the old entity should become either half. The old entity remains unavailable
and the new live group receives its own entity instead.

If you decide that an unavailable historical entity should represent a newly
created group, use the explicit service below. It preserves the old entity ID,
removes the new duplicate entity, and reloads only that Snapcast entry:

```yaml
action: snapcast.reconcile_group
data:
  old_entity_id: media_player.house_snapcast_group       # unavailable group
  new_entity_id: media_player.living_room_snapcast_group # active group
```

Both entities must be Snapcast **group** entities belonging to the same
Snapcast server. This operation is intentionally manual: it is the explicit
choice required for ambiguous merges and splits.

### Persistent Snapcast zones

A zone is a stable, user-defined `media_player` made from one or more Snapcast
**client** entities. Unlike a dynamic group, its identity does not depend on a
Snapcast group ID. This is the recommended entity for concepts such as
“Whole house”, “Downstairs”, or “Bedrooms”.

At the moment an action is sent, the zone finds the distinct current Snapcast
groups that contain its clients:

- Mute is applied to every one of those groups.
- Source selection is applied to every one, but only when that source exists
  in all of them.
- The zone reports a source only when all its current groups use the same
  source, and its source list is the intersection of their available sources.

Zones have mute and source controls only; they intentionally have no volume,
snapshot, restore, or latency control. If the zone's clients later join,
separate, or receive new Snapcast group IDs, the zone entity continues to work
without reconciliation.

Create a zone from the **client** entities you want it to cover:

```yaml
action: snapcast.create_zone
data:
  name: Whole house
  clients:
    - media_player.kitchen_snapcast_client
    - media_player.bedroom_snapcast_client
    - media_player.office_snapcast_client
```

The resulting entity is normally named `media_player.whole_house_snapcast_zone`.
Rename it or replace its clients with:

```yaml
action: snapcast.update_zone
data:
  zone_entity_id: media_player.whole_house_snapcast_zone
  name: House
  clients:
    - media_player.kitchen_snapcast_client
    - media_player.bedroom_snapcast_client
```

Either `name` or `clients` is sufficient for an update. All listed clients must
belong to the same Snapcast server entry. To remove a zone:

```yaml
action: snapcast.remove_zone
data:
  zone_entity_id: media_player.whole_house_snapcast_zone
```

### Latency sensors

Each Snapcast client also gets a dedicated `sensor` entity reporting its current latency in milliseconds. This enables latency-based automations (e.g., alert when a speaker falls out of sync) using standard HA sensor machinery.

### Services

| Service | Description |
|---|---|
| `snapcast.snapshot` | Take a snapshot of a client's current state |
| `snapcast.restore` | Restore a previously saved snapshot |
| `snapcast.set_latency` | Set client latency in milliseconds |
| `snapcast.reconcile_group` | Explicitly attach an unavailable group entity to an active replacement group |
| `snapcast.create_zone` | Create a persistent mute/source zone from Snapcast client entities |
| `snapcast.update_zone` | Rename a persistent zone or replace its client entities |
| `snapcast.remove_zone` | Remove a persistent zone |

### Auto-discovery

Clients that connect to or disconnect from the Snapcast server are automatically added or removed from Home Assistant without restarting.

### Reconnection

If the Snapcast server restarts or the connection drops, the integration reconnects automatically with exponential backoff (1s → 2s → 4s → … → 60s max). All entities remain available and recover their state.

## Requirements

- Home Assistant **2024.2.0** or newer
- A running [Snapcast](https://github.com/badaix/snapcast) server (v0.27.0+)

### HA 2026.x compatibility

This integration supports Home Assistant **2024.2.0 through current 2026.x releases**. The deprecated `extra_state_attributes` pattern is supplemented with dedicated `sensor` entities per client, following the modern HA architecture — but the attribute is still exposed for back-compat.

## Troubleshooting

| Problem | Solution |
|---|---|
| Entities show as unavailable | Check that the Snapcast server is running and reachable on the configured host:port |
| "Cannot connect" on setup | Verify the host address and port. Try the server IP instead of hostname |
| Volume not updating | The 45s polling fallback will pick it up. Push updates are instant |
| An old group is unavailable after clients join or split | This is safe by design when membership changed. Use the new group's entity, a persistent zone, or explicitly call `snapcast.reconcile_group` if it is the same logical area. |
| I need a stable “whole house” control | Create a persistent zone with `snapcast.create_zone`; do not automate against a dynamic group entity. |
| Old official entities still visible after install | Restart Home Assistant. HA picks up the new domain registration on cold start |

## Development

The test suite runs on the official Home Assistant test harness and covers setup/unload, the disconnect → reconnect cycle (including a regression test ensuring the polling fallback never masks a disconnect), client renames, and all commands/services:

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/python -m pytest tests/
```

CI (GitHub Actions) runs the tests plus [HACS](https://github.com/hacs/action) validation on every push and PR. Hassfest is not run: it rejects (by design) custom integrations that register a core domain, which is exactly what this drop-in replacement does.

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.

This project includes code derived from the [Home Assistant Snapcast integration](https://github.com/home-assistant/core/tree/dev/homeassistant/components/snapcast), copyright the Home Assistant project contributors.
