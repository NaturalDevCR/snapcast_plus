# Changelog

## 1.5.0 — 2026-11-05

- Query authoritative server state every 15 seconds with a 10-second deadline.
- Recover silent connections and clean up failed or cancelled startup attempts.
- Mark connected clients unavailable when their lastSeen stops advancing for 60 seconds.
- Fix discovery callbacks for new clients and ignore callbacks from replaced connections.
- Await reconnect cancellation during unload and bound configuration probes.
- Add redacted response/disconnect timestamps, retry counts, and stale-client diagnostics.
- Preserve entity IDs and explicit offline-client states.


## 1.4.0 — 2026-08-26

### Added

- Documented all Snapcast services in Home Assistant's service UI.
- Added a reconfigure flow for changing the Snapcast host or port.
- Added redacted config-entry diagnostics for connection and persistence health.
- Added `snapcast.cleanup_groups` for explicit removal of unavailable historical group entities.
- Added regression tests, Ruff checks, and an 85% coverage gate in CI.

### Changed

- Updated reconnection documentation to explain temporary entity unavailability during outages.
- Preserved existing entity IDs, unique IDs, service names, and service payloads.
