# Snapcast Plus

Custom Home Assistant integration for [Snapcast](https://github.com/badaix/snapcast) — a multi-room synchronous audio solution.

Based on the official Home Assistant Snapcast integration with key bug fixes and reliability improvements.

## Why Snapcast Plus

The official integration has known issues where media player entities become unresponsive after a server reconnection. This happens because client/group references become stale internally. **Snapcast Plus** fixes that:

| Issue | Official | Snapcast Plus |
|---|---|---|
| Stale references after reconnect | Yes | Fixed — always fetches fresh client objects |
| Reconnection logic | Delegated to library | Self-managed with exponential backoff |
| Push-only updates | Yes | Push + 45s polling fallback |
| Dynamic client add/remove | Manual | Automatic |

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
- Latency display per client

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

- Home Assistant **2024.1.0** or newer
- A running [Snapcast](https://github.com/badaix/snapcast) server (v0.27.0+)

## Troubleshooting

| Problem | Solution |
|---|---|
| Entities show as unavailable | Check that the Snapcast server is running and reachable on the configured host:port |
| "Cannot connect" on setup | Verify the host address and port. Try the server IP instead of hostname |
| Volume not updating | The 45s polling fallback will pick it up. Push updates are instant |

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.

This project includes code derived from the [Home Assistant Snapcast integration](https://github.com/home-assistant/core/tree/dev/homeassistant/components/snapcast), copyright the Home Assistant project contributors.
