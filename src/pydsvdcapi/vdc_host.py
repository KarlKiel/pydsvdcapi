"""vDC Host — top-level entity of a virtualDC host.

A :class:`VdcHost` represents the vDC host in the digitalSTROM system.
It holds the *common properties* required by every addressable entity,
provides DNS-SD (mDNS / Bonjour / Avahi) service announcement via the
``zeroconf`` library, and runs an asyncio TCP server that accepts
incoming vdSM connections.

Usage example::

    import asyncio
    from pydsvdcapi import VdcHost

    host = VdcHost(
        model="My Smart Gateway",
        name="Living Room Gateway",
    )

    async def main():
        await host.start()  # starts TCP server + DNS-SD announce
        try:
            await asyncio.Event().wait()  # run forever
        finally:
            await host.stop()

    asyncio.run(main())
"""

from __future__ import annotations

import asyncio
import logging
import platform
import socket
import threading
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from typing import Any, ClassVar

from zeroconf import ServiceInfo
from zeroconf.asyncio import AsyncZeroconf

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.connection import VdcConnection
from pydsvdcapi.dsuid import DsUid, DsUidNamespace
from pydsvdcapi.persistence import PropertyStore
from pydsvdcapi.property_handling import (
    build_get_property_response,
    elements_to_dict,
    expand_setproperty_wildcards,
)
from pydsvdcapi.session import MessageCallback, VdcSession
from pydsvdcapi.vdc import Vdc

#: Callback invoked when the vdSM requests device removal (§6.3).
#: Receives the dSUID string of the device to remove.
#: Return ``True`` to allow removal, ``False`` to reject it
#: (``ERR_FORBIDDEN``).  When no callback is set, removal is
#: always accepted.
RemoveCallback = Callable[[str], Awaitable[bool]]

#: Callback invoked when the vdSM requests identification of the
#: **vDC host device** itself (§7.4.5 via GenericRequest).
#: Receives the dSUID string of the addressed vDC.  Should
#: trigger a visual/acoustic signal on the platform hardware.
IdentifyCallback = Callable[[str], Awaitable[None]]

#: Callback for the ``pair`` GenericRequest method (§7.4.1).
#: ``(dsuid, establish, timeout, params) -> None``
PairCallback = Callable[[str, bool, int, dict[str, Any]], Awaitable[None]]

#: Callback for the ``authenticate`` GenericRequest method (§7.4.2).
#: ``(dsuid, auth_data, auth_scope, params) -> None``
AuthenticateCallback = Callable[[str, str, str, dict[str, Any]], Awaitable[None]]

#: Callback for the ``firmwareUpgrade`` GenericRequest method (§7.4.3).
#: ``(dsuid, check_only, clear_settings, params) -> None``
FirmwareUpgradeCallback = Callable[[str, bool, bool, dict[str, Any]], Awaitable[None]]

#: Callback for the ``setConfiguration`` GenericRequest method (§7.4.4).
#: ``(dsuid, config_id, params) -> None``
SetConfigurationCallback = Callable[[str, str, dict[str, Any]], Awaitable[None]]

#: Callback invoked when the vdSM TCP connection is lost unexpectedly.
#: Receives the :class:`VdcHost` instance and the exception that caused
#: the disconnect (or ``None`` for a clean EOF / bye).
#: Not called when :meth:`VdcHost.stop` initiated the disconnect.
DisconnectCallback = Callable[["VdcHost", Exception | None], Awaitable[None]]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default TCP port for the vDC host socket (as per the documentation).
DEFAULT_VDC_PORT: int = 8444

#: DNS-SD service type for vDC hosts.
VDC_SERVICE_TYPE: str = "_ds-vdc._tcp.local."

#: Entity type string for a vDC host (common property ``type``).
ENTITY_TYPE_VDC_HOST: str = "vDChost"

#: Debounce delay for auto-save in seconds.  When a tracked property
#: changes, the save is scheduled after this delay.  Subsequent changes
#: within the window reset the timer so that rapid edits result in a
#: single write.
AUTO_SAVE_DELAY: float = 1.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_default_mac() -> str:
    """Return the MAC address of the primary network interface.

    Falls back to a deterministic pseudo-MAC derived from the hostname
    when no real MAC address can be obtained.
    """
    import uuid as _uuid

    node = _uuid.getnode()
    # uuid.getnode() returns a random MAC with bit 0 set when it cannot
    # determine the real hardware address.  Bit 0 of the first octet
    # being 1 indicates a multicast / locally administered address.
    mac_bytes = node.to_bytes(6, "big")
    return ":".join(f"{b:02X}" for b in mac_bytes)


def _get_hostname() -> str:
    """Return the hostname of this machine."""
    return platform.node() or socket.gethostname()


# ---------------------------------------------------------------------------
# VdcHost
# ---------------------------------------------------------------------------


class VdcHost:
    """Represents a digitalSTROM vDC host and its common properties.

    A vDC host is the top-level addressable entity.  It provides a TCP
    server socket that a vdSM connects to, and announces itself via
    DNS-SD so that vdSMs can discover it automatically.

    All common properties (as defined in the *vDC API Properties —
    Common Properties* document) are available as regular Python
    attributes.  Properties that can be derived automatically (dSUID,
    ``hardwareGuid``, ``displayId``, …) are computed on first access
    unless explicitly set by the caller.

    **Auto-save:** When a ``state_path`` is configured, any change to a
    tracked property (e.g. ``name``, ``model``, ``vendor_name``, …)
    automatically triggers a debounced save.  The delay is controlled
    by :data:`AUTO_SAVE_DELAY` (default 1 s).  Rapid successive changes
    are coalesced into a single write.  Call :meth:`flush` to force an
    immediate save of pending changes (e.g. before shutdown).

    Parameters
    ----------
    mac:
        MAC address of the host hardware
        (e.g. ``"AA:BB:CC:DD:EE:FF"``).  Used to derive the dSUID
        and ``hardwareGuid``.  Auto-detected when omitted.
    port:
        TCP port for the vDC host socket.  Defaults to **8444**.
    dsuid:
        Explicit dSUID.  When omitted the dSUID is derived from
        *mac* using :pyfunc:`DsUid.from_name_in_space` with the
        well-known vDC host namespace.
    name:
        User-facing name for the host.  Defaults to
        ``"vDC host on <hostname>"``.
    model:
        Human-readable model description.  Defaults to
        ``"pydsvdcapi vDC host"``.
    model_version:
        Model / firmware version string.
    model_uid:
        System-unique ID for the functional model.  When omitted a
        deterministic value is derived from *model*.
    hardware_version:
        Human-readable hardware version string.
    hardware_guid:
        Native hardware GUID (``"macaddress:XX:XX:…"``).  Derived
        from *mac* when omitted.
    hardware_model_guid:
        Native hardware model GUID.
    vendor_name:
        Human-readable vendor name.
    vendor_guid:
        Globally unique vendor identifier.
    oem_guid:
        OEM product GUID.
    oem_model_guid:
        OEM product-model GUID.
    config_url:
        URL to the device's web configuration interface.
    device_icon_16:
        16×16 PNG icon as ``bytes``.
    device_icon_name:
        Filename-safe icon identifier for caching.
    state_path:
        Path to the YAML file used for persisting the property tree.
        When given, the host will attempt to restore its state on
        construction and can be asked to :meth:`save` at any time.
        When omitted, persistence is disabled.
    """

    #: Attribute names whose mutation triggers a debounced auto-save.
    _TRACKED_ATTRS: ClassVar[frozenset] = frozenset(
        {
            "name",
            "model",
            "model_version",
            "model_uid",
            "hardware_version",
            "hardware_guid",
            "hardware_model_guid",
            "vendor_name",
            "vendor_guid",
            "oem_guid",
            "oem_model_guid",
            "config_url",
            "device_icon_name",
        }
    )

    # ---- attribute change tracking -----------------------------------

    def __setattr__(self, name: str, value: object) -> None:
        """Set an attribute and schedule an auto-save when appropriate.

        Only attributes listed in :attr:`_TRACKED_ATTRS` are monitored.
        Auto-save is suppressed during ``__init__`` and :meth:`load` to
        avoid redundant writes.
        """
        super().__setattr__(name, value)
        if name in self._TRACKED_ATTRS and getattr(self, "_auto_save_enabled", False):
            self._schedule_auto_save()

    def __init__(
        self,
        *,
        mac: str | None = None,
        port: int = DEFAULT_VDC_PORT,
        dsuid: DsUid | None = None,
        name: str | None = None,
        model: str = "pydsvdcapi vDC host",
        model_version: str | None = None,
        model_uid: str | None = None,
        hardware_version: str | None = None,
        hardware_guid: str | None = None,
        hardware_model_guid: str | None = None,
        vendor_name: str | None = None,
        vendor_guid: str | None = None,
        oem_guid: str | None = None,
        oem_model_guid: str | None = None,
        config_url: str | None = None,
        device_icon_16: bytes | None = None,
        device_icon_name: str | None = None,
        state_path: str | Path | None = None,
    ) -> None:
        # --- persistence ----------------------------------------------
        self._store: PropertyStore | None = (
            PropertyStore(state_path) if state_path else None
        )

        # --- try restoring from persisted state -----------------------
        restored = self._store.load() if self._store else None
        host_state: dict[str, Any] = restored.get("vdcHost", {}) if restored else {}

        # --- network --------------------------------------------------
        self._mac: str = mac or host_state.get("mac") or _get_default_mac()
        self._port: int = (
            port if port != DEFAULT_VDC_PORT else host_state.get("port", port)
        )

        # --- identity -------------------------------------------------
        if dsuid is not None:
            self._dsuid = dsuid
        elif "dSUID" in host_state:
            self._dsuid = DsUid.from_string(host_state["dSUID"])
        else:
            self._dsuid = self._derive_dsuid(self._mac)

        # --- common properties ----------------------------------------
        self.name: str = (
            name or host_state.get("name") or f"vDC host on {_get_hostname()}"
        )
        self.model: str = (
            model if model != "pydsvdcapi vDC host" else host_state.get("model", model)
        )
        self.model_version: str | None = model_version or host_state.get("modelVersion")
        self.model_uid: str = (
            model_uid
            or host_state.get("modelUID")
            or self._derive_model_uid(self.model)
        )
        self.hardware_version: str | None = hardware_version or host_state.get(
            "hardwareVersion"
        )
        self.hardware_guid: str = (
            hardware_guid or host_state.get("hardwareGuid") or f"macaddress:{self._mac}"
        )
        self.hardware_model_guid: str | None = hardware_model_guid or host_state.get(
            "hardwareModelGuid"
        )
        self.vendor_name: str | None = vendor_name or host_state.get("vendorName")
        self.vendor_guid: str | None = vendor_guid or host_state.get("vendorGuid")
        self.oem_guid: str | None = oem_guid or host_state.get("oemGuid")
        self.oem_model_guid: str | None = oem_model_guid or host_state.get(
            "oemModelGuid"
        )
        self.config_url: str | None = config_url or host_state.get("configURL")
        self.device_icon_16: bytes | None = device_icon_16
        self.device_icon_name: str | None = device_icon_name or host_state.get(
            "deviceIconName"
        )

        # --- runtime state --------------------------------------------
        self._active: bool = True
        self._zeroconf: AsyncZeroconf | None = None
        self._service_info: ServiceInfo | None = None

        # --- TCP server / session state --------------------------------
        self._server: asyncio.AbstractServer | None = None
        self._session: VdcSession | None = None
        self._session_task: asyncio.Task | None = None
        self._on_message: MessageCallback | None = None
        self._on_remove: RemoveCallback | None = None
        self._on_identify: IdentifyCallback | None = None
        self._on_pair: PairCallback | None = None
        self._on_authenticate: AuthenticateCallback | None = None
        self._on_firmware_upgrade: FirmwareUpgradeCallback | None = None
        self._on_set_configuration: SetConfigurationCallback | None = None
        self._on_disconnect: DisconnectCallback | None = None
        self._stopping: bool = False

        # --- vDC registry ---------------------------------------------
        self._vdcs: dict[str, Vdc] = {}  # keyed by dSUID string

        # --- pending vanish -------------------------------------------
        self._pending_vanish: set[str] = set()

        # --- auto-save ------------------------------------------------
        self._save_timer: threading.Timer | None = None
        self._auto_save_enabled: bool = self._store is not None

        # --- restore vDCs from persisted state ------------------------
        if host_state.get("vdcs"):
            for vdc_state in host_state["vdcs"]:
                impl_id = vdc_state.get("implementationId")
                if impl_id:
                    vdc = Vdc(
                        host=self,
                        implementation_id=impl_id,
                        name=vdc_state.get("name") or impl_id,
                        model=vdc_state.get("model") or "Restored vDC",
                    )
                    vdc._apply_state(vdc_state)
                    self._vdcs[str(vdc.dsuid)] = vdc

        # Schedule an initial save so that the constructed state
        # (which may include defaults and derived values) is persisted.
        if self._auto_save_enabled:
            self._schedule_auto_save()

    # ---- derived / computed properties --------------------------------

    @staticmethod
    def _derive_dsuid(mac: str) -> DsUid:
        """Derive a vDC-host dSUID from a MAC address.

        Uses UUIDv5 hashing with the well-known vDC namespace, which
        is the documented method for generating a vDC host dSUID from
        the hardware's MAC address.
        """
        return DsUid.from_vdc_mac(mac)

    @staticmethod
    def _derive_model_uid(model: str) -> str:
        """Derive a deterministic ``modelUID`` from the model name.

        Uses UUIDv5 in the vDC namespace so that identical model names
        always produce the same ``modelUID``.
        """
        uid = DsUid.from_name_in_space(model, DsUidNamespace.VDC)
        return str(uid)

    # ---- read-only accessors -----------------------------------------

    @property
    def dsuid(self) -> DsUid:
        """The dSUID of this vDC host (read-only)."""
        return self._dsuid

    @property
    def display_id(self) -> str:
        """Human-readable identification of the vDC host.

        Returns the canonical hex representation of the dSUID, which
        serves as a readable identifier.
        """
        return str(self._dsuid)

    @property
    def entity_type(self) -> str:
        """Entity type string (always ``"vDChost"``)."""
        return ENTITY_TYPE_VDC_HOST

    @property
    def mac(self) -> str:
        """The MAC address associated with this host."""
        return self._mac

    @property
    def port(self) -> int:
        """The TCP port for the vDC host socket."""
        return self._port

    @property
    def active(self) -> bool:
        """Whether the vDC host is currently active / operational."""
        return self._active

    @active.setter
    def active(self, value: bool) -> None:
        self._active = bool(value)

    # ---- common-property dict ----------------------------------------

    def get_properties(self) -> dict:
        """Return all common properties as a flat dictionary.

        Keys match the property names from the vDC API specification.
        ``None`` values indicate properties that are not set.
        """
        return {
            "dSUID": str(self._dsuid),
            "displayId": self.display_id,
            "type": self.entity_type,
            "model": self.model,
            "modelVersion": self.model_version,
            "modelUID": self.model_uid,
            "hardwareVersion": self.hardware_version,
            "hardwareGuid": self.hardware_guid,
            "hardwareModelGuid": self.hardware_model_guid,
            "vendorName": self.vendor_name,
            "vendorGuid": self.vendor_guid,
            "oemGuid": self.oem_guid,
            "oemModelGuid": self.oem_model_guid,
            "configURL": self.config_url,
            "deviceIcon16": self.device_icon_16,
            "deviceIconName": self.device_icon_name,
            "name": self.name,
            "active": self._active,
        }

    # ---- vDC management -----------------------------------------------

    def add_vdc(self, vdc: Vdc) -> None:
        """Register a :class:`Vdc` with this host.

        The vDC is stored in an internal registry keyed by its dSUID.
        Adding a vDC with a dSUID that already exists replaces the
        previous entry.  If auto-save is enabled, a save is scheduled.

        Parameters
        ----------
        vdc:
            The :class:`Vdc` instance to register.
        """
        key = str(vdc.dsuid)
        self._vdcs[key] = vdc
        logger.info("Registered vDC '%s' (dSUID %s)", vdc.name, key)
        if self._auto_save_enabled:
            self._schedule_auto_save()

    def remove_vdc(self, dsuid: DsUid) -> Vdc | None:
        """Remove a registered vDC by its dSUID.

        Returns the removed :class:`Vdc` or ``None`` if no vDC with
        the given dSUID was registered.
        """
        key = str(dsuid)
        vdc = self._vdcs.pop(key, None)
        if vdc is not None:
            logger.info("Removed vDC '%s' (dSUID %s)", vdc.name, key)
            # Collect the vDC dSUID and all Vdsd dSUIDs.  Device base
            # dSUIDs are not tracked by the vdSM as separate addressable
            # entities, so only Vdsd dSUIDs need an explicit vanish.
            dsuids: set[str] = {key}
            for device in vdc.devices.values():
                for vdsd in device.vdsds.values():
                    dsuids.add(str(vdsd.dsuid))
            self._add_pending_vanish(dsuids)  # also schedules auto-save
        return vdc

    def get_vdc(self, dsuid: DsUid) -> Vdc | None:
        """Look up a registered vDC by its dSUID.

        Returns ``None`` if no vDC is registered with that dSUID.
        """
        return self._vdcs.get(str(dsuid))

    @property
    def vdcs(self) -> dict[str, Vdc]:
        """A read-only view of all registered vDCs (keyed by dSUID)."""
        return dict(self._vdcs)

    async def announce_vdcs(self) -> int:
        """Announce all registered vDCs to the connected vdSM.

        This should be called after the session hello handshake
        completes, before announcing any devices.

        Returns
        -------
        int
            The number of vDCs successfully announced.

        Raises
        ------
        ConnectionError
            If there is no active session.
        """
        session = self._session
        if session is None or not session.is_active:
            raise ConnectionError("Cannot announce vDCs — no active session")

        announced_count = 0
        for vdc in self._vdcs.values():
            try:
                success = await vdc.announce(session)
                if success:
                    announced_count += 1
            except Exception:  # noqa: BLE001
                logger.exception("Failed to announce vDC '%s'", vdc.name)

        logger.info(
            "Announced %d/%d vDCs",
            announced_count,
            len(self._vdcs),
        )
        return announced_count

    # ---- property tree (for persistence) -----------------------------

    def get_property_tree(self) -> dict[str, Any]:
        """Return the full property tree suitable for YAML persistence.

        The structure is::

            vdcHost:
              dSUID: "..."
              mac: "AA:BB:CC:DD:EE:FF"
              port: 8444
              name: "..."
              model: "..."
              ...
              vdcs:
                - dSUID: "..."
                  implementationId: "x-company-light"
                  ...
        """
        host_node: dict[str, Any] = {
            "dSUID": str(self._dsuid),
            "mac": self._mac,
            "port": self._port,
            "name": self.name,
            "model": self.model,
            "modelVersion": self.model_version,
            "modelUID": self.model_uid,
            "hardwareVersion": self.hardware_version,
            "hardwareGuid": self.hardware_guid,
            "hardwareModelGuid": self.hardware_model_guid,
            "vendorName": self.vendor_name,
            "vendorGuid": self.vendor_guid,
            "oemGuid": self.oem_guid,
            "oemModelGuid": self.oem_model_guid,
            "configURL": self.config_url,
            "deviceIconName": self.device_icon_name,
        }

        if self._vdcs:
            host_node["vdcs"] = [vdc.get_property_tree() for vdc in self._vdcs.values()]

        if self._pending_vanish:
            host_node["pendingVanish"] = sorted(self._pending_vanish)

        return {"vdcHost": host_node}

    # ---- persistence -------------------------------------------------

    def _add_pending_vanish(self, dsuids: Iterable[str]) -> None:
        """Track dSUIDs that must be vanished on the next session.

        Called when a vDC or device is removed while no session is active.
        The set is persisted in YAML so a restart does not lose the list.
        """
        self._pending_vanish.update(dsuids)
        if self._auto_save_enabled:
            self._schedule_auto_save()

    def save(self) -> None:
        """Persist the current property tree to the YAML state file.

        Does nothing if no ``state_path`` was provided at construction.
        Any pending debounced auto-save is cancelled since this manual
        save already captures the current state.
        """
        self._cancel_auto_save()
        if self._store is None:
            logger.debug("No state_path configured — skipping save.")
            return
        self._store.save(self.get_property_tree())

    # ---- auto-save internals ----------------------------------------

    def _schedule_auto_save(self) -> None:
        """Schedule a debounced save after :data:`AUTO_SAVE_DELAY` seconds.

        If a timer is already running it is cancelled and restarted so
        that rapid successive changes are coalesced into one write.
        """
        if self._save_timer is not None:
            self._save_timer.cancel()
        timer = threading.Timer(AUTO_SAVE_DELAY, self._do_auto_save)
        timer.daemon = True
        timer.start()
        self._save_timer = timer

    def _cancel_auto_save(self) -> None:
        """Cancel a pending auto-save timer without performing a save."""
        timer = getattr(self, "_save_timer", None)
        if timer is not None:
            timer.cancel()
            self._save_timer = None

    def _do_auto_save(self) -> None:
        """Execute the auto-save (called by the debounce timer thread)."""
        self._save_timer = None
        logger.debug("Auto-saving property tree.")
        if self._store is not None:
            self._store.save(self.get_property_tree())

    def flush(self) -> None:
        """Save immediately if there is a pending auto-save.

        This cancels the debounce timer and performs the save
        synchronously.  Call this before shutdown to ensure no
        property changes are lost.
        """
        if self._save_timer is not None:
            self._save_timer.cancel()
            self._save_timer = None
            self.save()

    def load(self) -> bool:
        """Reload properties from the persisted YAML state file.

        Returns ``True`` if state was successfully restored, ``False``
        otherwise.  Does nothing if no ``state_path`` was provided.

        Auto-save is suspended while the restored values are applied so
        that loading does not trigger a redundant write.
        """
        if self._store is None:
            return False

        tree = self._store.load()
        if tree is None:
            return False

        host_state = tree.get("vdcHost", {})
        if not host_state:
            return False

        # Suspend auto-save while applying restored state.
        prev = self._auto_save_enabled
        self._auto_save_enabled = False
        try:
            self._apply_state(host_state)
        finally:
            self._auto_save_enabled = prev
        return True

    def _apply_state(self, state: dict[str, Any]) -> None:
        """Apply a persisted state dict to this host's properties.

        Also restores vDC properties when ``vdcs`` entries match
        already-registered vDCs by dSUID or implementationId.
        """
        if "dSUID" in state:
            self._dsuid = DsUid.from_string(state["dSUID"])
        if "mac" in state:
            self._mac = state["mac"]
        if "port" in state:
            self._port = state["port"]
        if "name" in state:
            self.name = state["name"]
        if "model" in state:
            self.model = state["model"]
        if "modelVersion" in state:
            self.model_version = state["modelVersion"]
        if "modelUID" in state:
            self.model_uid = state["modelUID"]
        if "hardwareVersion" in state:
            self.hardware_version = state["hardwareVersion"]
        if "hardwareGuid" in state:
            self.hardware_guid = state["hardwareGuid"]
        if "hardwareModelGuid" in state:
            self.hardware_model_guid = state["hardwareModelGuid"]
        if "vendorName" in state:
            self.vendor_name = state["vendorName"]
        if "vendorGuid" in state:
            self.vendor_guid = state["vendorGuid"]
        if "oemGuid" in state:
            self.oem_guid = state["oemGuid"]
        if "oemModelGuid" in state:
            self.oem_model_guid = state["oemModelGuid"]
        if "configURL" in state:
            self.config_url = state["configURL"]
        if "deviceIconName" in state:
            self.device_icon_name = state["deviceIconName"]

        if "pendingVanish" in state:
            self._pending_vanish.update(state["pendingVanish"])

        # Restore vDC properties from persisted state.
        if "vdcs" in state:
            for vdc_state in state["vdcs"]:
                vdc = self._find_vdc_for_state(vdc_state)
                if vdc is not None:
                    vdc._apply_state(vdc_state)

    def _find_vdc_for_state(self, vdc_state: dict[str, Any]) -> Vdc | None:
        """Find a registered vDC matching *vdc_state*.

        Matches by dSUID first, then by ``implementationId`` as a
        fallback.
        """
        # Match by dSUID.
        dsuid_str = vdc_state.get("dSUID")
        if dsuid_str and dsuid_str in self._vdcs:
            return self._vdcs[dsuid_str]

        # Fallback — match by implementationId.
        impl_id = vdc_state.get("implementationId")
        if impl_id:
            for vdc in self._vdcs.values():
                if vdc.implementation_id == impl_id:
                    return vdc

        return None

    # ---- DNS-SD announcement -----------------------------------------

    async def announce(self) -> None:
        """Announce this vDC host on the local network via DNS-SD.

        Creates a ``_ds-vdc._tcp`` service entry so that vdSMs can
        discover this host automatically.

        Calling :meth:`announce` when already announced is a no-op.

        Raises
        ------
        RuntimeError
            If the service could not be registered.
        """
        if self._zeroconf is not None:
            logger.debug("Already announced — skipping.")
            return

        hostname = _get_hostname()
        service_name = f"{self.name} on {hostname}"

        # Build the ServiceInfo.  Zeroconf requires the fully-qualified
        # service type (``_ds-vdc._tcp.local.``).
        self._service_info = ServiceInfo(
            type_=VDC_SERVICE_TYPE,
            name=f"{service_name}.{VDC_SERVICE_TYPE}",
            port=self._port,
            properties={
                "dSUID": str(self._dsuid),
            },
            server=f"{hostname}.local.",
        )

        self._zeroconf = AsyncZeroconf()
        await self._zeroconf.async_register_service(self._service_info)
        logger.info(
            "Announced vDC host '%s' on port %d (dSUID %s)",
            service_name,
            self._port,
            self._dsuid,
        )

    async def unannounce(self) -> None:
        """Remove the DNS-SD announcement and release resources.

        Calling :meth:`unannounce` when not announced is a no-op.
        """
        if self._zeroconf is None:
            return

        if self._service_info is not None:
            await self._zeroconf.async_unregister_service(self._service_info)
            logger.info("Unannounced vDC host service.")

        await self._zeroconf.async_close()
        self._zeroconf = None
        self._service_info = None

    @property
    def is_announced(self) -> bool:
        """``True`` if the DNS-SD service is currently registered."""
        return self._zeroconf is not None

    # ---- TCP server --------------------------------------------------

    async def start(
        self,
        *,
        on_message: MessageCallback | None = None,
        on_remove: RemoveCallback | None = None,
        on_identify: IdentifyCallback | None = None,
        on_pair: PairCallback | None = None,
        on_authenticate: AuthenticateCallback | None = None,
        on_firmware_upgrade: FirmwareUpgradeCallback | None = None,
        on_set_configuration: SetConfigurationCallback | None = None,
        on_disconnect: DisconnectCallback | None = None,
        announce: bool = True,
        bind_address: str = "0.0.0.0",
    ) -> None:
        """Start the TCP server (and optionally DNS-SD announcement).

        Parameters
        ----------
        on_message:
            Async callback for messages that are not handled internally
            (i.e. not ``hello``, ``ping``, or ``bye``).  See
            :data:`~pydsvdcapi.session.MessageCallback`.
        on_remove:
            Optional async callback invoked when the vdSM requests
            device removal (§6.3).  Receives the dSUID string.  Return
            ``True`` to allow, ``False`` to reject
            (``ERR_FORBIDDEN``).  When ``None``, removal is always
            accepted.
        on_identify:
            Optional async callback invoked when the vdSM requests
            identification of the vDC host platform (§7.4.5 via
            GenericRequest).  Receives the dSUID string.  For
            **device-level** identification (§7.3.7), set
            ``Vdsd.on_identify`` on each device instead.
        on_pair:
            Optional async callback for the ``pair`` GenericRequest
            (§7.4.1 learn-in/learn-out).  Signature:
            ``(dsuid, establish, timeout, params) -> None``.
        on_authenticate:
            Optional async callback for the ``authenticate``
            GenericRequest (§7.4.2).  Signature:
            ``(dsuid, auth_data, auth_scope, params) -> None``.
        on_firmware_upgrade:
            Optional async callback for the ``firmwareUpgrade``
            GenericRequest (§7.4.3).  Signature:
            ``(dsuid, check_only, clear_settings, params) -> None``.
        on_set_configuration:
            Optional async callback for the ``setConfiguration``
            GenericRequest (§7.4.4).  Signature:
            ``(dsuid, config_id, params) -> None``.
        on_disconnect:
            Optional async callback invoked when the vdSM TCP connection
            is lost unexpectedly (network drop, dSS restart, etc.).
            Receives ``(host, reason)`` where *reason* is the exception
            that caused the disconnect, or ``None`` for a clean EOF / bye.
            **Not called** when :meth:`stop` initiated the disconnect.
        announce:
            If ``True`` (default) the DNS-SD service is announced
            automatically after the server starts listening.
        bind_address:
            The network address to bind to.  Defaults to ``"0.0.0.0"``
            (all IPv4 interfaces).
        """
        if self._server is not None:
            logger.debug("TCP server already running — skipping start.")
            return

        self._on_message = on_message
        self._on_remove = on_remove
        self._on_identify = on_identify
        self._on_pair = on_pair
        self._on_authenticate = on_authenticate
        self._on_firmware_upgrade = on_firmware_upgrade
        self._on_set_configuration = on_set_configuration
        self._on_disconnect = on_disconnect

        self._server = await asyncio.start_server(
            self._handle_new_connection,
            host=bind_address,
            port=self._port,
        )

        # Determine the actual port (useful when port=0 for random).
        socks = self._server.sockets
        if socks:
            actual_port = socks[0].getsockname()[1]
            if actual_port != self._port:
                self._port = actual_port

        logger.info(
            "TCP server listening on port %d (dSUID %s)",
            self._port,
            self._dsuid,
        )

        if announce:
            await self.announce()

    async def stop(self) -> None:
        """Stop the TCP server, close the active session, and unannounce.

        The shutdown sequence is ordered to minimise spurious reconnect
        attempts from the vdSM:

        1. **Flush** any pending auto-save so property changes are not
           lost.
        2. **Unannounce** the DNS-SD / Avahi service so the vdSM sees the
           service disappear *before* the TCP connection drops.
        3. **Close** the active session (TCP connection).
        4. **Stop** the TCP server.
        """
        # Flush any pending auto-save so no property changes are lost.
        self.flush()

        # Unannounce the DNS-SD service *before* dropping the TCP
        # connection.  This gives the vdSM's Avahi watcher a chance to
        # notice the service is gone so it does not immediately attempt
        # to reconnect to a dead port.
        await self.unannounce()

        # Close the active session.
        self._stopping = True
        try:
            await self._close_session()
        finally:
            self._stopping = False

        # Shut down the TCP server.
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("TCP server stopped")

    @property
    def is_serving(self) -> bool:
        """``True`` if the TCP server is running."""
        return self._server is not None and self._server.is_serving()

    @property
    def session(self) -> VdcSession | None:
        """The currently active session, if any."""
        return self._session

    # ---- connection handling (private) --------------------------------

    async def _handle_new_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Callback invoked by :func:`asyncio.start_server` for each
        new incoming TCP connection."""
        conn = VdcConnection(reader, writer)
        logger.info("New TCP connection from %s", conn.peername)

        # Only one session at a time.  Close the previous session if one
        # exists — the spec says a new Hello implicitly terminates the
        # old session.  We are resilient and allow reconnects.
        await self._close_session()

        session = VdcSession(
            connection=conn,
            host_dsuid=str(self._dsuid),
            on_message=self._dispatch_message,
            on_hello=self._on_session_ready,
        )
        self._session = session

        # Run the session in-line (the start_server callback is already
        # running in its own task per connection).
        await self._run_session(session)

    async def _run_session(self, session: VdcSession) -> None:
        """Run a session and clean up when it ends."""
        try:
            await session.run()
        except Exception:  # noqa: BLE001
            logger.exception("Session error")
        finally:
            if self._session is session:
                self._session = None
                self._session_task = None
            # Reset announcement state for all vDCs so they will be
            # re-announced on the next session.
            for vdc in self._vdcs.values():
                vdc.reset_announcement()
            logger.info("Session with %s cleaned up", session.vdsm_dsuid)
            if not self._stopping and self._on_disconnect is not None:
                try:
                    await self._on_disconnect(self, session.disconnect_reason)
                except Exception:  # noqa: BLE001
                    logger.exception("on_disconnect callback raised")

    async def _close_session(self) -> None:
        """Close the active session if there is one."""
        if self._session is not None:
            logger.info("Closing existing session with %s", self._session.vdsm_dsuid)
            await self._session.close()
            self._session = None
            self._session_task = None

    async def _flush_pending_vanish(self, session: VdcSession) -> None:
        """Send VDC_SEND_VANISH for every dSUID in _pending_vanish, then clear.

        Runs at the start of _on_session_ready() so the vdSM processes
        offline deletions before receiving re-announcement of survivors.
        Failed sends are logged but do not prevent the set from being
        cleared; the flush is best-effort to avoid blocking session start.
        """
        if not self._pending_vanish:
            return
        logger.info("Flushing %d pending vanish(es)", len(self._pending_vanish))
        for dsuid_str in list(self._pending_vanish):
            msg = pb.Message()
            msg.type = pb.VDC_SEND_VANISH
            msg.vdc_send_vanish.dSUID = dsuid_str
            try:
                await session.send_notification(msg)
                logger.debug("Sent pending vanish for %s", dsuid_str)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to send pending vanish for %s", dsuid_str)
        self._pending_vanish.clear()
        if self._auto_save_enabled:
            self._schedule_auto_save()

    async def _on_session_ready(self, session: VdcSession) -> None:
        """Auto-announce all registered vDCs and devices on *session*.

        Called by the session's ``on_hello`` hook after the hello
        handshake completes.  This ensures that whenever a vdSM
        (re-)connects, every vDC and device is properly announced on
        the new session — without requiring the caller to re-drive
        the announcement manually.
        """
        await self._flush_pending_vanish(session)
        logger.info(
            "Session ready — auto-announcing %d vDC(s)",
            len(self._vdcs),
        )
        for vdc in self._vdcs.values():
            try:
                success = await vdc.announce(session)
                if not success:
                    logger.warning(
                        "Auto-announce of vDC '%s' was rejected",
                        vdc.name,
                    )
                    continue
                announced = await vdc.announce_devices(session)
                logger.info(
                    "Auto-announced vDC '%s' with %d device(s)",
                    vdc.name,
                    announced,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Error during auto-announce of vDC '%s'", vdc.name)

    # ---- property access (internal message handling) -----------------

    async def _dispatch_message(
        self,
        session: VdcSession,
        msg: pb.Message,
    ) -> pb.Message | None:
        """Internal message handler installed on every session.

        Intercepts ``VDSM_REQUEST_GET_PROPERTY`` and
        ``VDSM_REQUEST_SET_PROPERTY`` and routes them to the
        addressed entity.  All other messages are forwarded to the
        user-supplied ``on_message`` callback.
        """
        msg_type = msg.type

        if msg_type == pb.VDSM_REQUEST_GET_PROPERTY:
            return self._handle_get_property(msg)

        if msg_type == pb.VDSM_REQUEST_SET_PROPERTY:
            return self._handle_set_property(msg)

        if msg_type == pb.VDSM_NOTIFICATION_SET_OUTPUT_CHANNEL_VALUE:
            await self._handle_set_output_channel_value(session, msg)
            return None

        if msg_type == pb.VDSM_NOTIFICATION_CALL_SCENE:
            await self._handle_call_scene(msg)
            return None

        if msg_type == pb.VDSM_NOTIFICATION_SAVE_SCENE:
            await self._handle_save_scene(msg)
            return None

        if msg_type == pb.VDSM_NOTIFICATION_UNDO_SCENE:
            await self._handle_undo_scene(msg)
            return None

        if msg_type == pb.VDSM_NOTIFICATION_SET_LOCAL_PRIO:
            await self._handle_set_local_priority(msg)
            return None

        if msg_type == pb.VDSM_NOTIFICATION_CALL_MIN_SCENE:
            await self._handle_call_min_scene(msg)
            return None

        if msg_type == pb.VDSM_NOTIFICATION_SET_CONTROL_VALUE:
            await self._handle_set_control_value(msg)
            return None

        if msg_type == pb.VDSM_NOTIFICATION_DIM_CHANNEL:
            await self._handle_dim_channel(msg)
            return None

        if msg_type == pb.VDSM_NOTIFICATION_IDENTIFY:
            await self._handle_identify(msg)
            return None

        if msg_type == pb.VDSM_REQUEST_GENERIC_REQUEST:
            return await self._handle_generic_request(session, msg)

        if msg_type == pb.VDSM_SEND_REMOVE:
            return await self._handle_remove(msg)

        # Delegate to the user callback.
        if self._on_message is not None:
            return await self._on_message(session, msg)
        return None

    def _resolve_entity(self, dsuid_str: str) -> dict[str, Any] | None:
        """Return ``(properties_dict, entity)`` for the entity with
        the given dSUID string, or ``None`` if not found."""
        # Normalise to upper-case — the vdSM may send lower-case hex.
        dsuid_str = dsuid_str.upper()
        if dsuid_str == str(self._dsuid):
            return self.get_properties()
        vdc = self._vdcs.get(dsuid_str)
        if vdc is not None:
            return vdc.get_properties()
        # Search for a vdSD across all vDCs.
        for vdc in self._vdcs.values():
            vdsd = vdc.get_vdsd_by_dsuid(DsUid.from_string(dsuid_str))
            if vdsd is not None:
                return vdsd.get_properties()
        return None

    def _handle_get_property(self, msg: pb.Message) -> pb.Message:
        """Handle a ``VDSM_REQUEST_GET_PROPERTY``."""
        target_dsuid = msg.vdsm_request_get_property.dSUID
        props = self._resolve_entity(target_dsuid)

        if props is None:
            logger.debug("getProperty for unknown dSUID %s", target_dsuid)
            resp = pb.Message()
            resp.type = pb.GENERIC_RESPONSE
            resp.message_id = msg.message_id
            resp.generic_response.code = pb.ERR_NOT_FOUND
            resp.generic_response.description = f"Entity {target_dsuid} not found"
            return resp

        query_names = [
            q.name or "<wildcard>" for q in msg.vdsm_request_get_property.query
        ]
        logger.debug(
            "getProperty for %s — %d query elements: %s",
            target_dsuid,
            len(msg.vdsm_request_get_property.query),
            query_names,
        )
        resp = build_get_property_response(msg, props)
        return resp

    def _handle_set_property(self, msg: pb.Message) -> pb.Message:
        """Handle a ``VDSM_REQUEST_SET_PROPERTY``."""
        # Normalise to upper-case — the vdSM may send lower-case hex.
        target_dsuid = msg.vdsm_request_set_property.dSUID.upper()
        incoming = elements_to_dict(msg.vdsm_request_set_property.properties)

        resp = pb.Message()
        resp.type = pb.GENERIC_RESPONSE
        resp.message_id = msg.message_id

        # Resolve the entity.
        if target_dsuid == str(self._dsuid):
            self._apply_set_property(incoming)
            resp.generic_response.code = pb.ERR_OK
            return resp

        vdc = self._vdcs.get(target_dsuid)
        if vdc is not None:
            self._apply_vdc_set_property(vdc, incoming)
            resp.generic_response.code = pb.ERR_OK
            return resp

        # Check for a vdSD across all vDCs.
        for vdc in self._vdcs.values():
            vdsd = vdc.get_vdsd_by_dsuid(DsUid.from_string(target_dsuid))
            if vdsd is not None:
                self._apply_vdsd_set_property(vdsd, incoming)
                resp.generic_response.code = pb.ERR_OK
                return resp

        resp.generic_response.code = pb.ERR_NOT_FOUND
        resp.generic_response.description = f"Entity {target_dsuid} not found"
        return resp

    def _apply_set_property(self, incoming: dict[str, Any]) -> None:
        """Apply writable properties to this host."""
        if "name" in incoming:
            self.name = incoming["name"]
            logger.info("Host name set to '%s'", self.name)

    def _apply_vdc_set_property(self, vdc: Vdc, incoming: dict[str, Any]) -> None:
        """Apply writable properties to a vDC."""
        if "name" in incoming:
            vdc.name = incoming["name"]
            logger.info("vDC '%s' name set to '%s'", vdc.dsuid, vdc.name)
        if "zoneID" in incoming and incoming["zoneID"] is not None:
            vdc.zone_id = int(incoming["zoneID"])
            logger.info("vDC '%s' zoneID set to %d", vdc.dsuid, vdc.zone_id)

    def _apply_vdsd_set_property(self, vdsd: Any, incoming: dict[str, Any]) -> None:
        """Apply writable properties to a vdSD.

        Supports wildcard expansion per §7.1.2: if a container property
        (e.g. ``buttonInputSettings``, ``scenes``) contains an
        empty-name entry (``""`` key from the protobuf wildcard), the
        value is applied to all existing items at that level.
        """
        if "name" in incoming:
            vdsd.name = incoming["name"]
            logger.info("vdSD '%s' name set to '%s'", vdsd.dsuid, vdsd.name)
        if "zoneID" in incoming and incoming["zoneID"] is not None:
            vdsd.zone_id = int(incoming["zoneID"])
            logger.info("vdSD '%s' zoneID set to %d", vdsd.dsuid, vdsd.zone_id)
        if "progMode" in incoming:
            val = incoming["progMode"]
            vdsd.prog_mode = bool(val) if val is not None else None
            logger.info("vdSD '%s' progMode set to %s", vdsd.dsuid, vdsd.prog_mode)
        # Button input settings (§4.2.2).
        if "buttonInputSettings" in incoming:
            btn_settings = incoming["buttonInputSettings"]
            if isinstance(btn_settings, dict):
                btn_settings = expand_setproperty_wildcards(
                    btn_settings,
                    vdsd._button_inputs.keys(),
                )
                for idx_str, settings in btn_settings.items():
                    if isinstance(settings, dict):
                        idx = int(idx_str)
                        btn = vdsd.get_button_input(idx)
                        if btn is not None:
                            btn.apply_settings(settings)
                            logger.info(
                                "vdSD '%s' buttonInputSettings[%d] updated",
                                vdsd.dsuid,
                                idx,
                            )
        # Binary input settings (§4.3.2).
        if "binaryInputSettings" in incoming:
            bi_settings = incoming["binaryInputSettings"]
            if isinstance(bi_settings, dict):
                bi_settings = expand_setproperty_wildcards(
                    bi_settings,
                    vdsd._binary_inputs.keys(),
                )
                for idx_str, settings in bi_settings.items():
                    if isinstance(settings, dict):
                        idx = int(idx_str)
                        bi = vdsd.get_binary_input(idx)
                        if bi is not None:
                            bi.apply_settings(settings)
                            logger.info(
                                "vdSD '%s' binaryInputSettings[%d] updated",
                                vdsd.dsuid,
                                idx,
                            )
        # Sensor input settings (§4.3.2).
        if "sensorSettings" in incoming:
            si_settings = incoming["sensorSettings"]
            if isinstance(si_settings, dict):
                si_settings = expand_setproperty_wildcards(
                    si_settings,
                    vdsd._sensor_inputs.keys(),
                )
                for idx_str, settings in si_settings.items():
                    if isinstance(settings, dict):
                        idx = int(idx_str)
                        si = vdsd.get_sensor_input(idx)
                        if si is not None:
                            si.apply_settings(settings)
                            logger.info(
                                "vdSD '%s' sensorSettings[%d] updated",
                                vdsd.dsuid,
                                idx,
                            )
        # Output settings (§4.8.2).
        if "outputSettings" in incoming:
            out_settings = incoming["outputSettings"]
            if isinstance(out_settings, dict):
                output = getattr(vdsd, "output", None)
                if output is not None:
                    output.apply_settings(out_settings)
                    logger.info(
                        "vdSD '%s' outputSettings updated",
                        vdsd.dsuid,
                    )
        # Output state (§4.8.3) — only localPriority is writable.
        if "outputState" in incoming:
            out_state = incoming["outputState"]
            if isinstance(out_state, dict):
                output = getattr(vdsd, "output", None)
                if output is not None:
                    output.apply_state(out_state)
                    logger.info(
                        "vdSD '%s' outputState updated",
                        vdsd.dsuid,
                    )
        # Custom actions (§4.5.3) — user-writable.
        if "customActions" in incoming:
            ca_data = incoming["customActions"]
            if isinstance(ca_data, dict):
                ca_data = expand_setproperty_wildcards(
                    ca_data,
                    vdsd._custom_actions.keys(),
                )
                for idx_str, settings in ca_data.items():
                    if isinstance(settings, dict):
                        idx = int(idx_str)
                        cust = vdsd.get_custom_action(idx)
                        if cust is not None:
                            cust.apply_settings(settings)
                            logger.info(
                                "vdSD '%s' customActions[%d] updated",
                                vdsd.dsuid,
                                idx,
                            )
        # Channel states (§4.9.3) — dSS sends this via setProperty when
        # the user or JSON API sets an output channel value directly
        # (setVdcDeviceOutputChannelValues path).  Each child element is
        # named by the channel name string (e.g. "brightness") and
        # contains a "value" child with the new double.
        if "channelStates" in incoming:
            ch_states = incoming["channelStates"]
            if isinstance(ch_states, dict):
                output = getattr(vdsd, "output", None)
                if output is not None:
                    for ch_name, ch_data in ch_states.items():
                        if not isinstance(ch_data, dict):
                            continue
                        new_val = ch_data.get("value")
                        if new_val is None:
                            continue
                        # Locate channel by name.
                        channel_obj = None
                        for ch in output.channels.values():
                            if ch.name == ch_name:
                                channel_obj = ch
                                break
                        if channel_obj is None:
                            logger.warning(
                                "setProperty channelStates: channel '%s' "
                                "not found on vdSD %s",
                                ch_name,
                                vdsd.dsuid,
                            )
                            continue
                        output.buffer_channel_value(channel_obj, float(new_val))
                        logger.debug(
                            "setProperty channelStates: vdSD %s ch='%s' "
                            "val=%s (buffered)",
                            vdsd.dsuid,
                            ch_name,
                            new_val,
                        )
                    # apply_pending_channels is async; schedule it.
                    import asyncio

                    asyncio.create_task(output.apply_pending_channels())
                    logger.info(
                        "vdSD '%s' channelStates updated via setProperty",
                        vdsd.dsuid,
                    )
        # Scene settings (§4.1.4 / §4.10).
        if "scenes" in incoming:
            scene_data = incoming["scenes"]
            if isinstance(scene_data, dict):
                output = getattr(vdsd, "output", None)
                if output is not None:
                    # Expand wildcards to all known scene numbers.
                    scene_data = expand_setproperty_wildcards(
                        scene_data,
                        output.scene_numbers,
                    )
                    output.apply_scenes(scene_data)
                    logger.info(
                        "vdSD '%s' scenes updated",
                        vdsd.dsuid,
                    )

    # ---- GenericRequest handler (§7.3.10+) -------------------------

    async def _handle_generic_request(
        self, session: VdcSession, msg: pb.Message
    ) -> pb.Message:
        """Handle ``VDSM_REQUEST_GENERIC_REQUEST`` messages.

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
        """
        req = msg.vdsm_request_generic_request
        # Strip optional API-version suffix, e.g. "scanDevices/6" → "scanDevices".
        method = req.methodname.split("/", 1)[0]
        dsuid_str = req.dSUID

        # Parse params PropertyElements into a flat dict.
        params_dict: dict[str, Any] = {}
        for elem in req.params:
            name = elem.name
            if elem.HasField("value"):
                pv = elem.value
                if pv.HasField("v_string"):
                    params_dict[name] = pv.v_string
                elif pv.HasField("v_double"):
                    params_dict[name] = pv.v_double
                elif pv.HasField("v_int64"):
                    params_dict[name] = pv.v_int64
                elif pv.HasField("v_uint64"):
                    params_dict[name] = pv.v_uint64
                elif pv.HasField("v_bool"):
                    params_dict[name] = pv.v_bool
                else:
                    params_dict[name] = None
            elif elem.elements:
                # Nested params — convert to dict via elements_to_dict.
                params_dict[name] = elements_to_dict(elem.elements)

        resp = pb.Message()
        resp.type = pb.GENERIC_RESPONSE
        resp.message_id = msg.message_id

        if method == "invokeDeviceAction":
            action_id = params_dict.get("id", "")
            # Remove 'id' from the params passed to the callback.
            action_params = {k: v for k, v in params_dict.items() if k != "id"}
            vdsd = self._find_vdsd_by_dsuid(dsuid_str)
            if vdsd is None:
                logger.warning(
                    "invokeDeviceAction: vdSD %s not found",
                    dsuid_str,
                )
                resp.generic_response.code = pb.ERR_NOT_FOUND
                resp.generic_response.description = f"Device {dsuid_str} not found"
                return resp

            try:
                await vdsd.invoke_action(action_id, action_params)
                resp.generic_response.code = pb.ERR_OK
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "invokeDeviceAction '%s' on vdSD %s failed",
                    action_id,
                    dsuid_str,
                )
                resp.generic_response.code = pb.ERR_NOT_IMPLEMENTED
                resp.generic_response.description = str(exc)
            return resp

        if method == "identify":
            # §7.4.5 — Identify vDC host device.
            logger.info(
                "GenericRequest identify for dSUID %s",
                dsuid_str,
            )
            if self._on_identify is not None:
                try:
                    await self._on_identify(dsuid_str)
                    resp.generic_response.code = pb.ERR_OK
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "on_identify callback raised for %s",
                        dsuid_str,
                    )
                    resp.generic_response.code = pb.ERR_NOT_IMPLEMENTED
                    resp.generic_response.description = str(exc)
            else:
                # No callback — acknowledge but do nothing.
                resp.generic_response.code = pb.ERR_OK
            return resp

        if method == "pair":
            # §7.4.1 — Learn-in / learn-out.
            if self._on_pair is not None:
                try:
                    await self._on_pair(
                        dsuid_str,
                        bool(params_dict.get("establish", True)),
                        int(params_dict.get("timeout", -1)),
                        {
                            k: v
                            for k, v in params_dict.items()
                            if k not in ("establish", "timeout")
                        },
                    )
                    resp.generic_response.code = pb.ERR_OK
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "on_pair callback raised for %s",
                        dsuid_str,
                    )
                    resp.generic_response.code = pb.ERR_NOT_IMPLEMENTED
                    resp.generic_response.description = str(exc)
            else:
                resp.generic_response.code = pb.ERR_NOT_IMPLEMENTED
                resp.generic_response.description = "pair: no callback registered"
            return resp

        if method == "authenticate":
            # §7.4.2 — Authenticate.
            if self._on_authenticate is not None:
                try:
                    await self._on_authenticate(
                        dsuid_str,
                        str(params_dict.get("authData", "")),
                        str(params_dict.get("authScope", "")),
                        {
                            k: v
                            for k, v in params_dict.items()
                            if k not in ("authData", "authScope")
                        },
                    )
                    resp.generic_response.code = pb.ERR_OK
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "on_authenticate callback raised for %s",
                        dsuid_str,
                    )
                    resp.generic_response.code = pb.ERR_NOT_IMPLEMENTED
                    resp.generic_response.description = str(exc)
            else:
                resp.generic_response.code = pb.ERR_NOT_IMPLEMENTED
                resp.generic_response.description = (
                    "authenticate: no callback registered"
                )
            return resp

        if method == "firmwareUpgrade":
            # §7.4.3 — Firmware upgrade.
            if self._on_firmware_upgrade is not None:
                try:
                    await self._on_firmware_upgrade(
                        dsuid_str,
                        bool(params_dict.get("checkonly", False)),
                        bool(params_dict.get("clearsettings", False)),
                        {
                            k: v
                            for k, v in params_dict.items()
                            if k not in ("checkonly", "clearsettings")
                        },
                    )
                    resp.generic_response.code = pb.ERR_OK
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "on_firmware_upgrade callback raised for %s",
                        dsuid_str,
                    )
                    resp.generic_response.code = pb.ERR_NOT_IMPLEMENTED
                    resp.generic_response.description = str(exc)
            else:
                resp.generic_response.code = pb.ERR_NOT_IMPLEMENTED
                resp.generic_response.description = (
                    "firmwareUpgrade: no callback registered"
                )
            return resp

        if method == "setConfiguration":
            # §7.4.4 — Change device configuration/profile.
            if self._on_set_configuration is not None:
                try:
                    await self._on_set_configuration(
                        dsuid_str,
                        str(params_dict.get("id", "")),
                        {k: v for k, v in params_dict.items() if k != "id"},
                    )
                    resp.generic_response.code = pb.ERR_OK
                except Exception as exc:  # noqa: BLE001
                    logger.exception(
                        "on_set_configuration callback raised for %s",
                        dsuid_str,
                    )
                    resp.generic_response.code = pb.ERR_NOT_IMPLEMENTED
                    resp.generic_response.description = str(exc)
            else:
                resp.generic_response.code = pb.ERR_NOT_IMPLEMENTED
                resp.generic_response.description = (
                    "setConfiguration: no callback registered"
                )
            return resp

        if method == "scanDevices":
            # Re-announce the addressed vDC and all its devices.
            # Matches "scanDevices" and versioned variants (version stripped above).
            #
            # IMPORTANT: the OK response must be sent to the vdSM BEFORE we
            # send any VDC_SEND_ANNOUNCE_* messages.  dSS will not respond to
            # our announce requests until it has received our scanDevices OK,
            # so doing the re-announcement inside the handler (before returning
            # resp) creates a deadlock that manifests as a 30-second timeout.
            # We therefore return OK immediately and re-announce in a
            # background task.
            dsuid_upper = dsuid_str.upper()
            if dsuid_upper in self._vdcs:
                vdcs_to_scan: list[Vdc] = [self._vdcs[dsuid_upper]]
            elif dsuid_upper == str(self._dsuid).upper():
                vdcs_to_scan = list(self._vdcs.values())
            else:
                resp.generic_response.code = pb.ERR_NOT_FOUND
                resp.generic_response.description = (
                    f"scanDevices: vDC {dsuid_str} not found"
                )
                return resp

            async def _do_scan(
                vdcs: list[Vdc],
                sess: VdcSession,
                target: str,
            ) -> None:
                for vdc in vdcs:
                    logger.info(
                        "scanDevices: re-announcing vDC '%s' (%s)",
                        vdc.name,
                        vdc.dsuid,
                    )
                    try:
                        vdc.reset_announcement()
                        await vdc.announce(sess)
                        await vdc.announce_devices(sess)
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "scanDevices: re-announcement failed for vDC %s",
                            vdc.dsuid,
                        )

            asyncio.ensure_future(_do_scan(vdcs_to_scan, session, dsuid_str))
            resp.generic_response.code = pb.ERR_OK
            return resp

        # Unknown generic request — delegate to user callback.
        if self._on_message is not None:
            result = await self._on_message(session, msg)
            if result is not None:
                return result

        resp.generic_response.code = pb.ERR_NOT_IMPLEMENTED
        resp.generic_response.description = f"Unknown generic request method: {method}"
        return resp

    # ---- remove handler (§6.3) ------------------------------------

    async def _handle_remove(self, msg: pb.Message) -> pb.Message:
        """Handle ``VDSM_SEND_REMOVE`` (§6.3).

        Looks up the device containing the addressed vdSD, consults
        the optional ``on_remove`` callback, and either removes the
        device from its vDC or rejects with ``ERR_FORBIDDEN``.
        """
        dsuid_str = msg.vdsm_send_remove.dSUID.upper()
        logger.info("remove request for dSUID %s", dsuid_str)

        resp = pb.Message()
        resp.type = pb.GENERIC_RESPONSE
        resp.message_id = msg.message_id

        # Find the vdSD and its owning vDC.
        dsuid = DsUid.from_string(dsuid_str)
        owning_vdc: Vdc | None = None
        for vdc in self._vdcs.values():
            if vdc.get_vdsd_by_dsuid(dsuid) is not None:
                owning_vdc = vdc
                break

        if owning_vdc is None:
            logger.warning(
                "remove: device %s not found",
                dsuid_str,
            )
            resp.generic_response.code = pb.ERR_NOT_FOUND
            resp.generic_response.description = f"Device {dsuid_str} not found"
            return resp

        # Consult user callback (if set).
        if self._on_remove is not None:
            try:
                allowed = await self._on_remove(dsuid_str)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "on_remove callback failed for %s",
                    dsuid_str,
                )
                allowed = False
            if not allowed:
                logger.info(
                    "remove: rejected by callback for %s",
                    dsuid_str,
                )
                resp.generic_response.code = pb.ERR_FORBIDDEN
                resp.generic_response.description = f"Removal of {dsuid_str} rejected"
                return resp

        # Remove the device from the vDC.
        # track_vanish=False: the vdSM initiated this removal and has
        # already deleted the device from its own database.
        owning_vdc.remove_device(dsuid, track_vanish=False)
        logger.info(
            "remove: device %s removed from vDC '%s'",
            dsuid_str,
            owning_vdc.name,
        )
        resp.generic_response.code = pb.ERR_OK
        return resp

    # ---- dimChannel notification handler (§7.3.5) -----------------

    async def _handle_dim_channel(self, msg: pb.Message) -> None:
        """Handle ``VDSM_NOTIFICATION_DIM_CHANNEL`` (§7.3.5).

        Resolves the target output channel and delegates to the
        output's :meth:`~pydsvdcapi.output.Output.dim_channel`
        method which invokes the ``on_dim_channel`` callback.
        """
        notif = msg.vdsm_send_dim_channel
        mode = notif.mode
        area = notif.area

        for dsuid_str in notif.dSUID:
            vdsd = self._find_vdsd_by_dsuid(dsuid_str)
            if vdsd is None:
                logger.warning(
                    "dimChannel: vdSD %s not found",
                    dsuid_str,
                )
                continue

            output = getattr(vdsd, "output", None)
            if output is None:
                logger.debug(
                    "dimChannel: vdSD %s has no output",
                    dsuid_str,
                )
                continue

            # Resolve the channel — prefer channelId (API v3),
            # fall back to channel type (int).
            channel_obj = None
            if notif.channelId:
                channel_obj = output.channel_by_key(notif.channelId)
            if channel_obj is None and notif.channel:
                from pydsvdcapi.enums import OutputChannelType

                try:
                    ct = OutputChannelType(int(notif.channel))
                    channel_obj = output.get_channel_by_type(ct)
                except (ValueError, KeyError):
                    pass
            # channel=0 means "default channel" — use the first one.
            if channel_obj is None:
                chs = output.channels
                if chs:
                    channel_obj = chs[min(chs)]

            if channel_obj is None:
                logger.warning(
                    "dimChannel: no channel resolved for vdSD %s",
                    dsuid_str,
                )
                continue

            logger.debug(
                "dimChannel: %s ch=%s mode=%d area=%d",
                dsuid_str,
                channel_obj.name,
                mode,
                area,
            )

            try:
                await output.dim_channel(channel_obj, mode, area)
            except Exception:
                logger.exception(
                    "dimChannel handler raised for vdSD %s",
                    dsuid_str,
                )

    # ---- identify notification handler (§7.3.7) ---------------------

    async def _handle_identify(self, msg: pb.Message) -> None:
        """Handle ``VDSM_NOTIFICATION_IDENTIFY`` (§7.3.7).

        Resolves each target vdSD and calls its
        :meth:`~pydsvdcapi.vdsd.Vdsd.identify` method which invokes
        the ``on_identify`` callback.
        """
        notif = msg.vdsm_send_identify

        for dsuid_str in notif.dSUID:
            vdsd = self._find_vdsd_by_dsuid(dsuid_str)
            if vdsd is None:
                logger.warning(
                    "identify: vdSD %s not found",
                    dsuid_str,
                )
                continue

            try:
                await vdsd.identify()
            except Exception:
                logger.exception(
                    "identify handler raised for vdSD %s",
                    dsuid_str,
                )

    # ---- setOutputChannelValue notification handler ------------------

    def _find_vdsd_by_dsuid(self, dsuid_str: str) -> Any | None:
        """Find a vdSD across all vDCs by dSUID string."""
        dsuid_str = dsuid_str.upper()
        for vdc in self._vdcs.values():
            vdsd = vdc.get_vdsd_by_dsuid(DsUid.from_string(dsuid_str))
            if vdsd is not None:
                return vdsd
        return None

    async def _handle_set_control_value(self, msg: pb.Message) -> None:
        """Handle ``VDSM_NOTIFICATION_SET_CONTROL_VALUE`` (§7.3.8).

        Stores the control value on the target vdSD(s) and invokes
        the device's ``on_control_value`` callback if set.
        """
        notif = msg.vdsm_send_set_control_value
        name = notif.name
        value = notif.value
        group: int | None = int(notif.group) if notif.group else None
        zone_id: int | None = int(notif.zone_id) if notif.zone_id else None

        for dsuid_str in notif.dSUID:
            vdsd = self._find_vdsd_by_dsuid(dsuid_str)
            if vdsd is None:
                logger.warning(
                    "setControlValue: vdSD %s not found",
                    dsuid_str,
                )
                continue
            try:
                await vdsd.set_control_value(name, value, group, zone_id)
            except Exception:
                logger.exception(
                    "setControlValue callback raised for vdSD %s",
                    dsuid_str,
                )

    async def _handle_set_output_channel_value(
        self,
        session: VdcSession,
        msg: pb.Message,
    ) -> None:
        """Handle ``VDSM_NOTIFICATION_SET_OUTPUT_CHANNEL_VALUE``.

        Buffers the channel value on the target output; when
        ``apply_now`` is ``True`` (or omitted), applies all buffered
        values via the output's ``on_channel_applied`` callback.
        """
        notif = msg.vdsm_send_output_channel_value

        # Resolve the target vdSD(s).
        for dsuid_str in notif.dSUID:
            vdsd = self._find_vdsd_by_dsuid(dsuid_str)
            if vdsd is None:
                logger.warning(
                    "setOutputChannelValue: vdSD %s not found",
                    dsuid_str,
                )
                continue

            output = getattr(vdsd, "output", None)
            if output is None:
                logger.warning(
                    "setOutputChannelValue: vdSD %s has no output",
                    dsuid_str,
                )
                continue

            # Find the channel by container key, name, or channel type.
            channel_obj = None
            if notif.channelId:
                channel_obj = output.channel_by_key(notif.channelId)
            if channel_obj is None and notif.HasField("channel"):
                # Look up by channel type (int).
                from pydsvdcapi.enums import OutputChannelType

                try:
                    ct = OutputChannelType(int(notif.channel))
                    channel_obj = output.get_channel_by_type(ct)
                except (ValueError, KeyError):
                    pass
            if channel_obj is None:
                logger.warning(
                    "setOutputChannelValue: channel '%s'/%d not found on vdSD %s",
                    notif.channelId,
                    notif.channel,
                    dsuid_str,
                )
                continue

            # Buffer the value on the output.
            output.buffer_channel_value(channel_obj, notif.value)

            logger.debug(
                "setOutputChannelValue: %s ch=%s val=%s apply_now=%s",
                dsuid_str,
                channel_obj.name,
                notif.value,
                notif.apply_now,
            )

            # apply_now: True (or default=True when omitted) triggers
            # hardware apply of all pending updates.
            if notif.apply_now:
                await output.apply_pending_channels()

    # ---- scene notification handlers ---------------------------------

    @staticmethod
    def _matches_zone_and_group(
        vdsd: Any,
        output: Any,
        zone_id: int,
        group: int,
    ) -> bool:
        """Check whether *vdsd* / *output* matches the zone/group filter.

        A value of ``0`` for either parameter means "not specified" and
        always matches.  Otherwise the device's ``zone_id`` must equal
        *zone_id*, and the output's ``active_group`` (the operationally
        assigned dS Application ID from OutputSettings §4.8.2) or the
        output's ``groups`` membership set must contain *group*.
        """
        if zone_id != 0 and getattr(vdsd, "zone_id", 0) != zone_id:
            return False
        if group != 0:
            ag = getattr(output, "active_group", 0)
            if ag != group and group not in output.groups:
                return False
        return True

    async def _handle_call_scene(self, msg: pb.Message) -> None:
        """Handle ``VDSM_NOTIFICATION_CALL_SCENE`` (§7.3.1)."""
        notif = msg.vdsm_send_call_scene
        scene = notif.scene
        force = notif.force
        group = notif.group
        zone_id = notif.zone_id

        for dsuid_str in notif.dSUID:
            vdsd = self._find_vdsd_by_dsuid(dsuid_str)
            if vdsd is None:
                logger.warning("callScene: vdSD %s not found", dsuid_str)
                continue
            output = getattr(vdsd, "output", None)
            if output is None:
                logger.debug("callScene: vdSD %s has no output", dsuid_str)
                continue
            if not self._matches_zone_and_group(
                vdsd,
                output,
                zone_id,
                group,
            ):
                logger.debug(
                    "callScene: vdSD %s skipped (zone/group mismatch)",
                    dsuid_str,
                )
                continue
            await output.dispatch_scene(scene, force=force, group=group)
            logger.debug(
                "callScene %d (force=%s, group=%d, zone=%d) on vdSD %s",
                scene,
                force,
                group,
                zone_id,
                dsuid_str,
            )

    async def _handle_save_scene(self, msg: pb.Message) -> None:
        """Handle ``VDSM_NOTIFICATION_SAVE_SCENE`` (§7.3.2)."""
        notif = msg.vdsm_send_save_scene
        scene = notif.scene
        group = notif.group
        zone_id = notif.zone_id

        for dsuid_str in notif.dSUID:
            vdsd = self._find_vdsd_by_dsuid(dsuid_str)
            if vdsd is None:
                logger.warning("saveScene: vdSD %s not found", dsuid_str)
                continue
            output = getattr(vdsd, "output", None)
            if output is None:
                logger.debug("saveScene: vdSD %s has no output", dsuid_str)
                continue
            if not self._matches_zone_and_group(
                vdsd,
                output,
                zone_id,
                group,
            ):
                logger.debug(
                    "saveScene: vdSD %s skipped (zone/group mismatch)",
                    dsuid_str,
                )
                continue
            output.save_scene(scene)
            logger.debug(
                "saveScene %d (group=%d, zone=%d) on vdSD %s",
                scene,
                group,
                zone_id,
                dsuid_str,
            )

    async def _handle_undo_scene(self, msg: pb.Message) -> None:
        """Handle ``VDSM_NOTIFICATION_UNDO_SCENE`` (§7.3.3)."""
        notif = msg.vdsm_send_undo_scene
        scene = notif.scene
        group = notif.group
        zone_id = notif.zone_id

        for dsuid_str in notif.dSUID:
            vdsd = self._find_vdsd_by_dsuid(dsuid_str)
            if vdsd is None:
                logger.warning("undoScene: vdSD %s not found", dsuid_str)
                continue
            output = getattr(vdsd, "output", None)
            if output is None:
                logger.debug("undoScene: vdSD %s has no output", dsuid_str)
                continue
            if not self._matches_zone_and_group(
                vdsd,
                output,
                zone_id,
                group,
            ):
                logger.debug(
                    "undoScene: vdSD %s skipped (zone/group mismatch)",
                    dsuid_str,
                )
                continue
            output.undo_scene(scene, group=group)
            # Trigger callback for the restored values.
            await output.apply_pending_channels()
            logger.debug(
                "undoScene %d (group=%d, zone=%d) on vdSD %s",
                scene,
                group,
                zone_id,
                dsuid_str,
            )

    async def _handle_set_local_priority(self, msg: pb.Message) -> None:
        """Handle ``VDSM_NOTIFICATION_SET_LOCAL_PRIO`` (§7.3.4).

        Sets ``localPriority`` on the output if the referenced scene
        does **not** have its ``dontCare`` flag set.  Only acts if the
        device matches the zone/group filter.
        """
        notif = msg.vdsm_send_set_local_prio
        scene = notif.scene
        group = notif.group
        zone_id = notif.zone_id

        for dsuid_str in notif.dSUID:
            vdsd = self._find_vdsd_by_dsuid(dsuid_str)
            if vdsd is None:
                continue
            output = getattr(vdsd, "output", None)
            if output is None:
                continue
            if not self._matches_zone_and_group(
                vdsd,
                output,
                zone_id,
                group,
            ):
                continue
            entry = output.get_scene(scene)
            if entry is not None and not entry.get("dontCare", False):
                output.local_priority = True
                logger.debug(
                    "setLocalPriority: set on vdSD %s (scene %d, group=%d, zone=%d)",
                    dsuid_str,
                    scene,
                    group,
                    zone_id,
                )

    async def _handle_call_min_scene(self, msg: pb.Message) -> None:
        """Handle ``VDSM_NOTIFICATION_CALL_MIN_SCENE`` (§7.3.6).

        If the device is off (primary channel at min), set it to the
        minimum brightness / value needed to become logically "on".
        Only acts if the referenced scene does not have dontCare set
        and the device matches the zone/group filter.
        """
        notif = msg.vdsm_send_call_min_scene
        scene = notif.scene
        group = notif.group
        zone_id = notif.zone_id

        for dsuid_str in notif.dSUID:
            vdsd = self._find_vdsd_by_dsuid(dsuid_str)
            if vdsd is None:
                continue
            output = getattr(vdsd, "output", None)
            if output is None:
                continue
            if not self._matches_zone_and_group(
                vdsd,
                output,
                zone_id,
                group,
            ):
                continue
            entry = output.get_scene(scene)
            if entry is not None and entry.get("dontCare", False):
                continue
            # Find the primary channel (dsIndex 0).
            primary = output.get_channel(0)
            if primary is None:
                continue
            # Only act if the device is currently off.
            if primary.value is not None and primary.value > primary.min_value:
                continue
            # Set to min_brightness if available, otherwise min + resolution.
            min_on = output.min_brightness
            if min_on is None:
                min_on = primary.min_value + primary.resolution
            primary.set_value_from_vdsm(min_on)
            primary.confirm_applied()
            await output.apply_pending_channels()
            logger.debug(
                "callMinScene %d: set min-on on vdSD %s",
                scene,
                dsuid_str,
            )

    # ---- dunder -------------------------------------------------------

    def __repr__(self) -> str:
        return f"VdcHost(dsuid={self._dsuid!r}, port={self._port}, name={self.name!r})"

    def __del__(self) -> None:
        # Cancel any pending auto-save timer.
        timer = getattr(self, "_save_timer", None)
        if timer is not None:
            timer.cancel()

        # Best-effort cleanup hint.  Async resources should be released
        # via ``await host.stop()`` before the object is dropped.
        if self._zeroconf is not None:
            logger.warning(
                "VdcHost garbage-collected with active DNS-SD — "
                "call `await host.stop()` for clean shutdown."
            )
