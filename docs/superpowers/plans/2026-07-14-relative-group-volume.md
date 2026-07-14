# Relative Snapcast Group Volume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore relative volume and visible mute controls for dynamic Snapcast group players.

**Architecture:** `SnapcastGroupDevice` exposes the group's average volume and delegates slider changes to the installed Snapcast library's proportional `Snapgroup.set_volume` method. Zones remain unchanged because they can target more than one group.

**Tech Stack:** Python 3.13, Home Assistant `MediaPlayerEntity`, snapcast 2.3.8, pytest-homeassistant-custom-component.

## Global Constraints

- The group slider must call `Snapgroup.set_volume`; it must not set each client to a uniform value.
- Dynamic groups retain mute and source controls and do not gain snapshot, restore, or latency.
- Persistent zones do not gain volume controls.
- New behavior is introduced by a failing focused test before production code.

---

### Task 1: Expose native relative group volume

**Files:**
- Modify: `media_player.py`
- Modify: `tests/test_integration.py`

**Interfaces:**
- `SnapcastGroupDevice.volume_level -> float | None` returns `group.volume / 100`.
- `SnapcastGroupDevice.async_set_volume_level(volume: float)` calls `await group.set_volume(round(volume * 100))`.

- [ ] **Step 1: Write failing group volume test**

```python
async def test_group_volume_uses_snapcast_relative_adjustment(...):
    await setup_entry(hass, config_entry)
    group = hass.states.get(GROUP_ID)
    assert group.attributes["volume_level"] == 0.5
    await hass.services.async_call(
        "media_player", "volume_set",
        {"entity_id": GROUP_ID, "volume_level": 0.37}, blocking=True,
    )
    fake_server.group("group-a").set_volume.assert_awaited_once_with(37)
```

- [ ] **Step 2: Run it to verify failure**

Run: `/Users/jdavidoa91/Dev/snapcast_plus/.venv/bin/python -m pytest tests/test_integration.py::test_group_volume_uses_snapcast_relative_adjustment -v`

Expected: FAIL because groups currently have no `volume_level` and reject `volume_set`.

- [ ] **Step 3: Implement minimum group-volume behavior**

Add `VOLUME_SET` to `SnapcastGroupDevice._attr_supported_features`, return the
current `group.volume / 100` from `volume_level`, and delegate the slider value
to `group.set_volume(round(volume * 100))`. Raise `ServiceValidationError` if
the group disappeared before the command.

- [ ] **Step 4: Run focused tests**

Run: `/Users/jdavidoa91/Dev/snapcast_plus/.venv/bin/python -m pytest tests/test_integration.py::test_group_volume_uses_snapcast_relative_adjustment tests/test_integration.py::test_group_entity_only_controls_mute_and_source -v`

Expected: Replace the obsolete no-volume test with a zone-only assertion; both focused tests PASS.

### Task 2: Document and release the correction

**Files:**
- Modify: `README.md`
- Modify: `manifest.json`
- Test: `tests/`

- [ ] **Step 1: Update README**

Explain that a group slider is the average client volume, that Snapcast applies
relative distribution rather than uniform values, and that this is why mute is
visible in Home Assistant's native dialog.

- [ ] **Step 2: Bump version**

Set the manifest version to `1.3.1`.

- [ ] **Step 3: Run final verification**

Run: `/Users/jdavidoa91/Dev/snapcast_plus/.venv/bin/python -m pytest tests/ -v && git diff --check`

Expected: all tests pass and no whitespace errors.
