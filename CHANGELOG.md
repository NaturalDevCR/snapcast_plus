# Changelog

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
