# Snapcast Plus Operational Polish Design

## Goal

Improve the integration's operability and maintainability without changing its drop-in entity and service compatibility contract.

## Scope

1. Make all seven Snapcast services discoverable and documented in Home Assistant's service UI.
2. Add a reconfigure flow that validates a new host/port before reloading the existing entry.
3. Add config-entry diagnostics with connection, reconnect, entity, and persistence health data while redacting the configured host.
4. Add an explicit cleanup service for unavailable historical group identities and remove their registry entries.
5. Add negative-path and persistence-oriented tests, lint/coverage checks in CI, and correct the reconnection wording in the README.

## Design

### Service metadata

`services.yaml`, `strings.json`, and `translations/en.json` will describe `reconcile_group`, `create_zone`, `update_zone`, and `remove_zone` in addition to the three existing services. Schemas remain in `services.py`; the metadata will expose entity selectors and required/optional fields without changing service names or payloads.

### Reconfiguration

`SnapcastConfigFlow.async_step_reconfigure` will use the current config entry, validate the proposed connection with `create_server(..., reconnect=False)`, stop the probe, and call `async_update_reload_and_abort` with the new host and port. DNS and socket failures reuse existing translated errors. The user flow's duplicate-entry behavior remains unchanged.

### Diagnostics

`diagnostics.py` will expose a redacted dictionary containing connection status, last-update status, reconnect delay, active client/group counts, stored zone count, and historical group-binding counts. No host, client IDs, stream metadata, or user names will be returned.

### Historical group cleanup

The coordinator will expose `async_cleanup_groups() -> list[str]`, removing only bindings whose physical Snapcast group is unavailable and deleting their stored membership snapshots. The service will validate the config entry, remove matching group entities from the registry, and reload that entry so no stale entity remains. Active group bindings are never touched.

### Quality gates

CI will run the existing tests with coverage (minimum 85%) and Ruff. The README will state that entities become unavailable during an outage and recover after reconnection. Existing Python and Home Assistant version floors remain unchanged.

## Compatibility and failure behavior

- Existing entity IDs, unique IDs, and service payloads remain unchanged.
- Reconfigure failures keep the form open with the existing error translations.
- Diagnostics must succeed while the entry is loaded and must not expose identifying Snapcast data.
- Cleanup is explicit and irreversible for historical group entity identities, so it is not automatic.

## Verification

- Add tests for reconfigure success/failure, diagnostics redaction, cleanup behavior, and all service metadata keys.
- Run the full pytest suite with coverage, Ruff, and JSON parsing checks.
