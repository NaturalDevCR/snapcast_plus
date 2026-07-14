# Entidades de grupos Snapcast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exponer los grupos de Snapcast como `media_player` estables y controlables, incluidos los cambios de ID de grupo y la reconciliación manual de entidades históricas.

**Architecture:** Un gestor persistente asigna una identidad lógica de grupo a cada ID físico de Snapcast y conserva la composición de miembros observada. Las entidades de grupo resuelven ese ID físico en cada acceso, mientras que el servicio manual reasigna una identidad antigua a un grupo nuevo y recarga la entrada para conservar el `entity_id` histórico.

**Tech Stack:** Python 3.13, Home Assistant custom integration API, `DataUpdateCoordinator`, `Store`, `MediaPlayerEntity`, pytest-homeassistant-custom-component.

## Global Constraints

- Mantener el dominio `snapcast` y los `unique_id` históricos `snapcast_group_{host}:{port}_{group_id}` cuando el grupo todavía usa su ID original.
- No conservar referencias `Snapgroup` entre actualizaciones ni reconexiones.
- No asignar automáticamente un grupo cuando la coincidencia de miembros no sea única.
- `snapcast.set_latency` solo debe aplicarse a entidades de cliente.
- Ejecutar cada prueba nueva en rojo antes de implementar el comportamiento correspondiente.

---

### Task 1: Persistir y reconciliar identidades de grupo

**Files:**
- Create: `group_registry.py`
- Modify: `coordinator.py`
- Test: `tests/test_group_registry.py`

**Interfaces:**
- Produces `SnapcastGroupRegistry.async_load()`, `async_reconcile(groups)`, `physical_id(logical_id)`, `logical_ids()`, and `async_reassign(old_logical_id, new_physical_id)`.
- `async_reconcile(groups)` consumes objects with `identifier` and `clients`, and returns the logical IDs that must be represented.
- `SnapcastUpdateCoordinator` owns `group_registry` and loads it before entity platforms set up.

- [ ] **Step 1: Write the failing exact-match and ambiguous-match tests**

```python
async def test_reconcile_preserves_logical_id_when_group_id_changes():
    registry = SnapcastGroupRegistry(hass, entry_id)
    await registry.async_load()
    assert await registry.async_reconcile([group("old", ["a", "b"])]) == {"old"}
    assert await registry.async_reconcile([group("new", ["a", "b"])]) == {"old"}
    assert registry.physical_id("old") == "new"

async def test_reconcile_does_not_choose_tied_member_overlap():
    registry = SnapcastGroupRegistry(hass, entry_id)
    await registry.async_load()
    await registry.async_reconcile([group("left", ["a"]), group("right", ["b"])])
    logical_ids = await registry.async_reconcile([group("merged", ["a", "b"])])
    assert "merged" in logical_ids
    assert registry.physical_id("left") is None
    assert registry.physical_id("right") is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_group_registry.py -v`

Expected: FAIL because `custom_components.snapcast.group_registry` does not exist.

- [ ] **Step 3: Implement the minimal persistent registry**

```python
class SnapcastGroupRegistry:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = Store[dict[str, GroupRecord]](hass, 1, f"snapcast_groups.{entry_id}")
        self._records: dict[str, GroupRecord] = {}

    async def async_reconcile(self, groups: Iterable[Snapgroup]) -> set[str]:
        # Match physical IDs, then exact member sets, then one unambiguous
        # maximum-overlap candidate; persist only when records change.
```

Store `logical_id`, `physical_id | None`, and sorted `member_ids`. Mark unmatched records with `physical_id=None`; do not delete them. Match candidates one-to-one and create a new logical ID equal to the physical ID for an unmatched active group.

- [ ] **Step 4: Run the registry tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_group_registry.py -v`

Expected: PASS with the exact-match and ambiguous-match cases green.

- [ ] **Step 5: Add and verify persistence and unambiguous-overlap tests**

```python
async def test_reconcile_restores_saved_physical_mapping_after_load():
    ...
    assert restored.physical_id("old") == "new"

async def test_reconcile_uses_unique_largest_member_overlap():
    ...
    assert registry.physical_id("old") == "new"
```

Run: `.venv/bin/python -m pytest tests/test_group_registry.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add group_registry.py coordinator.py tests/test_group_registry.py
git commit -m "feat: persist snapcast group identities"
```

### Task 2: Exponer y controlar entidades de grupo

**Files:**
- Modify: `const.py`
- Modify: `media_player.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_integration.py`

**Interfaces:**
- Consumes `SnapcastUpdateCoordinator.group_registry` from Task 1.
- Produces `SnapcastGroupDevice(coordinator, logical_id)` with `build_unique_id(host_id, logical_id)` and fresh group lookup by registry physical ID.
- Adds `GROUP_PREFIX = "snapcast_group_"` and `GROUP_SUFFIX = "Snapcast Group"`.

- [ ] **Step 1: Write the failing entity discovery and control test**

```python
async def test_setup_creates_controllable_group_entity(hass, config_entry, snapserver_factory):
    await setup_entry(hass, config_entry)
    group = hass.states.get("media_player.living_room_snapcast_group")
    assert group is not None
    assert group.state == "playing"
    await hass.services.async_call(
        "media_player", "volume_set",
        {"entity_id": group.entity_id, "volume_level": 0.37}, blocking=True,
    )
    fake_server.group("group-a").set_volume.assert_awaited_once_with(37)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_integration.py::test_setup_creates_controllable_group_entity -v`

Expected: FAIL because no group entity exists.

- [ ] **Step 3: Implement group discovery and `SnapcastGroupDevice`**

```python
class SnapcastGroupDevice(SnapcastCoordinatorEntity, MediaPlayerEntity):
    _attr_supported_features = (
        MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    def _get_group(self) -> Snapgroup | None:
        physical_id = self.coordinator.group_registry.physical_id(self._logical_id)
        if physical_id is None or self.coordinator.server is None:
            return None
        return self.coordinator.server.group(physical_id)
```

Drive both client and group entity discovery from a single coordinator listener. Do not remove unrepresented group entities from the registry; add unresolved logical IDs as unavailable entities. Implement state, name, volume, mute, source, snapshot, restore, and clear errors for latency/grouping-only client methods.

- [ ] **Step 4: Run the focused entity test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_integration.py::test_setup_creates_controllable_group_entity -v`

Expected: PASS.

- [ ] **Step 5: Write and run a failing rebind-after-ID-change regression test**

```python
async def test_group_entity_keeps_entity_id_when_snapcast_changes_group_id(...):
    old_entity_id = "media_player.living_room_snapcast_group"
    replace_server_group("group-a", "group-b", client_ids=["aa:bb:cc"])
    fake_server.on_update()
    await hass.async_block_till_done()
    assert hass.states.get(old_entity_id) is not None
    await call_group_volume_service(old_entity_id)
    fake_server.group("group-b").set_volume.assert_awaited_once()
```

Run: `.venv/bin/python -m pytest tests/test_integration.py::test_group_entity_keeps_entity_id_when_snapcast_changes_group_id -v`

Expected: FAIL before the registry result is consumed by group entities; PASS after the minimal fix.

- [ ] **Step 6: Commit**

```bash
git add const.py media_player.py tests/conftest.py tests/test_integration.py
git commit -m "feat: expose resilient snapcast group players"
```

### Task 3: Reconciliar entidades antiguas manualmente

**Files:**
- Modify: `services.py`
- Modify: `services.yaml`
- Modify: `tests/test_integration.py`
- Modify: `translations/en.json`

**Interfaces:**
- Produces `snapcast.reconcile_group(old_entity_id, new_entity_id)`.
- Consumes two registered `SnapcastGroupDevice` entities belonging to the same `SnapcastConfigEntry`.
- Calls `group_registry.async_reassign(old_logical_id, new_physical_id)` and reloads exactly that entry.

- [ ] **Step 1: Write the failing service test**

```python
async def test_reconcile_group_keeps_the_old_entity_id(hass, ...):
    await setup_entry(hass, config_entry)
    await hass.services.async_call(
        DOMAIN, "reconcile_group",
        {"old_entity_id": stale_group_id, "new_entity_id": new_group_id},
        blocking=True,
    )
    assert hass.states.get(stale_group_id) is not None
    assert hass.states.get(new_group_id) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_integration.py::test_reconcile_group_keeps_the_old_entity_id -v`

Expected: FAIL because the service is not registered.

- [ ] **Step 3: Implement service validation and controlled reload**

```python
async def async_reconcile_group(call: ServiceCall) -> None:
    old_entity, new_entity = validate_group_entities(call.data)
    await old_entry.runtime_data.group_registry.async_reassign(
        old_logical_id, new_physical_id
    )
    entity_registry.async_remove(new_entity_id)
    await hass.config_entries.async_reload(old_entry.entry_id)
```

Reject missing entities, client entities, different Snapcast servers, and a target group already bound to another logical ID with `ServiceValidationError`. Document both service fields and their semantics in `services.yaml`.

- [ ] **Step 4: Run the service test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_integration.py::test_reconcile_group_keeps_the_old_entity_id -v`

Expected: PASS.

- [ ] **Step 5: Add validation tests and run the full suite**

```python
async def test_reconcile_group_rejects_client_or_cross_server_entities(...):
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(..., blocking=True)
```

Run: `.venv/bin/python -m pytest tests/ -v`

Expected: PASS with no failures.

- [ ] **Step 6: Commit**

```bash
git add services.py services.yaml translations/en.json tests/test_integration.py
git commit -m "feat: reconcile legacy snapcast group entities"
```

### Task 4: Verificación y documentación de usuario

**Files:**
- Modify: `README.md`
- Modify: `manifest.json`
- Test: `tests/`

**Interfaces:**
- Documents automatic group ID rebinds and `snapcast.reconcile_group` recovery.

- [ ] **Step 1: Add README documentation**

Document that group entities are dynamic Snapcast groups with stable Home Assistant identities, how automatic matching works, why ambiguous mappings require the manual service, and an exact service-call example using `old_entity_id` and `new_entity_id`.

- [ ] **Step 2: Bump integration version**

Set `manifest.json` version to the next patch release after `1.2.0`.

- [ ] **Step 3: Run the complete test suite**

Run: `.venv/bin/python -m pytest tests/ -v`

Expected: PASS with every test green.

- [ ] **Step 4: Inspect the final diff and status**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; only intended files are modified.

- [ ] **Step 5: Commit**

```bash
git add README.md manifest.json
git commit -m "docs: document snapcast group reconciliation"
```
