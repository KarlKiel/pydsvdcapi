# scanDevices GenericRequest Handler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Handle the `scanDevices` (and versioned `scanDevices/N`) `GenericRequest` that the vdSM sends when the dSS configurator triggers "re-register devices", so that pydsvdcapi re-announces the addressed vDC and all its devices instead of returning `ERR_NOT_IMPLEMENTED`.

**Architecture:** The vdSM sends `VDSM_REQUEST_GENERIC_REQUEST` with `methodname = "scanDevices/6"` (or similar version-suffixed name) targeting the vDC's dSUID. The existing `_handle_generic_request()` in `VdcHost` needs two changes: (1) strip the `/N` version suffix from any method name so existing and future versioned calls are handled correctly; (2) add a `scanDevices` branch that resets announcement flags on the addressed vDC and re-announces it and all its devices. If the dSUID is the host's own dSUID, all vDCs are re-announced.

**Tech Stack:** Python 3.10+, asyncio, protobuf (`vdc_messages_pb2`), pytest-asyncio, `unittest.mock`.

---

## File Structure

- **Modify:** `src/pydsvdcapi/vdc_host.py` — two edits:
  1. Line ~1373: add one line stripping the `/N` version suffix from `method`
  2. After `setConfiguration` block (~line 1558): add the `scanDevices` handler branch + update docstring at ~line 1356
- **Modify:** `tests/test_vdc_host.py` — append new `TestHandleScanDevicesGenericRequest` class
- **Modify:** `docs/vdc-host-behavior.md` — document the new behaviour under §2.5

---

### Task 1: Implement `scanDevices` handler

**Files:**
- Modify: `src/pydsvdcapi/vdc_host.py` (lines ~1353–1568)
- Modify: `tests/test_vdc_host.py` (append after line 710)

- [ ] **Step 1: Write the failing tests**

Add this class at the end of `tests/test_vdc_host.py`:

```python
# ---------------------------------------------------------------------------
# scanDevices handler (GenericRequest)
# ---------------------------------------------------------------------------


def _make_scan_devices_msg(dsuid_str: str, method: str = "scanDevices", msg_id: int = 55) -> "pb.Message":
    """Build a GenericRequest 'scanDevices' protobuf message."""
    msg = pb.Message()
    msg.type = pb.VDSM_REQUEST_GENERIC_REQUEST
    msg.message_id = msg_id
    msg.vdsm_request_generic_request.methodname = method
    msg.vdsm_request_generic_request.dSUID = dsuid_str
    return msg


def _make_ok_session() -> MagicMock:
    """Session mock whose send_request always returns ERR_OK."""
    ok_resp = pb.Message()
    ok_resp.generic_response.code = pb.ERR_OK
    session = MagicMock(spec=VdcSession)
    session.is_active = True
    session.send_request = AsyncMock(return_value=ok_resp)
    return session


class TestHandleScanDevicesGenericRequest:
    """Tests for GenericRequest 'scanDevices' (and versioned variants)."""

    @pytest.mark.asyncio
    async def test_scan_devices_reannounces_vdc_and_devices(self):
        """scanDevices re-announces the addressed vDC and its device."""
        host, vdc, _device, _vdsd = _make_host_with_device()
        session = _make_ok_session()

        msg = _make_scan_devices_msg(str(vdc.dsuid))
        resp = await host._dispatch_message(session, msg)

        assert resp.generic_response.code == pb.ERR_OK
        sent_types = [c.args[0].type for c in session.send_request.call_args_list]
        assert pb.VDC_SEND_ANNOUNCE_VDC in sent_types
        assert pb.VDC_SEND_ANNOUNCE_DEVICE in sent_types

    @pytest.mark.asyncio
    async def test_scan_devices_versioned_method_name(self):
        """'scanDevices/6' is handled identically to 'scanDevices'."""
        host, vdc, _device, _vdsd = _make_host_with_device()
        session = _make_ok_session()

        msg = _make_scan_devices_msg(str(vdc.dsuid), method="scanDevices/6")
        resp = await host._dispatch_message(session, msg)

        assert resp.generic_response.code == pb.ERR_OK
        sent_types = [c.args[0].type for c in session.send_request.call_args_list]
        assert pb.VDC_SEND_ANNOUNCE_VDC in sent_types
        assert pb.VDC_SEND_ANNOUNCE_DEVICE in sent_types

    @pytest.mark.asyncio
    async def test_scan_devices_resets_announcement_flags(self):
        """scanDevices re-announces even if the vDC was already announced."""
        host, vdc, device, _vdsd = _make_host_with_device()
        session = _make_ok_session()

        # Pre-mark as announced so we can verify reset + re-announce.
        vdc._announced = True
        device._announced = True

        msg = _make_scan_devices_msg(str(vdc.dsuid))
        resp = await host._dispatch_message(session, msg)

        assert resp.generic_response.code == pb.ERR_OK
        sent_types = [c.args[0].type for c in session.send_request.call_args_list]
        assert pb.VDC_SEND_ANNOUNCE_VDC in sent_types
        assert pb.VDC_SEND_ANNOUNCE_DEVICE in sent_types

    @pytest.mark.asyncio
    async def test_scan_devices_host_dsuid_reannounces_all(self):
        """scanDevices with the host's own dSUID re-announces all vDCs."""
        host, vdc, _device, _vdsd = _make_host_with_device()
        session = _make_ok_session()

        msg = _make_scan_devices_msg(str(host.dsuid))
        resp = await host._dispatch_message(session, msg)

        assert resp.generic_response.code == pb.ERR_OK
        sent_types = [c.args[0].type for c in session.send_request.call_args_list]
        assert pb.VDC_SEND_ANNOUNCE_VDC in sent_types
        assert pb.VDC_SEND_ANNOUNCE_DEVICE in sent_types

    @pytest.mark.asyncio
    async def test_scan_devices_unknown_dsuid_returns_not_found(self):
        """scanDevices with an unknown dSUID returns ERR_NOT_FOUND."""
        host, _vdc, _device, _vdsd = _make_host_with_device()
        session = _make_ok_session()

        msg = _make_scan_devices_msg("00" * 17)
        resp = await host._dispatch_message(session, msg)

        assert resp.generic_response.code == pb.ERR_NOT_FOUND
        session.send_request.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
python -m pytest tests/test_vdc_host.py::TestHandleScanDevicesGenericRequest -v
```

Expected: all 5 tests FAIL — `resp.generic_response.code` will be `ERR_NOT_IMPLEMENTED` (the current fallback), not `ERR_OK` / `ERR_NOT_FOUND`.

- [ ] **Step 3: Implement the handler in `vdc_host.py`**

**Edit 1** — strip version suffix from all method names. Locate this block in `_handle_generic_request()`:

```python
        req = msg.vdsm_request_generic_request
        method = req.methodname
        dsuid_str = req.dSUID
```

Replace with:

```python
        req = msg.vdsm_request_generic_request
        # Strip optional API-version suffix, e.g. "scanDevices/6" → "scanDevices".
        method = req.methodname.split("/")[0]
        dsuid_str = req.dSUID
```

**Edit 2** — add the `scanDevices` branch. Locate the block that ends the `setConfiguration` handler:

```python
            return resp

        # Unknown generic request — delegate to user callback.
```

Insert immediately before `# Unknown generic request`:

```python
        if method == "scanDevices":
            # Re-announce the addressed vDC and all its devices.
            # Matches "scanDevices" and versioned variants (version stripped above).
            dsuid_upper = dsuid_str.upper()
            if dsuid_upper in self._vdcs:
                vdcs_to_scan: list[Any] = [self._vdcs[dsuid_upper]]
            elif dsuid_upper == str(self._dsuid).upper():
                vdcs_to_scan = list(self._vdcs.values())
            else:
                resp.generic_response.code = pb.ERR_NOT_FOUND
                resp.generic_response.description = (
                    f"scanDevices: vDC {dsuid_str} not found"
                )
                return resp
            try:
                for vdc in vdcs_to_scan:
                    logger.info(
                        "scanDevices: re-announcing vDC '%s' (%s)",
                        vdc.name,
                        vdc.dsuid,
                    )
                    vdc.reset_announcement()
                    await vdc.announce(session)
                    await vdc.announce_devices(session)
                resp.generic_response.code = pb.ERR_OK
            except Exception as exc:  # noqa: BLE001
                logger.exception("scanDevices failed for %s", dsuid_str)
                resp.generic_response.code = pb.ERR_NOT_IMPLEMENTED
                resp.generic_response.description = str(exc)
            return resp

```

**Edit 3** — update the docstring at the top of `_handle_generic_request()`. Find the current "Currently supports:" bullet list:

```python
        Currently supports:

        * ``invokeDeviceAction`` (§7.3.10) — invoke an action on a
          target vdSD.
        * ``identify`` (§7.4.5) — identify the vDC host platform.
        * ``pair`` (§7.4.1) — learn-in / learn-out.
        * ``authenticate`` (§7.4.2) — authentication process.
        * ``firmwareUpgrade`` (§7.4.3) — firmware upgrade process.
        * ``setConfiguration`` (§7.4.4) — change device configuration.

        All other method names are delegated to the user-supplied
        ``on_message`` callback. If no callback handles them, an
        ``ERR_NOT_IMPLEMENTED`` response is returned.
```

Replace with:

```python
        Currently supports:

        * ``invokeDeviceAction`` (§7.3.10) — invoke an action on a
          target vdSD.
        * ``identify`` (§7.4.5) — identify the vDC host platform.
        * ``pair`` (§7.4.1) — learn-in / learn-out.
        * ``authenticate`` (§7.4.2) — authentication process.
        * ``firmwareUpgrade`` (§7.4.3) — firmware upgrade process.
        * ``setConfiguration`` (§7.4.4) — change device configuration.
        * ``scanDevices`` — re-announce the addressed vDC and all its
          devices (triggered by "re-register devices" in the dSS
          configurator).  Version-suffixed variants such as
          ``scanDevices/6`` are accepted; the suffix is stripped before
          dispatch.

        The vdSM may append a ``/<version>`` suffix to any method name
        (e.g. ``scanDevices/6``).  The handler strips the suffix before
        matching, so all version variants are dispatched to the same
        branch.

        All other method names are delegated to the user-supplied
        ``on_message`` callback. If no callback handles them, an
        ``ERR_NOT_IMPLEMENTED`` response is returned.
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
python -m pytest tests/test_vdc_host.py::TestHandleScanDevicesGenericRequest -v
```

Expected output:
```
PASSED tests/test_vdc_host.py::TestHandleScanDevicesGenericRequest::test_scan_devices_reannounces_vdc_and_devices
PASSED tests/test_vdc_host.py::TestHandleScanDevicesGenericRequest::test_scan_devices_versioned_method_name
PASSED tests/test_vdc_host.py::TestHandleScanDevicesGenericRequest::test_scan_devices_resets_announcement_flags
PASSED tests/test_vdc_host.py::TestHandleScanDevicesGenericRequest::test_scan_devices_host_dsuid_reannounces_all
PASSED tests/test_vdc_host.py::TestHandleScanDevicesGenericRequest::test_scan_devices_unknown_dsuid_returns_not_found
5 passed
```

- [ ] **Step 5: Run the full test suite to verify no regressions**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
python -m pytest tests/ -q
```

Expected: all tests pass (currently 1437).

- [ ] **Step 6: Commit**

```bash
git add src/pydsvdcapi/vdc_host.py tests/test_vdc_host.py
git commit -m "feat: handle scanDevices GenericRequest for vDC re-announcement"
```

---

### Task 2: Update documentation

**Files:**
- Modify: `docs/vdc-host-behavior.md`

- [ ] **Step 1: Add scanDevices documentation**

In `docs/vdc-host-behavior.md`, locate section **2.5 Session and reconnect behaviour** which currently ends at:

```
No intervention from user code is required for reconnect.  Every vDC
and device declared before `host.start()` is automatically presented
to each new session.
```

Append a new subsection immediately after that paragraph (before the `---` separator):

```markdown
### 2.6 On-demand re-announcement (`scanDevices`)

When a user clicks **"Re-register devices"** in the dSS configurator, the
vdSM sends a `scanDevices` GenericRequest to the vDC host.  The request
targets a specific vDC dSUID and asks the vDC to re-send its full
announcement.

pydsvdcapi handles this automatically:

1. Resets the announcement flags for the addressed vDC and all its devices.
2. Re-sends `VDC_SEND_ANNOUNCE_VDC` for the vDC.
3. Re-sends `VDC_SEND_ANNOUNCE_DEVICE` for every device in the vDC.

If the dSUID in the request matches the **vDC host** dSUID (rather than a
specific vDC), all registered vDCs and their devices are re-announced.

> **Version suffix:** The vdSM may send `scanDevices/6` (or another
> version number) rather than the bare `scanDevices`.  pydsvdcapi strips
> the suffix before dispatch, so all firmware versions are supported.
```

- [ ] **Step 2: Run the full test suite**

```
cd /home/arne/Development/pyDSvDCAPI/pyDSvDCAPI
python -m pytest tests/ -q
```

Expected: all tests still pass.

- [ ] **Step 3: Commit**

```bash
git add docs/vdc-host-behavior.md
git commit -m "docs: document scanDevices GenericRequest re-announcement behaviour"
```
