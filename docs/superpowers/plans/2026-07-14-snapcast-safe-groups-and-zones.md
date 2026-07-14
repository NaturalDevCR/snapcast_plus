# Grupos seguros y zonas persistentes de Snapcast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hacer segura la reconciliación de grupos dinámicos y añadir zonas persistentes con mute y fuente.

**Architecture:** El coordinador seguirá guardando enlaces lógicos de grupo, pero solo reusará una entidad con ID físico igual o miembros idénticos. Un segundo `Store` guardará definiciones de zona por entrada; las entidades de zona resolverán los grupos de sus clientes justo antes de leer estado o enviar comandos. Los servicios validan entidades del registro, mutan el almacén correspondiente y recargan solo la entrada afectada cuando es necesario retirar una entidad.

**Tech Stack:** Python 3.13, Home Assistant custom integration APIs, `DataUpdateCoordinator`, `Store`, `MediaPlayerEntity`, pytest-homeassistant-custom-component.

## Global Constraints

- Mantener el dominio `snapcast` y los `unique_id` existentes.
- No conservar referencias a objetos de la biblioteca Snapcast entre actualizaciones.
- Un grupo solo se reasigna automáticamente por identidad física o conjunto completo de miembros idéntico.
- Grupos y zonas solo admiten mute y selección de fuente; los clientes conservan volumen y los servicios de snapshot, restore y latencia.
- Toda funcionalidad nueva sigue el ciclo prueba roja, implementación mínima y prueba verde.

---

### Task 1: Hacer conservadora la reconciliación automática

**Files:**
- Modify: `coordinator.py`
- Modify: `tests/test_integration.py`

**Interfaces:**
- `SnapcastUpdateCoordinator.reconcile_groups()` conserva `group_bindings` y `group_members`.
- Para un grupo físico sin enlace, solo reutiliza un `logical_id` sin enlace cuando el conjunto de miembros es igual y el candidato es único.

- [ ] **Step 1: Write the failing partial-overlap regression test**

```python
async def test_group_with_partial_member_overlap_gets_a_new_entity(...):
    await setup_entry(hass, config_entry)
    fake_server.groups_by_id = {"split": make_group("split", ["aa:bb:cc"])}
    fake_server.on_update()
    await hass.async_block_till_done()
    assert config_entry.runtime_data.group_bindings == {
        "group-a": None, "split": "split"
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_integration.py::test_group_with_partial_member_overlap_gets_a_new_entity -v`

Expected: FAIL because the current maximum-overlap heuristic binds `group-a` to `split`.

- [ ] **Step 3: Implement exact-only matching**

Remove the `highest` / `best` member-overlap branch from
`SnapcastUpdateCoordinator.reconcile_groups()`. Retain the candidate only
when exactly one disappeared logical group has the exact member set;
otherwise use the physical ID as a new logical ID.

- [ ] **Step 4: Run focused tests to verify green**

Run: `.venv/bin/python -m pytest tests/test_integration.py::test_group_entity_rebinds_when_snapcast_changes_group_id tests/test_integration.py::test_group_with_partial_member_overlap_gets_a_new_entity -v`

Expected: PASS.

### Task 2: Add explicit reconciliation service

**Files:**
- Modify: `coordinator.py`
- Modify: `services.py`
- Modify: `media_player.py`
- Modify: `tests/test_integration.py`

**Interfaces:**
- `async_reassign_group(old_logical_id: str, new_logical_id: str) -> None` persists the old logical identity pointing at the active physical target and deletes the duplicate logical record.
- `snapcast.reconcile_group(old_entity_id, new_entity_id)` validates same-entry group entities, applies the reassignment, removes the target registry entity, and reloads that entry.

- [ ] **Step 1: Write the failing service behavior test**

```python
await hass.services.async_call(DOMAIN, "reconcile_group", {
    "old_entity_id": GROUP_ID, "new_entity_id": new_group_entity_id,
}, blocking=True)
assert coordinator.group_bindings["group-a"] == "split"
assert "split" not in coordinator.group_bindings
```

- [ ] **Step 2: Run it and verify service-not-found failure**

Run: `.venv/bin/python -m pytest tests/test_integration.py::test_reconcile_group_service_reuses_old_entity -v`

- [ ] **Step 3: Implement validation and reassignment**

Register a raw Home Assistant service with two entity IDs. Resolve each entry
through `entity_registry`, require `media_player`, platform `snapcast`, group
unique-ID prefix, the same loaded config entry, an unavailable old group, and
an active new group. Persist reassignment, remove the new registry entity, and
reload only the validated config entry.

- [ ] **Step 4: Run focused tests to verify green**

Run: `.venv/bin/python -m pytest tests/test_integration.py::test_reconcile_group_service_reuses_old_entity -v`

Expected: PASS.

### Task 3: Persist and expose user-defined zones

**Files:**
- Modify: `coordinator.py`
- Modify: `const.py`
- Modify: `media_player.py`
- Modify: `services.py`
- Modify: `tests/test_integration.py`

**Interfaces:**
- A zone record has `id: str`, `name: str`, and `client_ids: list[str]` in `snapcast_zones.<entry_id>`.
- `create_zone`, `update_zone`, and `remove_zone` receive registered client or zone entity IDs and resolve a single `SnapcastUpdateCoordinator`.
- `SnapcastZoneDevice(coordinator, zone_id)` has the stable unique ID `snapcast_zone_{host_id}_{zone_id}`.

- [ ] **Step 1: Write failing creation and multi-group mute tests**

```python
await hass.services.async_call(DOMAIN, "create_zone", {
    "name": "Casa", "clients": [MEDIA_PLAYER_ID],
}, blocking=True)
zone = hass.states.get("media_player.casa_snapcast_zone")
assert zone is not None
await hass.services.async_call("media_player", "volume_mute", {
    "entity_id": zone.entity_id, "is_volume_muted": True,
}, blocking=True)
```

- [ ] **Step 2: Run it to verify the service is absent**

Run: `.venv/bin/python -m pytest tests/test_integration.py::test_zone_controls_current_groups_of_its_clients -v`

- [ ] **Step 3: Implement zone storage and lifecycle**

Load zone records in coordinator setup, persist mutations before notifying
listeners, and teach media-player setup to add all stored zone entities. Zone
create/update/remove services validate client/zone registry entries from one
Snapcast config entry. For a deletion, remove its entity registry entry and
reload the affected entry so its state disappears.

- [ ] **Step 4: Run focused zone lifecycle tests to verify green**

Run: `.venv/bin/python -m pytest tests/test_integration.py::test_zone_controls_current_groups_of_its_clients tests/test_integration.py::test_zone_persists_when_clients_change_groups -v`

Expected: PASS.

- [ ] **Step 5: Write and pass source/validation tests**

Test a source shared by all target groups, rejection of a source missing from
one group, rejection of a zone spanning entries, and removal of a zone.

Run: `.venv/bin/python -m pytest tests/test_integration.py -v`

Expected: PASS.

### Task 4: Document and release the behavior

**Files:**
- Modify: `README.md`
- Modify: `manifest.json`
- Test: `tests/`

- [ ] **Step 1: Update README**

Explain dynamic group entities, the no-volume policy, automatic exact-match
rules, the `reconcile_group` recovery call, all zone services with YAML
examples, and practical migration/troubleshooting guidance.

- [ ] **Step 2: Bump version**

Set `manifest.json` to `1.3.0`.

- [ ] **Step 3: Run final verification**

Run: `.venv/bin/python -m pytest tests/ -v && git diff --check`

Expected: all tests pass and no whitespace errors.
