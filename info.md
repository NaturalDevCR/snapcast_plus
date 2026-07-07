# Snapcast Plus

Drop-in replacement for the official Home Assistant Snapcast integration. Same `domain: snapcast`, same `unique_id`s, same services — but with critical reliability fixes:

- Self-managed reconnection with exponential backoff (no stale `Snapclient` references after server restarts).
- 45-second polling fallback so entities never get stuck if a push callback is missed.
- Dual-layer availability checks (coordinator + per-client existence on the server).
- Explicit `last_update_success = False` + `async_update_listeners()` on disconnect so entities go unavailable immediately.
- Defensive `None` guards everywhere.

Plus dedicated `sensor.*` entities for per-client latency (with proper `unit_of_measurement`, `device_class`, `state_class`) while still exposing `extra_state_attributes["latency"]` for back-compat.

Install via HACS as a custom repository (type: Integration). On restart, Home Assistant transparently picks up your existing Snapcast config entry — no migration needed.
