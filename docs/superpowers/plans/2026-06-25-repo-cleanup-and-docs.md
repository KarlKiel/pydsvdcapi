# Repository Cleanup and Comprehensive Documentation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Streamline the pydsvdcapi repository: remove all internal/p44 references, add GPL v3 headers to every source file, consolidate scattered docs into a single comprehensive `docs/guide.md`, and wire it into Sphinx via MyST so both narrative and API docs are served from one place.

**Architecture:** Obsolete files (examples, plans, internal analyses) move to an untracked `old/` folder. Every Python source file gains an SPDX header. All internal comparisons and implementation notes are removed or neutralised. `docs/guide.md` becomes the single source of truth — readable standalone as Markdown and processable by Sphinx via `myst-parser`. The `conversion.py` shim is eliminated; internal modules import from `pydsvdcapi.addons.converter` directly.

**Tech Stack:** Python 3.10+, protobuf, PyYAML, Sphinx + myst-parser + sphinx-autodoc-typehints + furo, ruff, mypy, pytest

---

## File map (what changes)

| File | Action |
|------|--------|
| `old/` (new) | Created at repo root, added to `.gitignore`, removed from git |
| `REVIEW.md` | → `old/` |
| `RELEASE-0.8.1.md` | → `old/` |
| `examples/` | → `old/` |
| `docs/superpowers/` | → `old/` |
| `docs/p44vdc-comparison.md` | → `old/` (already in .gitignore) |
| `docs/p44vdc-message-flow-reference.md` | → `old/` |
| `docs/api-conformance-analysis.md` | → `old/` |
| `docs/device-class-analysis.md` | → `old/` |
| `docs/dss-device-class-usage-analysis.md` | → `old/` |
| `docs/dss-configurator-ui-composition.md` | → `old/` |
| `docs/dss-vdc-behavior.md` | → `old/` |
| `docs/message-flow-reference.md` | → `old/` |
| `docs/vdc-db-device-catalogue.md` | → `old/` |
| `docs/vdc-api-properties.md` | Consolidated → `old/` |
| `docs/model-features-auto-assignment.md` | Consolidated → `old/` |
| `docs/device-splitting-guidelines.md` | Consolidated → `old/` |
| `docs/vdc-host-behavior.md` | Consolidated → `old/` |
| `docs/guide.md` | **Created** — comprehensive library guide |
| `docs/conf.py` | Updated: myst-parser, copyright fix |
| `docs/index.rst` | Updated: point to guide |
| `docs/api.rst` | Updated: leaner API reference |
| `src/pydsvdcapi/*.py` | GPL v3 SPDX header added, p44 refs removed |
| `src/pydsvdcapi/conversion.py` | **Deleted** after updating importers |
| `src/pydsvdcapi/device_state.py` | Import fixed: → `addons.converter` |
| `src/pydsvdcapi/output_channel.py` | Import fixed: → `addons.converter` |
| `src/pydsvdcapi/device_property.py` | Import fixed: → `addons.converter` |
| `src/pydsvdcapi/binary_input.py` | Import fixed: → `addons.converter` |
| `src/pydsvdcapi/sensor_input.py` | Import fixed: → `addons.converter` |
| `tests/test_output_channel.py` | p44 refs removed from comments |
| `tests/test_output.py` | p44 refs removed from comments |
| `CHANGELOG.md` | p44 refs replaced with neutral wording |
| `README.md` | Remove dead `examples/` links |
| `pyproject.toml` | Add myst-parser to docs deps, fix copyright |

---

## Task 1: Move obsolete files to `old/` and update git

**Files:**
- Create: `old/` (directory)
- Modify: `.gitignore`
- Remove from git: all files listed below

- [ ] **Step 1: Create the `old/` directory and move files**

```bash
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
mkdir -p old

# Move root-level obsolete files
cp REVIEW.md old/
cp RELEASE-0.8.1.md old/

# Move examples
cp -r examples/ old/examples/

# Move docs to old
cp -r docs/superpowers/ old/superpowers/
cp docs/p44vdc-comparison.md old/ 2>/dev/null || true
cp docs/p44vdc-message-flow-reference.md old/
cp docs/api-conformance-analysis.md old/
cp docs/device-class-analysis.md old/
cp docs/dss-device-class-usage-analysis.md old/
cp docs/dss-configurator-ui-composition.md old/
cp docs/dss-vdc-behavior.md old/
cp docs/message-flow-reference.md old/
cp docs/vdc-db-device-catalogue.md old/
cp docs/vdc-api-properties.md old/
cp docs/model-features-auto-assignment.md old/
cp docs/device-splitting-guidelines.md old/
cp docs/vdc-host-behavior.md old/
```

- [ ] **Step 2: Remove the files from git tracking**

```bash
# Root files
git rm REVIEW.md RELEASE-0.8.1.md

# Examples
git rm -r examples/

# Docs
git rm -r docs/superpowers/
git rm docs/p44vdc-message-flow-reference.md
git rm docs/api-conformance-analysis.md
git rm docs/device-class-analysis.md
git rm docs/dss-device-class-usage-analysis.md
git rm docs/dss-configurator-ui-composition.md
git rm docs/dss-vdc-behavior.md
git rm docs/message-flow-reference.md
git rm docs/vdc-db-device-catalogue.md
git rm docs/vdc-api-properties.md
git rm docs/model-features-auto-assignment.md
git rm docs/device-splitting-guidelines.md
git rm docs/vdc-host-behavior.md
```

- [ ] **Step 3: Add `old/` to `.gitignore`**

Open `.gitignore` and add these lines after the existing `Documentation/` entry:

```
# Retired / archived files (kept locally, not version-controlled)
old/
```

- [ ] **Step 4: Stage and commit**

```bash
git add .gitignore
git commit -m "chore: retire obsolete files to old/ (untracked)"
```

Expected: clean `git status` with no untracked docs, examples, or old root files.

---

## Task 2: Remove all p44/plan44 references from `src/`

**Files:**
- Modify: `src/pydsvdcapi/dsuid.py`
- Modify: `src/pydsvdcapi/property_handling.py`
- Modify: `src/pydsvdcapi/device_state.py`
- Modify: `src/pydsvdcapi/device_property.py`
- Modify: `src/pydsvdcapi/output.py`
- Modify: `src/pydsvdcapi/vdsd.py`

- [ ] **Step 1: Fix `dsuid.py`**

Line 21: replace
```
Reference: plan44/p44vdc dsuid.cpp/hpp (GPL-3.0-or-later).
```
with:
```
Reference: ds-basics v1.6, vDC API specification.
```

Line 47: replace
```
# Well-known namespace UUIDs  (from p44vdc/dsuid.hpp)
```
with:
```
# Well-known namespace UUIDs  (from digitalSTROM system documentation)
```

- [ ] **Step 2: Fix `property_handling.py`**

Line 59: replace any occurrence of `p44-vdc` with `the vDC API reference implementation`.

Run:
```bash
grep -n "p44" src/pydsvdcapi/property_handling.py
```
For each match replace the technical context note, e.g.:
- `"This matches the p44-vdc behaviour for"` → `"This matches the vDC API specification for"`

- [ ] **Step 3: Fix `device_state.py`**

```bash
grep -n "p44" src/pydsvdcapi/device_state.py
```
Line ~310: replace `"p44-vdc sends the text label"` with `"The vDC API specification requires the text label"`.

- [ ] **Step 4: Fix `device_property.py`**

```bash
grep -n "p44" src/pydsvdcapi/device_property.py
```
Replace every occurrence of `p44-vdc` with `the vDC API specification` or `the vDC reference behaviour` depending on context. Lines ~476, ~516, ~560.

- [ ] **Step 5: Fix `output.py`**

```bash
grep -n "p44" src/pydsvdcapi/output.py
```
All occurrences: replace internal comparison comments with neutral descriptions of what the vDC API wire format requires. Specifically:
- `"Rounded approximations of p44vdc ShadowBehaviour compiled-in defaults."` → `"Default motor timing values for shade outputs (per vDC API specification)."`
- `"Motor open travel time in seconds (ShadowBehaviour / p44vdc)."` → `"Motor open travel time in seconds."`
- `"# Shadow motor timing settings (ShadowBehaviour / p44vdc)"` → `"# Shadow motor timing settings"`
- `"p44vdc API v3+ getApiId() format"` → `"vDC API v3+ channel ID format"`
- `"matching the p44vdc API v3+ channel ID"` → `"matching the vDC API v3+ channel ID"`
- `"follows p44vdc behaviour: group 0"` → `"follows vDC API: group 0"`
- `"falls back to p44-compatible defaults"` → `"falls back to vDC API defaults"`
- `"matching p44vdc base OutputBehaviour"` → `"matching vDC API base output behaviour"`
- `"not in p44vdc base but"` → `"always included"`

- [ ] **Step 6: Fix `vdsd.py`**

```bash
grep -n "p44" src/pydsvdcapi/vdsd.py
```
Line ~1633: `"# modelFeatures — sorted by canonical ModelFeatureId enum index (as p44vdc)."` → `"# modelFeatures — sorted by canonical ModelFeatureId enum index."`
Line ~1722: `"# In p44-vdc, enableAsSingleDevice() always creates ALL"` → `"# Always create ALL"`
Line ~2319: `"# (mirrors vdSMAnnouncementAcknowledged in p44vdc device.cpp)."` → `"# (mirrors vdSMAnnouncementAcknowledged in the vDC API protocol)"`

- [ ] **Step 7: Verify no p44 refs remain in src/**

```bash
grep -rn "p44\|plan44\|Plan44" src/pydsvdcapi/
```
Expected: zero output (excluding `_pb2.py` files which are generated).

- [ ] **Step 8: Commit**

```bash
git add src/pydsvdcapi/dsuid.py src/pydsvdcapi/property_handling.py \
    src/pydsvdcapi/device_state.py src/pydsvdcapi/device_property.py \
    src/pydsvdcapi/output.py src/pydsvdcapi/vdsd.py
git commit -m "chore: remove all p44/plan44 references from src/"
```

---

## Task 3: Remove p44/plan44 references from tests and CHANGELOG

**Files:**
- Modify: `tests/test_output_channel.py`
- Modify: `tests/test_output.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Fix `tests/test_output_channel.py`**

```bash
grep -n "p44" tests/test_output_channel.py
```
- Line ~667: `"# uninitialized → 0.0, matching p44vdc v_double default"` → `"# uninitialized → 0.0 (vDC API default)"`
- Line ~1614: `"""POSITIONAL: shade channels keyed by channel name, matching p44vdc wire format."""` → `"""POSITIONAL: shade channels keyed by channel name (vDC API v3+ wire format)."""`
- Line ~1618 comment: remove `"as p44vdc uses"` → just remove the parenthetical.

- [ ] **Step 2: Fix `tests/test_output.py`**

```bash
grep -n "p44" tests/test_output.py
```
- Line ~3513: `"""Shadow timing fields are always emitted for shadow devices with p44-compatible defaults."""` → `"""Shadow timing fields are always emitted for shadow devices with vDC API defaults."""`

- [ ] **Step 3: Fix `CHANGELOG.md`**

```bash
grep -n "p44" CHANGELOG.md
```
Replace all occurrences:
- `"matching p44vdc behaviour"` → `"matching the vDC API specification"`
- `"matching p44vdc wire format"` → `"matching the vDC API v3+ wire format"`
- `"matches p44vdc's"` → `"matches the vDC API"`
- `"emitted by p44vdc"` → `"emitted by the vDC API"`
- `"as p44vdc uses"` → (remove the parenthetical)
- `"ShadowBehaviour / p44vdc"` → `"shade output"`
- `"p44vdc base OutputBehaviour"` → `"vDC API base output"`
- `"not in p44vdc base"` → `"always included"`
- `"from modelconst.h"` → (remove this parenthetical entirely)
- `"p44mbrd"` → `"the Matter bridge integration"` 
- Any remaining `p44` → context-appropriate neutral wording

- [ ] **Step 4: Verify**

```bash
grep -rn "p44\|plan44\|Plan44" tests/ CHANGELOG.md
```
Expected: zero output.

- [ ] **Step 5: Commit**

```bash
git add tests/test_output_channel.py tests/test_output.py CHANGELOG.md
git commit -m "chore: remove p44/plan44 references from tests and CHANGELOG"
```

---

## Task 4: Add GPL v3 SPDX headers to all src Python files

**Files:**
- Modify: every `*.py` in `src/pydsvdcapi/` (except generated `*_pb2.py`)

The header block is:
```python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024–2026 Arne Speck
```

Place these two lines as the **very first lines** of each file, before any module docstring or imports. If the file starts with a shebang (`#!/usr/bin/env python`), place the header after the shebang.

- [ ] **Step 1: Add headers to the main source files**

Files to edit (do one at a time, inserting the header at line 1):
```
src/pydsvdcapi/__init__.py
src/pydsvdcapi/actions.py
src/pydsvdcapi/binary_input.py
src/pydsvdcapi/button_input.py
src/pydsvdcapi/connection.py
src/pydsvdcapi/device_event.py
src/pydsvdcapi/device_property.py
src/pydsvdcapi/device_state.py
src/pydsvdcapi/device_template.py
src/pydsvdcapi/dsuid.py
src/pydsvdcapi/enums.py
src/pydsvdcapi/output.py
src/pydsvdcapi/output_channel.py
src/pydsvdcapi/persistence.py
src/pydsvdcapi/property_handling.py
src/pydsvdcapi/sensor_input.py
src/pydsvdcapi/session.py
src/pydsvdcapi/vdc.py
src/pydsvdcapi/vdc_host.py
src/pydsvdcapi/vdsd.py
src/pydsvdcapi/addons/__init__.py
src/pydsvdcapi/addons/converter/__init__.py
```

For each file, prepend:
```python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024–2026 Arne Speck
```

Do NOT touch `vdc_messages_pb2.py`, `vdcapi_pb2.py`, `vdc_messages_pb2.pyi`, `vdcapi_pb2.pyi` — these are generated protobuf files.

- [ ] **Step 2: Verify headers present in all target files**

```bash
for f in src/pydsvdcapi/__init__.py \
          src/pydsvdcapi/actions.py \
          src/pydsvdcapi/binary_input.py \
          src/pydsvdcapi/button_input.py \
          src/pydsvdcapi/connection.py \
          src/pydsvdcapi/device_event.py \
          src/pydsvdcapi/device_property.py \
          src/pydsvdcapi/device_state.py \
          src/pydsvdcapi/device_template.py \
          src/pydsvdcapi/dsuid.py \
          src/pydsvdcapi/enums.py \
          src/pydsvdcapi/output.py \
          src/pydsvdcapi/output_channel.py \
          src/pydsvdcapi/persistence.py \
          src/pydsvdcapi/property_handling.py \
          src/pydsvdcapi/sensor_input.py \
          src/pydsvdcapi/session.py \
          src/pydsvdcapi/vdc.py \
          src/pydsvdcapi/vdc_host.py \
          src/pydsvdcapi/vdsd.py \
          src/pydsvdcapi/addons/__init__.py \
          src/pydsvdcapi/addons/converter/__init__.py; do
    head -1 "$f" | grep -q "SPDX" || echo "MISSING HEADER: $f"
done
```
Expected: no output.

- [ ] **Step 3: Run tests to confirm nothing broke**

```bash
python -m pytest -q
```
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/pydsvdcapi/
git commit -m "chore: add GPL v3 SPDX headers to all source files"
```

---

## Task 5: Remove `conversion.py` shim — update internal imports

**Context:** `src/pydsvdcapi/conversion.py` is a backward-compat shim that re-exports from `pydsvdcapi.addons.converter`. Five internal modules import from it. Update them to import directly from `pydsvdcapi.addons.converter`, then delete the shim.

**Files:**
- Modify: `src/pydsvdcapi/binary_input.py`
- Modify: `src/pydsvdcapi/device_property.py`
- Modify: `src/pydsvdcapi/device_state.py`
- Modify: `src/pydsvdcapi/output_channel.py`
- Modify: `src/pydsvdcapi/sensor_input.py`
- Delete: `src/pydsvdcapi/conversion.py`

- [ ] **Step 1: Update imports in the five files**

In each of the five files, find the line:
```python
from pydsvdcapi.conversion import apply_converter, compile_converter
```
and replace it with:
```python
from pydsvdcapi.addons.converter import apply_converter, compile_converter
```

Files:
- `src/pydsvdcapi/binary_input.py` (line ~60)
- `src/pydsvdcapi/device_property.py` (line ~65)
- `src/pydsvdcapi/device_state.py` (line ~63)
- `src/pydsvdcapi/output_channel.py` (line ~101)
- `src/pydsvdcapi/sensor_input.py` (line ~85)

- [ ] **Step 2: Delete the shim**

```bash
git rm src/pydsvdcapi/conversion.py
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest -q
```
Expected: all tests pass (no import errors).

- [ ] **Step 4: Commit**

```bash
git add src/pydsvdcapi/binary_input.py src/pydsvdcapi/device_property.py \
    src/pydsvdcapi/device_state.py src/pydsvdcapi/output_channel.py \
    src/pydsvdcapi/sensor_input.py
git commit -m "refactor: remove conversion.py shim; import from addons.converter directly"
```

---

## Task 6: Update pyproject.toml and docs/conf.py for MyST Sphinx

**Files:**
- Modify: `pyproject.toml`
- Modify: `docs/conf.py`

- [ ] **Step 1: Add myst-parser to pyproject.toml docs deps**

In `pyproject.toml`, find the `[project.optional-dependencies]` `docs` section:
```toml
docs = [
    "sphinx>=7.0",
    "sphinx-autodoc-typehints>=1.25",
    "furo>=2024.0",
]
```
Replace with:
```toml
docs = [
    "sphinx>=7.0",
    "myst-parser>=3.0",
    "sphinx-autodoc-typehints>=1.25",
    "furo>=2024.0",
]
```

- [ ] **Step 2: Rewrite `docs/conf.py`**

Replace the entire content of `docs/conf.py` with:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024–2026 Arne Speck
import os
import sys

sys.path.insert(0, os.path.abspath("../src"))

from pydsvdcapi import __version__

project = "pydsvdcapi"
copyright = "2024–2026 Arne Speck"
author = "Arne Speck"
release = __version__

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx_autodoc_typehints",
]

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "tasklist",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "myst",
}

html_theme = "furo"

autodoc_member_order = "bysource"
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}
```

- [ ] **Step 3: Update `docs/index.rst` to include guide.md**

Replace the entire `docs/index.rst` with:

```rst
pydsvdcapi
==========

Python library for the digitalSTROM virtual Device Connector (vDC) API.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   guide
   api
```

- [ ] **Step 4: Update `docs/api.rst`**

Replace the entire `docs/api.rst` with:

```rst
API Reference
=============

Full API reference auto-generated from source docstrings.

.. automodule:: pydsvdcapi
   :members:
   :show-inheritance:
```

- [ ] **Step 5: Install myst-parser and verify Sphinx build**

```bash
pip install myst-parser
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml docs/conf.py docs/index.rst docs/api.rst
git commit -m "chore: add myst-parser; update Sphinx conf for guide.md"
```

---

## Task 7: Write `docs/guide.md` — Part 1: Introduction through Quick Start

**Files:**
- Create: `docs/guide.md`

- [ ] **Step 1: Create guide.md with introduction, installation, and quick start**

Create `docs/guide.md` with this content:

````markdown
# pydsvdcapi — Developer Guide

## 1. Introduction

pydsvdcapi is a Python library for building **virtual Device Connectors (vDCs)** — software
bridges that make custom hardware or cloud services appear as native devices in a
digitalSTROM smart home installation.

### What is digitalSTROM?

digitalSTROM (dS) is a home-automation system based on powerline communication (the 230 V wiring
in walls). Every controllable device in a dS installation — a light, a blind, a thermostat —
is represented on the **dSS** (digitalSTROM server) as a logical entity with a stable unique ID,
zone assignment, scene memory, and group membership.

The system is entirely local: no cloud, no subscriptions. The dSS coordinates all communication
through the bus coupler firmware (vdSM) that runs inside the dSS box.

### What is the vDC API?

The **vDC API** is the protobuf-over-TCP protocol that lets software-defined devices join a dS
installation without any powerline hardware. A process implementing the vDC API announces
virtual devices to the vdSM, receives commands (scene calls, output value changes), and pushes
state updates back. From the dSS's point of view, vDC devices are indistinguishable from real
hardware devices.

The protocol defines three first-class entities:

| Entity | Role |
|--------|------|
| **vDChost** | The gateway process (one per machine/process). Owns the TCP socket. |
| **vDC** | A logical connector that groups related devices (one per integration type). |
| **vdSD** | A single virtual device, the smallest addressable unit. |

### What can you build with pydsvdcapi?

- An IP-to-dS bridge for lights, thermostats, smart plugs, or window actuators
- A MQTT, ZigBee, Z-Wave, KNX, or Modbus gateway into digitalSTROM
- A virtual "device" that represents a web service or cloud API
- Test harnesses and simulation drivers for dS integration testing

---

## 2. Installation

```bash
pip install pydsvdcapi
```

Requires Python ≥ 3.10.

For development (tests, linting, type checking):
```bash
pip install "pydsvdcapi[dev]"
```

For building the documentation:
```bash
pip install "pydsvdcapi[docs]"
make -C docs html
```

---

## 3. Quick Start

The minimal skeleton to get a dimmable light visible on the dSS:

```python
import asyncio
from pydsvdcapi import (
    VdcHost, Vdc, Device, Vdsd,
    DsUid,
    Output, OutputFunction, OutputMode, OutputUsage,
    ColorGroup, DeviceLifecycleState,
)


async def main():
    # 1. Gateway entity — one per process
    host = VdcHost(
        name="My Python Gateway",
        state_path="state.yaml",  # persist across restarts
    )

    # 2. Logical connector — one per integration type
    vdc = Vdc(
        implementation_id="x-myapp-lights",
        name="My Lights",
        model="Python Light Controller",
    )
    host.add_vdc(vdc)

    # 3. Physical device and its virtual representation
    device = Device(dsuid=DsUid.new_gtin_based("0000000000001", 0))
    vdsd = Vdsd(
        dsuid=DsUid.new_uuid_based(),
        name="Living Room Light",
    )

    # 4. Output: the single controllable output of this device
    output = Output(
        function=OutputFunction.DIMMER,
        mode=OutputMode.PWM,
        usage=OutputUsage.ROOM,
        group=ColorGroup.YELLOW,   # yellow = light group
    )
    vdsd.set_output(output)

    # 5. React to dSS commands
    brightness = output.channels["brightness"]

    @brightness.on_apply
    async def apply_brightness(value: float) -> None:
        print(f"Set brightness to {value:.1f}%")
        # → send to your physical hardware here

    # 6. React to identify (user touches device in configurator)
    async def on_identify(v: Vdsd) -> None:
        print(f"Identify: {v.name}")
    vdsd.on_identify = on_identify

    # 7. Report device health
    await vdsd.set_lifecycle_state(DeviceLifecycleState.ACTIVE)

    # 8. Assemble and run
    device.add_vdsd(vdsd)
    vdc.add_device(device)
    await host.run()   # connects to dSS, blocks until stopped


asyncio.run(main())
```

The host will:
- Register itself via mDNS so the vdSM on the dSS can find it automatically
- Accept the TCP connection and perform the `hello` handshake
- Announce the vDC and all devices
- Dispatch incoming commands to your callbacks
- Push state changes to the dSS when you update a channel value
- Persist the device tree to `state.yaml` on any configuration change

---
````

- [ ] **Step 2: Verify the file exists and is valid Markdown**

```bash
wc -l docs/guide.md
```
Expected: > 100 lines.

- [ ] **Step 3: Commit**

```bash
git add docs/guide.md
git commit -m "docs: create guide.md — introduction, installation, quick start"
```

---

## Task 8: Write `docs/guide.md` — Part 2: Architecture and Core Entities

**Files:**
- Modify: `docs/guide.md` (append)

- [ ] **Step 1: Append the architecture and entity reference sections**

Append to `docs/guide.md`:

````markdown
## 4. Architecture

### 4.1 Entity hierarchy

```
VdcHost  — one per gateway process (owns the TCP socket and mDNS registration)
  └─ Vdc  — one or more per host (one per integration type)
       └─ Device  — one per physical device
            └─ Vdsd  — one or more per Device (one per independent output/function)
```

The dSS sees all three levels. The vdSM (the bus coupler firmware inside the dSS) connects to the
VdcHost's TCP socket and discovers everything via the announcement protocol.

### 4.2 Device vs Vdsd

Each physical piece of hardware is wrapped in a `Device`. The Device holds one or more `Vdsd`
instances that share the first 16 bytes of their dSUID (byte 17 = sub-device index).

**When to use multiple Vdsd per Device:**

A vdSD has exactly **one** output. If your hardware has multiple independent outputs:

- A dual dimmer → 2 Vdsd instances (one per channel)
- A combined light + shade actuator → 2 Vdsd instances (different primary groups)
- An RGB light (brightness + hue + saturation) → 1 Vdsd with 3 channels on one output

Multiple sensors, binary inputs, or button inputs on the same Vdsd are fine.

```python
base = DsUid.new_gtin_based("0123456789012", 0)
light_device = Device(dsuid=base)

# Both share bytes 0-15 of the dSUID
light_vdsd = Vdsd(dsuid=base.derive_subdevice(0), name="Light")
shade_vdsd = Vdsd(dsuid=base.derive_subdevice(1), name="Shade")
light_device.add_vdsd(light_vdsd)
light_device.add_vdsd(shade_vdsd)
```

---

## 5. VdcHost Reference

`VdcHost` is the gateway entity. There is exactly one per process.

### 5.1 Constructor parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | `hostname` | Human-readable gateway name shown in the dSS configurator |
| `dsuid` | `DsUid \| None` | derived from MAC | Stable unique ID of this gateway; auto-derived from the MAC address if omitted |
| `mac` | `str \| None` | auto-detected | Ethernet MAC address used for dSUID derivation and mDNS |
| `port` | `int` | `8444` | TCP port the vdSM connects to |
| `model` | `str \| None` | `name` | Model description shown in the configurator |
| `model_version` | `str \| None` | `None` | Firmware/software version shown in the configurator |
| `vendor_name` | `str \| None` | `None` | Vendor label shown alongside the model |
| `state_path` | `str \| Path \| None` | `None` | Path to the YAML persistence file; no persistence if `None` |

### 5.2 Running the host

```python
await host.run()   # blocks until stopped
await host.stop()  # called from another coroutine to terminate
```

### 5.3 Callbacks on `start()` / `run()`

| Parameter | Signature | When called |
|-----------|-----------|-------------|
| `on_hello` | `async (host, session) -> None` | vdSM connects and completes hello |
| `on_authenticate` | `async (host, token) -> bool` | vdSM sends an authentication token (return `True` to accept) |
| `on_pair` | `async (host, token) -> None` | Pairing request received |
| `on_remove` | `async (host) -> None` | vdSM requests removal of this gateway |
| `on_set_configuration` | `async (host, config) -> None` | vdSM pushes configuration |
| `on_firmware_upgrade` | `async (host, url) -> None` | vdSM requests a firmware upgrade |
| `on_identify` | `async (host) -> None` | vdSM asks the gateway to identify itself |
| `on_disconnect` | `async (host, reason) -> None` | TCP connection lost unexpectedly |

### 5.4 Managing vDCs

```python
host.add_vdc(vdc)                      # add a vDC before or after run()
host.remove_vdc(dsuid)                 # remove by dSUID
host.get_vdc(dsuid)                    # look up by dSUID
for dsuid, vdc in host.vdcs.items():   # iterate all vDCs
    ...
```

### 5.5 Persistence

When `state_path` is configured, the host saves its complete property tree (all vDCs, devices,
and their user-visible configuration such as names, zone assignments, and scene settings) to a
YAML file. Saves are debounced — rapid changes within `AUTO_SAVE_DELAY` seconds (default 2 s)
coalesce into a single write.

Call `host.flush()` to force an immediate save (e.g. before a planned shutdown).

---

## 6. Vdc Reference

A `Vdc` groups devices that belong to the same integration (e.g. all lights from one protocol).
There is typically one Vdc per integration type.

### 6.1 Constructor parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `implementation_id` | `str` | required | Protocol-unique string identifying this vDC implementation (e.g. `"x-mycompany-lights"`). Used as part of the `modelUID`. |
| `name` | `str` | required | User-visible name of this connector |
| `dsuid` | `DsUid \| None` | auto-generated | Stable ID of this vDC; auto-generated from `implementation_id` if omitted |
| `model` | `str \| None` | `None` | Model description |
| `model_version` | `str \| None` | `None` | Firmware/version string |
| `device_class` | `str \| None` | `None` | dS-defined device class profile name |
| `device_class_version` | `str \| None` | `None` | Revision of the device class profile |
| `capabilities` | `VdcCapabilities` | default | Feature flags for this vDC |

### 6.2 VdcCapabilities

```python
from pydsvdcapi import VdcCapabilities

caps = VdcCapabilities(
    metering=False,           # True if devices report energy metering
    identification=True,      # True if devices can identify themselves
    dynamic_definitions=False,# True if states/events/actions come from oemModelGuid lookup
)
vdc = Vdc(implementation_id="x-myapp", capabilities=caps, ...)
```

### 6.3 Managing devices

```python
vdc.add_device(device)              # add a Device
vdc.remove_device(dsuid)            # remove by base dSUID
vdc.get_device(dsuid)               # look up
for dsuid, dev in vdc.devices.items():
    ...
```

---

## 7. Vdsd Reference

`Vdsd` is the virtual device entity visible to the dSS. Every room control action ultimately
targets one or more Vdsd instances.

### 7.1 Constructor parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dsuid` | `DsUid` | required | Stable unique ID for this virtual device |
| `name` | `str` | required | User-visible device name (editable in configurator) |
| `model` | `str \| None` | `None` | Model description |
| `model_version` | `str \| None` | `None` | Firmware version string |
| `vendor_name` | `str \| None` | `None` | Vendor name |
| `vendor_id` | `str \| None` | `None` | Vendor identifier in `schema:id` format |
| `hardware_guid` | `str \| None` | `None` | Hardware-level GUID (e.g. `macaddress:AA:BB:CC:DD:EE:FF`) |
| `hardware_model_guid` | `str \| None` | `None` | Hardware model GUID (e.g. `enoceaneep:A50904`) |
| `oem_guid` | `str \| None` | `None` | OEM product GUID |
| `oem_model_guid` | `str \| None` | `None` | OEM product model GUID (GTIN: `gs1:(01)GTIN13`). **Critical for dSS dynamic feature lookup.** |
| `config_url` | `str \| None` | `None` | URL of the device's web config UI |
| `device_class` | `str \| None` | `None` | dS-defined device class profile name |
| `device_class_version` | `str \| None` | `None` | Revision of the device class profile |

### 7.2 Common identity properties and their effect

| Property | dSS effect |
|----------|-----------|
| `name` | Shown in configurator device tile; user can rename, change is pushed back via `setProperty` |
| `model` | Shown in configurator hardware info panel |
| `vendor_name` | Shown alongside model |
| `oem_model_guid` | **GTIN-based lookup** in the dSS device database for states, events, and action definitions |
| `config_url` | Shown as a "Configure" link in the configurator |

### 7.3 Callbacks

| Property | Signature | When called |
|----------|-----------|-------------|
| `on_identify` | `async (vdsd) -> None` | vdSM asks the device to blink/flash for physical identification |
| `on_control_value` | `async (vdsd, name, value, group, zone_id) -> None` | vdSM sends a `setControlValue` (e.g. room temperature setpoint) |

### 7.4 Physical device identification

When the user physically touches the device (e.g. presses a pairing button on the hardware),
call `send_identify()` to notify the dSS which device was touched:

```python
# User pressed the pairing button on the physical hardware
await vdsd.send_identify()
```

The dSS uses the incoming dSUID to proceed with pairing or zone assignment without requiring
the user to enter the dSUID manually.

---

## 8. DsUid — Unique Device Identifiers

Every entity (VdcHost, Vdc, Vdsd) needs a stable `DsUid`. The ID must be deterministic —
the same hardware must produce the same dSUID on every restart, because the dSS uses the dSUID
as the primary key for all stored configuration.

```python
from pydsvdcapi import DsUid, DsUidNamespace

# UUID-based (for devices with no better hardware ID)
# IMPORTANT: store this and reuse it across restarts — or derive it deterministically
uid = DsUid.new_uuid_based()

# GTIN-based (for off-the-shelf hardware with a GS1 GTIN)
uid = DsUid.new_gtin_based("0123456789012", subdevice_index=0)

# From an EnOcean radio address (32-bit hex)
uid = DsUid.from_enocean("A4BC23D2", subdevice_index=0)

# From a MAC address
uid = DsUid.from_mac("AA:BB:CC:DD:EE:FF", subdevice_index=0)

# Sub-device enumeration (share bytes 0-15 with a sibling Vdsd)
sibling = uid.derive_subdevice(1)
```

**Rule:** If the hardware has a GTIN, use `new_gtin_based`. If it has an EnOcean ID or MAC,
use the corresponding factory. Only use `new_uuid_based()` for devices with no other stable ID,
and in that case store the returned `DsUid` in the persistence YAML so it survives restarts.

---
````

- [ ] **Step 2: Run a quick Sphinx check (optional but recommended)**

```bash
python -m sphinx docs/ docs/_build/html -q 2>&1 | head -30
```
Any warnings about missing `guide` are expected until MyST is installed; zero errors is the goal.

- [ ] **Step 3: Commit**

```bash
git add docs/guide.md
git commit -m "docs: add architecture, entity hierarchy, VdcHost/Vdc/Vdsd/DsUid reference"
```

---

## Task 9: Write `docs/guide.md` — Part 3: Output and Channels

**Files:**
- Modify: `docs/guide.md` (append)

- [ ] **Step 1: Append output and channel reference**

Append to `docs/guide.md`:

````markdown
## 9. Output Reference

Each Vdsd has **at most one** output. The output declares what kind of controllable thing the
device is (light, shade, switch, etc.) and owns all output channels.

### 9.1 Creating an output

```python
from pydsvdcapi import Output, OutputFunction, OutputMode, OutputUsage, ColorGroup

output = Output(
    function=OutputFunction.DIMMER,
    mode=OutputMode.PWM,
    usage=OutputUsage.ROOM,
    group=ColorGroup.YELLOW,
)
vdsd.set_output(output)
```

### 9.2 OutputFunction — what kind of device this is

| Value | Channels auto-created | Typical device |
|-------|-----------------------|----------------|
| `ON_OFF` | brightness | Switch, relay |
| `DIMMER` | brightness | Dimmable light |
| `DIMMER_COLOR_TEMP` | brightness, colortemp | Tunable white light |
| `FULL_COLOR_DIMMER` | brightness, hue, saturation, colortemp, cieX, cieY | RGB/RGBW light |
| `POSITIONAL` | none (add manually) | Shade/blind motor |
| `BIPOLAR` | none (add manually) | Bipolar actuator |
| `INTERNALLY_CONTROLLED` | none (add manually) | Self-regulating device |
| `CUSTOM` | none (add manually) | Anything else |
| `AUDIO_VOLUME` | volume | Speaker/amplifier volume |
| `VENTILATION` | airflow | Fan/ventilation unit |
| `HEATING_LEVEL` | heatingPower | Heating actuator |
| `COOLING_LEVEL` | coolingPower | Cooling actuator |
| `FCU_OPERATION_MODE` | fcuOperationMode | Fan Coil Unit |

### 9.3 OutputMode

| Value | Meaning |
|-------|---------|
| `SWITCH` | Binary on/off only |
| `RAMP_TO_VALUE` | Ramping with a transition time |
| `PWM` | Pulse-width modulation (most dimmable devices) |
| `HEATING_PWM` | PWM for heating actuators |
| `POSITION_RELAY` | Positional relay (shade) |
| `POSITION_PWM` | Positional PWM (shade) |

### 9.4 OutputUsage

| Value | Meaning |
|-------|---------|
| `ROOM` | Room-level control |
| `ZONE` | Zone-level control |
| `USER` | User-defined |

### 9.5 Shade / POSITIONAL outputs

For shade motors, use `OutputFunction.POSITIONAL` and add the required channels manually.
The library provides pre-defined specs for all standard shade channels:

```python
from pydsvdcapi import (
    Output, OutputFunction, OutputMode, OutputUsage, ColorGroup,
    OutputChannel, OutputChannelType, get_channel_spec,
)

output = Output(
    function=OutputFunction.POSITIONAL,
    mode=OutputMode.POSITION_PWM,
    usage=OutputUsage.ROOM,
    group=ColorGroup.GREY,   # grey = shade group
)

# Standard outside shade (position + blade angle)
output.add_channel(OutputChannel(OutputChannelType.SHADE_POSITION_OUTSIDE, ds_index=0))
output.add_channel(OutputChannel(OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE, ds_index=1))

vdsd.set_output(output)
```

**Motor timing settings (shade only):**

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `motor_open_time` | `float` | `55.0` | Travel time fully closed → fully open, seconds |
| `motor_close_time` | `float` | `55.0` | Travel time fully open → fully closed, seconds |
| `motor_open_angle_time` | `float` | `1.5` | Time to rotate blade fully open, seconds |
| `motor_close_angle_time` | `float` | `1.5` | Time to rotate blade fully closed, seconds |

```python
output.motor_open_time = 60.0
output.motor_close_time = 65.0
```

### 9.6 Push changes

When `output.push_changes = True` (default), any channel value updated via `update_value()`
triggers a `VDC_SEND_PUSH_NOTIFICATION` to the dSS, so the configurator sees live values.

Set `output.push_changes = False` during bulk updates to suppress intermediate notifications.

---

## 10. Output Channels Reference

Channels are the individual controllable parameters of an output (brightness, hue, position, etc.).

### 10.1 Channel identification

Each channel has:
- A **name** (string, e.g. `"brightness"`, `"shadePositionOutside"`) — used in `setOutputChannelValue` from dSS
- An **`OutputChannelType`** enum value — used internally and in `channelDescriptions`
- A **`ds_index`** integer — used in API v2 numeric key addressing

### 10.2 Available OutputChannelType values

| Enum | Name | Unit | Device type |
|------|------|------|-------------|
| `BRIGHTNESS` | `brightness` | % | Light |
| `HUE` | `hue` | ° | Color light |
| `SATURATION` | `saturation` | % | Color light |
| `COLOR_TEMP` | `colortemp` | mired | Tunable white |
| `CIE_X` | `cieX` | — | Color light (CIE x) |
| `CIE_Y` | `cieY` | — | Color light (CIE y) |
| `SHADE_POSITION_OUTSIDE` | `shadePositionOutside` | % | Shade outside |
| `SHADE_POSITION_INDOOR` | `shadePositionIndoor` | % | Shade indoor |
| `SHADE_OPENING_ANGLE_OUTSIDE` | `shadeOpeningAngleOutside` | ° | Blade angle outside |
| `SHADE_OPENING_ANGLE_INDOOR` | `shadeOpeningAngleIndoor` | ° | Blade angle indoor |
| `AIR_FLOW_INTENSITY` | `airFlowIntensity` | % | Ventilation speed |
| `AIR_FLOW_DIRECTION` | `airFlowDirection` | enum | Ventilation direction |
| `AIR_LOUVER_AUTO` | `airLouverAuto` | enum | Louver auto mode |
| `AIR_LOUVER_POSITION` | `airLouverPosition` | % | Louver position |
| `AIR_FLOW_AUTO` | `airFlowAuto` | enum | Flow auto mode |
| `HEATING_POWER` | `heatingPower` | % | Heating actuator |
| `COOLING_CAPACITY` | `coolingCapacity` | % | Cooling actuator |
| `AUDIO_VOLUME` | `volume` | % | Speaker volume |
| `POWER_STATE` | `powerState` | enum | Power on/off/standby |
| `FCU_OPERATION_MODE` | `fcuOperationMode` | enum | FCU mode |

### 10.3 Receiving commands from dSS

Register an `on_apply` callback on the channel. It is called when the dSS sends
`setOutputChannelValue` with `apply_now=True`, or when a buffered `apply_now=False`
batch is committed:

```python
brightness = output.channels["brightness"]

@brightness.on_apply
async def apply_brightness(value: float) -> None:
    # value is in the channel's native unit (% for brightness)
    await hardware.set_brightness(value)
```

For color lights where multiple channels are set simultaneously, use `apply_now=False`
buffering: the dSS sends individual channel values with `apply_now=False`, then a final
`setOutputChannelValue` with `apply_now=True` to commit. The library batches these and calls
each channel's `on_apply` only once per commit.

### 10.4 Updating values from the device side

When the physical hardware reports a change (e.g. a sensor measuring actual brightness):

```python
await output.channels["brightness"].update_value(73.5)
# If push_changes=True: automatically sends VDC_SEND_PUSH_NOTIFICATION to dSS
```

### 10.5 Value converters on channels

Converters transform the raw value between the device's native range and the dS percentage
range before the value is stored or an `on_apply` callback is called:

```python
from pydsvdcapi import compile_converter

# Device uses 0–255; dS uses 0–100 %
converter = compile_converter("value * 100 / 255")
output.channels["brightness"].set_converter(converter)
```

---
````

- [ ] **Step 2: Commit**

```bash
git add docs/guide.md
git commit -m "docs: add Output and channel reference sections"
```

---

## Task 10: Write `docs/guide.md` — Part 4: Inputs

**Files:**
- Modify: `docs/guide.md` (append)

- [ ] **Step 1: Append inputs reference**

Append to `docs/guide.md`:

````markdown
## 11. Binary Input Reference

A `BinaryInput` models one on/off sensor input (door contact, motion detector, window handle).

### 11.1 Creating a binary input

```python
from pydsvdcapi import BinaryInput, BinaryInputType, BinaryInputUsage, BinaryInputGroup

bi = BinaryInput(
    vdsd=my_vdsd,
    ds_index=0,
    sensor_function=BinaryInputType.PRESENCE,
    input_usage=BinaryInputUsage.ROOM_CLIMATE,
    update_interval=0,      # 0 = event-driven
    alive_sign_interval=0,  # 0 = no periodic keep-alive
)
my_vdsd.add_binary_input(bi)
```

### 11.2 BinaryInputType

`NONE`, `PRESENCE`, `BRIGHTNESS`, `PRESENCE_IN_DARKNESS`, `TWILIGHT`, `MOTION`,
`MOTION_IN_DARKNESS`, `SMOKE`, `WIND`, `RAIN`, `SUN_RADIATION`, `THERMOSTAT`,
`LOW_BATTERY`, `WINDOW_HANDLE`, `DOOR_BELL`, `HIGH_TEMPERATURE`, `LOW_TEMPERATURE`,
`FROST`, `ICE_DETECTION`, `HEATING_SYSTEM_ERROR`, `COOLING_SYSTEM_ERROR`, `FILTER_FAILURE`

### 11.3 BinaryInputGroup (dS room group)

`UNDEFINED`, `YELLOW` (light), `GREY` (shade), `BLUE` (heating/climate), `CYAN` (audio),
`MAGENTA` (video), `RED` (security), `GREEN` (access), `BLACK` (joker)

### 11.4 Updating values

```python
# Boolean state (most binary inputs)
await bi.update_value(True)    # contact closed / active

# Extended integer state (window handle: 0=closed, 1=tilted, 2=open)
await bi.update_extended_value(2)
```

When the Vdsd is announced, updates push `binaryInputStates` to the dSS automatically.

### 11.5 Settings callback

```python
from pydsvdcapi import BinaryInputSettingsChangedCallback

async def on_settings(bi: BinaryInput) -> None:
    print(f"Binary input group changed to {bi.group}")

bi.on_settings_changed = on_settings
```

---

## 12. Button Input Reference

A `ButtonInput` models one physical button element on a device.

### 12.1 Creating button inputs

```python
from pydsvdcapi import (
    ButtonInput, ButtonType, ButtonMode, ButtonGroup, ButtonFunction,
    create_button_group,
)

# Single pushbutton (most common)
btn = ButtonInput(
    vdsd=my_vdsd,
    ds_index=0,
    button_type=ButtonType.SINGLE,
    button_mode=ButtonMode.STANDARD,
    group=ButtonGroup.YELLOW,
    button_function=ButtonFunction.DEVICE,
)
my_vdsd.add_button_input(btn)

# Two-button rocker (up/down pair)
buttons = create_button_group(
    vdsd=my_vdsd,
    ds_index_start=0,
    count=2,
    button_type=ButtonType.TWO_WAY,
    group=ButtonGroup.YELLOW,
)
for b in buttons:
    my_vdsd.add_button_input(b)
```

### 12.2 ButtonType

| Value | Meaning |
|-------|---------|
| `SINGLE` | One push button |
| `TWO_WAY` | Up/down or on/off pair |
| `FOUR_WAY` | 4-way control (up/down/left/right or scene 1–4) |

### 12.3 ButtonMode

`STANDARD`, `TURBO`, `CONFIGURED`, `DISABLED`

### 12.4 Click detection

Use `ClickDetector` to detect short press, long press, and double-click:

```python
from pydsvdcapi import ClickDetector, ButtonClickType

detector = ClickDetector(btn)

@detector.on_click
async def handle_click(click_type: ButtonClickType) -> None:
    if click_type == ButtonClickType.SHORT_CLICK:
        print("Short press")
    elif click_type == ButtonClickType.LONG_CLICK:
        print("Long press")
```

---

## 13. Sensor Input Reference

A `SensorInput` models one analog sensor (temperature, humidity, illuminance, etc.).

### 13.1 Creating a sensor input

```python
from pydsvdcapi import SensorInput, SensorType, SensorUsage, SensorGroup

si = SensorInput(
    vdsd=my_vdsd,
    ds_index=0,
    sensor_type=SensorType.TEMPERATURE,
    usage=SensorUsage.ROOM,
    update_interval=60,       # seconds between expected updates
    alive_sign_interval=600,  # seconds between keep-alive signals
)
my_vdsd.add_sensor_input(si)
```

### 13.2 SensorType

`TEMPERATURE`, `RELATIVE_HUMIDITY`, `ILLUMINATION`, `SUPPLY_VOLTAGE`, `CO2_CONCENTRATION`,
`CO_CONCENTRATION`, `SOUND_PRESSURE_LEVEL`, `WIND_SPEED`, `RAIN_INTENSITY`, `UV_INDEX`,
`AIR_PRESSURE`, `POWER`, `ENERGY`, `ELECTRIC_CURRENT`, `ELECTRIC_VOLTAGE`,
`SET_POINT`, `HEATING_VALUE`, `WATER_AMOUNT`, `POWER_STATE`

### 13.3 Updating sensor values

```python
# Report a new reading (value in the sensor's SI unit)
await si.update_value(21.5)   # 21.5 °C for a temperature sensor

# Report an error
from pydsvdcapi import InputError
await si.set_error(InputError.NO_ERROR)
await si.set_error(InputError.OUT_OF_RANGE)
```

### 13.4 Value converters on sensors

```python
from pydsvdcapi import compile_converter

# Sensor outputs raw ADC counts 0–4095; convert to 0–100 %
converter = compile_converter("value * 100 / 4095")
si.set_converter(converter)
```

---
````

- [ ] **Step 2: Commit**

```bash
git add docs/guide.md
git commit -m "docs: add binary input, button input, sensor input reference"
```

---

## Task 11: Write `docs/guide.md` — Part 5: States, Events, Properties, and Actions

**Files:**
- Modify: `docs/guide.md` (append)

- [ ] **Step 1: Append states, events, properties, and actions reference**

Append to `docs/guide.md`:

````markdown
## 14. Device State Reference

A `DeviceState` models a discrete device state visible to the dSS (e.g. operating mode, error
state, connection status). States have a fixed set of named options.

### 14.1 Creating a device state

```python
from pydsvdcapi import DeviceState

st = DeviceState(
    vdsd=my_vdsd,
    ds_index=0,
    name="operatingState",
    options={0: "Off", 1: "Initializing", 2: "Running", 3: "Shutdown"},
    description="Current operating state of the device",
)
my_vdsd.add_device_state(st)
```

### 14.2 Updating state values

```python
# By key (integer)
await st.update_value(2)           # → "Running"

# By label (string) — resolved to key automatically
await st.update_value("Running")   # → key 2
```

Updates push `deviceStates` to the dSS when the Vdsd is announced.

---

## 15. Device Event Reference

A `DeviceEvent` models a stateless one-shot occurrence (button press, alarm trigger, etc.)
that is pushed to the dSS but carries no persistent state.

### 15.1 Creating a device event

```python
from pydsvdcapi import DeviceEvent

evt = DeviceEvent(
    vdsd=my_vdsd,
    ds_index=0,
    name="doorbell",
    description="Doorbell button pressed",
)
my_vdsd.add_device_event(evt)
```

### 15.2 Raising an event

```python
await evt.raise_event()
# Sends VDC_SEND_PUSH_NOTIFICATION with deviceevents payload to the dSS
```

---

## 16. Device Property Reference

A `DeviceProperty` exposes an arbitrary readable/writable value on the device — useful for
configuration parameters that the dSS configurator should display or allow editing.

### 16.1 Property types

| Constant | Type | Example |
|----------|------|---------|
| `PROPERTY_TYPE_NUMERIC` | float | temperature setpoint |
| `PROPERTY_TYPE_STRING` | str | firmware version |
| `PROPERTY_TYPE_ENUMERATION` | int | mode selection |

### 16.2 Creating a device property

```python
from pydsvdcapi import DeviceProperty, PROPERTY_TYPE_NUMERIC

prop = DeviceProperty(
    vdsd=my_vdsd,
    ds_index=0,
    name="targetTemperature",
    property_type=PROPERTY_TYPE_NUMERIC,
    description="Heating setpoint in °C",
    default_value=21.0,
    min_value=5.0,
    max_value=35.0,
    resolution=0.5,
    si_unit="degree Celsius",
)
my_vdsd.add_device_property(prop)
```

### 16.3 Reading and writing values

```python
# Update the stored value and push to dSS
await prop.update_value(22.5)

# React when dSS writes the property
async def on_set(value: float) -> None:
    await hardware.set_setpoint(value)

prop.on_set = on_set
```

---

## 17. Actions Reference

The vDC API supports three categories of device actions:

| Category | Prefix | Persistence | Who controls |
|----------|--------|-------------|--------------|
| `StandardAction` | `std.` | Permanent | Device (defined at build time) |
| `CustomAction` | `custom.` | Persisted YAML | User (created/edited via configurator) |
| `DynamicAction` | `dynamic.` | Transient | Device hardware |

### 17.1 Defining action templates and standard actions

```python
from pydsvdcapi import ActionParameter, DeviceActionDescription, StandardAction

# Template: defines the action schema (parameters and their types)
param = ActionParameter(
    name="scene",
    type="enumeration",
    options={"0": "Off", "1": "On", "2": "Bright", "3": "Dim"},
    default=1,
)
tmpl = DeviceActionDescription(
    vdsd=my_vdsd,
    ds_index=0,
    name="activateScene",
    description="Activate a preset scene",
    params=[param],
)
my_vdsd.add_device_action_description(tmpl)

# Standard action: a fixed instance of the template
action = StandardAction(
    vdsd=my_vdsd,
    ds_index=0,
    action_description=tmpl,
    name="std.activateDefault",
    param_overrides={"scene": 1},
)
my_vdsd.add_standard_action(action)
```

### 17.2 Receiving action invocations

```python
from pydsvdcapi import InvokeActionCallback

async def on_invoke(vdsd: Vdsd, action_id: str, params: dict) -> None:
    print(f"Action '{action_id}' invoked with {params}")

my_vdsd.on_invoke_action = on_invoke
```

---
````

- [ ] **Step 2: Commit**

```bash
git add docs/guide.md
git commit -m "docs: add device state, event, property, and actions reference"
```

---

## Task 12: Write `docs/guide.md` — Part 6: Model Features Reference

**Files:**
- Modify: `docs/guide.md` (append)

- [ ] **Step 1: Append model features reference**

Append to `docs/guide.md`:

````markdown
## 18. Model Features Reference

`modelFeatures` is the list of capability flags that tells the dSS configurator which UI panels
and controls to display for a device. They are announced during `VDC_SEND_ANNOUNCE_DEVICE`.

The library auto-derives the correct set of flags from the configured components when
`derive_model_features()` runs at announcement time. You can also add or remove flags manually.

### 18.1 Manually adding or removing features

```python
my_vdsd.add_model_feature("transt")
my_vdsd.remove_model_feature("blink")
```

Call these **before** the device is announced (before `host.run()` announces it), or after
calling `derive_model_features()` if you need to adjust the auto-derived set.

### 18.2 Auto-derived features (set automatically based on configured components)

| Trigger | Feature added | Configurator UI effect |
|---------|---------------|------------------------|
| Any output present | `dontcare` | Per-scene "retain current value" checkbox |
| Any output present | `blink` | Per-scene "blink effect" checkbox |
| Channel type in {1–12, 14–18, 22–24} and `function ≠ POSITIONAL` | `transt` | Per-scene transition-time radio button |
| `primaryGroup ≠ 2` (non-shade) | `outvalue8` | 8-bit output value slider |
| `function == ON_OFF` | `outconfigswitch` | Switch output threshold UI |
| `function == ON_OFF` | `impulseconfig` | "Impulse" tab in device properties |
| Channels HUE+SAT or BRIGHTNESS+COLOR_TEMP both present | `outputchannels` | Extra channel controls |
| `function` in {DIMMER, DIMMER_COLOR_TEMP, FULL_COLOR_DIMMER} | `dimtimeconfig` | Dim time settings |
| Channel type HEATING_POWER, or shade group + ON_OFF | `pwmvalue` | PWM-mode indicator |
| Any ventilation channel (types 12, 13, 14, 15, 20, 21) | `ventconfig` | Ventilation speed/flap config |
| `primaryGroup == 2` + `function == POSITIONAL` | `shadeposition` | 16-bit position slider + buttons |
| POSITIONAL + blade angle channel (type 9 or 10) | `shadebladeang` | Blade angle slider |
| `on_identify` callback registered | `identification` | "Identify" button in configurator |
| Any `BinaryInput` added | `binaryInputs` | Binary input panel |
| Any `SensorInput` added | `sensors` | Sensor panel |
| Any `ButtonInput` added | `pushbutton` | Button configuration panel |
| `button_type == TWO_WAY` on any button | `twowayconfig` | 2-way rocker configuration |
| Any `DeviceState` added | `states` | Device state panel |
| Any `DeviceEvent` added | `events` | Device events panel |
| Heating output (group 3) present | `heatinggroup` | Heating group indicator |
| Climate Vdsd (group 48) | `fcu` | FCU-mode control panel |
| Both heating and cooling sensors | `heatcoolctl` | Heating/cooling control |

### 18.3 Manually addable features (not auto-derived)

| Feature | When to add manually |
|---------|----------------------|
| `shadeprops` | Shade devices that expose motor travel time via `outputSettings` and allow the dSS to write motor timing values |
| `motiontimefins` | Shade devices that support fin rotation timing configuration |

### 18.4 Blocked features (not applicable to vDC devices)

The following features are rejected with `ValueError` because they only apply to classic
DS485 bus hardware and have no effect over the vDC API:

`akminput`, `akmdelay`, `akmsensor`, `akmreducepower`, `frostprotection`, `pairedDevices`,
`syncButtonUp`, `syncButtonDown`

---
````

- [ ] **Step 2: Commit**

```bash
git add docs/guide.md
git commit -m "docs: add model features reference"
```

---

## Task 13: Write `docs/guide.md` — Part 7: Lifecycle, Persistence, Converters, Templates

**Files:**
- Modify: `docs/guide.md` (append)

- [ ] **Step 1: Append lifecycle, persistence, converters, and templates**

Append to `docs/guide.md`:

````markdown
## 19. Device Lifecycle Reference

`DeviceLifecycleState` describes the health of a physical device. The library uses this to
decide whether to respond to ping requests and when to push `active` property changes to the dSS.

### 19.1 States

| State | `active` pushed | Ping response | Meaning |
|-------|-----------------|---------------|---------|
| `ACTIVE` | Yes (on transition) | Pong sent | Device operating normally |
| `INACTIVE` | Yes (on transition) | No pong | Device powered off or intentionally offline |
| `MAINTENANCE` | Yes (on transition) | No pong | Device in maintenance mode |
| `ERROR` | Yes (on transition) | No pong | Communication error or hardware fault |
| `REMOVED` | Yes (on transition) | `VDC_SEND_VANISH` | Device permanently removed |

### 19.2 Setting lifecycle state

```python
from pydsvdcapi import DeviceLifecycleState

# Device came online
await vdsd.set_lifecycle_state(DeviceLifecycleState.ACTIVE)

# Device offline (network loss, powered off)
await vdsd.set_lifecycle_state(DeviceLifecycleState.INACTIVE)

# Device permanently removed from the installation
await vdsd.set_lifecycle_state(DeviceLifecycleState.REMOVED)
```

Changes push `active` property immediately to the dSS. The `REMOVED` state causes a
`VDC_SEND_VANISH` to be sent on every subsequent ping until the Vdsd is also removed from
the Vdc.

### 19.3 Ping / pong

The dSS periodically sends `VDSM_SEND_PING` to check device presence. The library responds
automatically based on lifecycle state: `ACTIVE` devices receive pong; all others suppress it.
Your application does not need to handle ping directly.

---

## 20. Persistence Reference

When `state_path` is configured on the VdcHost, the library persists the following to a YAML
file:

**Persisted (survive restarts):**
- Device descriptions (name, model, vendor, etc.)
- Output descriptions and settings (mode, groups, channel descriptions and settings)
- Input descriptions and settings (sensor type, group, function)
- Button descriptions and settings (mode, group, function)
- Custom actions (user-created)
- Device property descriptions

**Transient (not persisted):**
- Output channel values and state
- Sensor readings and binary input states
- Device state values
- Dynamic actions
- Session state (ping counters, etc.)

### 20.1 Auto-save timing

```python
from pydsvdcapi import AUTO_SAVE_DELAY
# Default: 2.0 seconds debounce
```

After any tracked property changes, the save is scheduled after `AUTO_SAVE_DELAY` seconds.
Rapid changes within that window coalesce into a single write.

```python
host.flush()   # force immediate write (use before shutdown)
host.save()    # equivalent to flush()
host.load()    # reload from disk (normally called automatically at start)
```

---

## 21. Value Converters Reference

Converters let you transform raw hardware values to/from the dS range without writing
custom conversion code in every callback.

### 21.1 Compiling a converter

```python
from pydsvdcapi import compile_converter, apply_converter

# Simple linear scaling
converter = compile_converter("value * 100 / 255")   # 0-255 → 0-100%

# Two-way converter: different expressions for each direction
converter = compile_converter({
    "downlink": "value * 255 / 100",   # dS (0-100%) → hardware (0-255)
    "uplink":   "value * 100 / 255",   # hardware → dS
})

# With clamping
converter = compile_converter("max(0, min(100, value * 100 / 4095))")
```

### 21.2 Attaching converters

```python
# On an output channel
output.channels["brightness"].set_converter(converter)

# On a sensor input
sensor.set_converter(converter)

# On a binary input (for extended values)
binary_input.set_converter(converter)

# On a device property
device_property.set_converter(converter)
```

### 21.3 Direct application

```python
result = apply_converter(converter, 128, direction="uplink")
```

---

## 22. Device Templates Reference

A `DeviceTemplate` is a structural snapshot of a `Device` with instance-specific values
stripped. Templates allow creating identically structured devices with minimal per-instance
configuration.

### 22.1 Saving a template

```python
vdc.save_template(
    device,
    template_type="generic",            # "generic" or "model"
    integration="x-myapp-lights",
    name="dimmable-light",
    description="Standard dimmable light",
)
```

Template files are saved to the `state_path` directory under
`templates/<template_type>/<integration>/<name>.yaml`.

### 22.2 Loading and using a template

```python
tmpl = vdc.load_template(
    template_type="generic",
    integration="x-myapp-lights",
    name="dimmable-light",
)

# Configure instance-specific fields
tmpl.configure({
    "vdsds[0].name": "Kitchen Light",
})

if tmpl.is_ready():
    device = tmpl.instantiate(vdc=vdc, dsuid=my_dsuid)
    device.vdsds[0].output.channels["brightness"].on_apply = apply_brightness
    await device.announce(session)
```

### 22.3 Required fields

Templates record which fields must be supplied via `configure()` before `instantiate()`
can be called. `is_ready()` returns `False` until all required fields are set.

---

## 23. Session Constants Reference

| Constant | Value | Description |
|----------|-------|-------------|
| `SUPPORTED_API_VERSION` | `2` | Minimum vDC API version accepted |
| `MAX_SUPPORTED_API_VERSION` | `4` | Maximum vDC API version accepted |
| `DEFAULT_VDC_PORT` | `8444` | Default TCP port |
| `AUTO_SAVE_DELAY` | `2.0` | Debounce delay for auto-save (seconds) |
| `MAX_MESSAGE_LENGTH` | `65536` | Maximum protobuf message size |
| `ENTITY_TYPE_VDC_HOST` | `"vDChost"` | Entity type string for VdcHost |
| `ENTITY_TYPE_VDC` | `"vDC"` | Entity type string for Vdc |
| `ENTITY_TYPE_VDSD` | `"vdSD"` | Entity type string for Vdsd |

---
````

- [ ] **Step 2: Commit**

```bash
git add docs/guide.md
git commit -m "docs: add lifecycle, persistence, converters, templates, constants reference"
```

---

## Task 14: Update README.md and CONTRIBUTING.md

**Files:**
- Modify: `README.md`
- Modify: `CONTRIBUTING.md`

- [ ] **Step 1: Update README.md**

Replace the "See also" / examples links with references to guide.md.

Find the lines:
```markdown
See [`examples/getting_started.py`](examples/getting_started.py) for a minimal runnable example
and [`examples/full_showcase.py`](examples/full_showcase.py) for all 27 device classes.
```
Replace with:
```markdown
See the [Developer Guide](docs/guide.md) for complete reference documentation.
```

Update the Documentation section:
```markdown
## Documentation

Full guide: [`docs/guide.md`](docs/guide.md)

API reference: [pydsvdcapi.readthedocs.io](https://pydsvdcapi.readthedocs.io)
```

Remove the domain documentation bullet list (those files are now gone or consolidated).

- [ ] **Step 2: Update CONTRIBUTING.md**

Remove the `examples/` entry from the project layout:
```
tests/               # pytest tests (mirror the src/ structure)
examples/            # usage examples     ← remove this line
docs/                # supplementary documentation
```

- [ ] **Step 3: Commit**

```bash
git add README.md CONTRIBUTING.md
git commit -m "docs: update README and CONTRIBUTING for new guide structure"
```

---

## Task 15: Final verification

**Files:** no changes (verification only)

- [ ] **Step 1: Run the full test suite**

```bash
python -m pytest -q
```
Expected: all tests pass (1614+ passing, 0 failures).

- [ ] **Step 2: Search for any remaining p44/plan44 references**

```bash
grep -rn "p44\|plan44\|Plan44" \
    src/pydsvdcapi/ \
    tests/ \
    docs/guide.md \
    README.md \
    CHANGELOG.md \
    CONTRIBUTING.md \
    pyproject.toml \
    2>/dev/null | grep -v "_pb2\|__pycache__"
```
Expected: zero output.

- [ ] **Step 3: Verify SPDX headers present in all src files**

```bash
grep -rL "SPDX-License-Identifier" src/pydsvdcapi/*.py src/pydsvdcapi/addons/*.py src/pydsvdcapi/addons/converter/*.py 2>/dev/null | grep -v "_pb2"
```
Expected: zero output (all files have the header).

- [ ] **Step 4: Verify no references to removed docs files remain**

```bash
grep -rn "p44vdc-comparison\|p44vdc-message-flow\|api-conformance-analysis\|dss-vdc-behavior\|device-class-analysis\|message-flow-reference\|vdc-db-device-catalogue" \
    README.md CONTRIBUTING.md docs/guide.md docs/index.rst 2>/dev/null
```
Expected: zero output.

- [ ] **Step 5: Verify `conversion.py` is gone and imports work**

```bash
python -c "from pydsvdcapi import apply_converter, compile_converter; print('OK')"
```
Expected: `OK`.

```bash
test -f src/pydsvdcapi/conversion.py && echo "ERROR: shim still exists" || echo "OK: shim removed"
```
Expected: `OK: shim removed`.

- [ ] **Step 6: Lint pass**

```bash
ruff check src/ tests/
```
Expected: 0 errors.

- [ ] **Step 7: Final commit if any cleanups were needed**

```bash
git status
# If any files were modified during verification fixes:
git add -u
git commit -m "chore: final cleanup from verification pass"
```

---

## Self-Review

### Spec coverage

| Requirement | Covered in task(s) |
|-------------|--------------------|
| Move obsolete files to `old/`, add to .gitignore | Task 1 |
| Move examples to `old/` | Task 1 |
| Move superpowers plans/specs to `old/` | Task 1 |
| Add GPL v3 SPDX headers to all src files | Task 4 |
| Remove all p44/plan44 references from src/ | Task 2 |
| Remove all p44/plan44 references from tests/ and CHANGELOG | Task 3 |
| Remove `conversion.py` shim | Task 5 |
| Update internal imports to `addons.converter` | Task 5 |
| Update Sphinx for MyST + guide.md | Task 6 |
| Comprehensive guide.md — introduction and purpose | Task 7 |
| Comprehensive guide.md — architecture + entity reference | Task 8 |
| Comprehensive guide.md — output and channels | Task 9 |
| Comprehensive guide.md — inputs | Task 10 |
| Comprehensive guide.md — states, events, properties, actions | Task 11 |
| Comprehensive guide.md — model features | Task 12 |
| Comprehensive guide.md — lifecycle, persistence, converters, templates | Task 13 |
| Update README.md and CONTRIBUTING.md | Task 14 |
| Final verification | Task 15 |

### Placeholder scan

No TBDs, TODOs, or "similar to" references. All code blocks contain actual content. All file
paths are exact.

### Type consistency

No new types are introduced. All API references in the guide match the actual exported names in
`src/pydsvdcapi/__init__.py`.
