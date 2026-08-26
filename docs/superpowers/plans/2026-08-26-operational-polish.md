# Operational Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve Snapcast Plus service discoverability, supportability, configuration, persistence hygiene, and automated quality checks without changing existing public IDs or payloads.

**Architecture:** Keep coordinator state as the source of truth. Add diagnostics as a read-only config-entry module, reconfiguration as a second ConfigFlow step, and historical cleanup as an explicit coordinator/service operation. Keep UI metadata in the existing service/translation files and verify behavior through the Home Assistant test harness.

**Tech Stack:** Python 3.13, Home Assistant custom integration APIs, pytest, pytest-homeassistant-custom-component, pytest-cov, Ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-26-operational-polish-design.md`

## Global Constraints

- Preserve domain `snapcast`, existing client/group/zone unique IDs, and existing service names/payloads.
- Keep `reconnect=False` and the fresh-server reconnection model.
- Never expose hostnames, IP addresses, client IDs, stream metadata, or user names in diagnostics.
- Historical group cleanup is explicit; active bindings remain untouched.
- Keep Home Assistant minimum version `2024.2.0` and Snapcast dependency `2.3.8`.

### Task 1: Document all services and add cleanup service contract

**Files:**
- Modify: `services.py`
- Modify: `services.yaml`
- Modify: `strings.json`
- Modify: `translations/en.json`
- Test: `tests/test_integration.py`

**Interfaces:**
- Produce `snapcast.cleanup_groups` service with no fields.
- Preserve existing service handlers and payloads.

- [ ] **Step 1: Write failing tests** for the cleanup service registration and for the presence of all seven existing service names plus `cleanup_groups` in the loaded service registry.
- [ ] **Step 2: Run the focused tests** with `.venv/bin/python -m pytest tests/test_integration.py -k "service or cleanup" -q`; verify failure because the new service is not registered.
- [ ] **Step 3: Implement the coordinator-independent service registration** and add complete field metadata for `reconcile_group`, `create_zone`, `update_zone`, `remove_zone`, and `cleanup_groups`.
- [ ] **Step 4: Run the focused tests** and verify they pass.
- [ ] **Step 5: Commit** with `feat: document snapcast services`.

### Task 2: Add reconfiguration flow

**Files:**
- Modify: `config_flow.py`
- Modify: `strings.json`
- Modify: `translations/en.json`
- Test: `tests/test_config_flow.py`

**Interfaces:**
- Produce `SnapcastConfigFlow.async_step_reconfigure(user_input: dict | None) -> ConfigFlowResult`.
- Reuse `SNAPCAST_SCHEMA` and existing `invalid_host`/`cannot_connect` errors.

- [ ] **Step 1: Write failing tests** for successful reconfiguration and socket failure preserving the form/error.
- [ ] **Step 2: Run `.venv/bin/python -m pytest tests/test_config_flow.py -k reconfigure -q`** and verify the step is missing.
- [ ] **Step 3: Implement a connection probe helper and `async_step_reconfigure`; stop the probe and call `async_update_reload_and_abort` with `data_updates`.
- [ ] **Step 4: Run the focused tests** and verify both paths pass.
- [ ] **Step 5: Commit** with `feat: add snapcast reconfigure flow`.

### Task 3: Add diagnostics

**Files:**
- Create: `diagnostics.py`
- Modify: `manifest.json`
- Test: `tests/test_integration.py`

**Interfaces:**
- Produce `async_get_config_entry_diagnostics(hass, entry) -> dict`.
- Return only redacted connection/reconnect/entity/persistence counts.

- [ ] **Step 1: Write a failing diagnostics test** asserting redaction and expected count/status keys.
- [ ] **Step 2: Run the focused test** and verify import/handler failure.
- [ ] **Step 3: Implement the read-only diagnostics handler and add the manifest diagnostics flag if required by the installed Home Assistant version.
- [ ] **Step 4: Run the focused test** and verify no host or IDs are present.
- [ ] **Step 5: Commit** with `feat: add snapcast diagnostics`.

### Task 4: Implement explicit historical group cleanup

**Files:**
- Modify: `coordinator.py`
- Modify: `services.py`
- Modify: `services.yaml`
- Modify: `strings.json`
- Modify: `translations/en.json`
- Test: `tests/test_integration.py`

**Interfaces:**
- Produce `SnapcastUpdateCoordinator.async_cleanup_groups() -> list[str]` returning removed logical group IDs.
- Produce `snapcast.cleanup_groups` that removes matching group registry entries and reloads the config entry.

- [ ] **Step 1: Write a failing test** that creates an unavailable historical group, calls cleanup, and asserts its registry entry/storage binding is removed while the active group remains.
- [ ] **Step 2: Run the focused test** and verify the coordinator method/service is absent.
- [ ] **Step 3: Implement cleanup of only `None` physical bindings, membership snapshots, registry entries, and entry reload.
- [ ] **Step 4: Run the focused test** and verify active bindings remain unchanged.
- [ ] **Step 5: Commit** with `feat: prune historical snapcast groups`.

### Task 5: Improve CI and documentation

**Files:**
- Modify: `requirements_test.txt`
- Modify: `pyproject.toml`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Test: `tests/test_integration.py` and `tests/test_config_flow.py` (coverage additions from prior tasks)

**Interfaces:**
- CI runs pytest with coverage threshold 85% and Ruff.
- README accurately describes temporary unavailability during reconnect and lists cleanup/diagnostics/reconfigure behavior.

- [ ] **Step 1: Add configuration/tests for the checks** and run the commands locally to capture current failures or lint findings.
- [ ] **Step 2: Fix only integration-owned lint findings and add explicit Ruff exclusions for generated/test harness paths.
- [ ] **Step 3: Add CI commands and pin the HACS action to a stable major version.
- [ ] **Step 4: Correct README wording and development commands.
- [ ] **Step 5: Run full pytest, coverage, Ruff, and JSON parsing checks.
- [ ] **Step 6: Commit** with `ci: add lint and coverage gates`.

### Task 6: Final verification

**Files:**
- Inspect: `git diff`, all changed files

- [ ] **Step 1: Run `.venv/bin/python -m pytest tests -q --cov=. --cov-report=term-missing --cov-fail-under=85`.
- [ ] **Step 2: Run `.venv/bin/ruff check .`.
- [ ] **Step 3: Run `.venv/bin/python -m json.tool services.yaml` only for JSON files and validate YAML with the available parser.
- [ ] **Step 4: Run `git diff --check` and inspect `git status --short`.
- [ ] **Step 5: Report exact verification output and any remaining limitations.
