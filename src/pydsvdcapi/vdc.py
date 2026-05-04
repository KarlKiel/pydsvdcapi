"""vDC — virtual Device Connector entity.

A :class:`Vdc` represents a logical virtual Device Connector in the
digitalSTROM system.  A vDC host (:class:`~pydsvdcapi.vdc_host.VdcHost`)
manages one or more vDCs, each of which in turn manages a set of
virtual dS devices (vdSDs).

Each vDC has the *common properties* shared by all addressable entities,
plus **vDC-specific** properties:

* **capabilities** — metering, identification, dynamicDefinitions
* **zoneID** — default dS zone assigned by the vdSM
* **implementationId** — unique identifier for the vDC implementation

Auto-save
~~~~~~~~~

When the owning :class:`VdcHost` has persistence enabled, any mutation
of a *tracked* property on the Vdc triggers a debounced auto-save on the
host.  The Vdc does **not** maintain its own persistence store — it
delegates entirely to its parent.

Announcement
~~~~~~~~~~~~

After the vDC session with a vdSM is established the host must announce
every registered vDC with :meth:`Vdc.announce`.  This sends a
``VDC_SEND_ANNOUNCE_VDC`` protobuf request carrying the vDC's dSUID and
waits for a ``GENERIC_RESPONSE``.

Usage example::

    from pydsvdcapi import VdcHost, Vdc

    host = VdcHost(name="My Gateway", state_path="state.yaml")
    vdc = Vdc(
        host=host,
        implementation_id="x-mycompany-light",
        name="Light Controller",
        model="Light vDC v1",
    )
    host.add_vdc(vdc)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.dsuid import DsUid, DsUidNamespace

if TYPE_CHECKING:
    from pydsvdcapi.device_template import DeviceTemplate
    from pydsvdcapi.session import VdcSession
    from pydsvdcapi.vdc_host import VdcHost
    from pydsvdcapi.vdsd import Device, Vdsd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Entity type string for a vDC (common property ``type``).
ENTITY_TYPE_VDC: str = "vDC"


# ---------------------------------------------------------------------------
# Capabilities helper
# ---------------------------------------------------------------------------


@dataclass
class VdcCapabilities:
    """Boolean capability flags for a vDC.

    Each flag maps directly to the documented vDC capabilities:

    * **metering** — the vDC provides metering data.
    * **identification** — the vDC can identify itself (e.g. blink a LED).
    * **dynamic_definitions** — the vDC supports dynamic device
      definitions such as ``propertyDescriptions`` and
      ``actionDescriptions``.
    """

    metering: bool = False
    identification: bool = False
    dynamic_definitions: bool = False

    def to_dict(self) -> dict[str, bool]:
        """Return the capabilities as a ``{name: bool}`` dictionary."""
        return {
            "metering": self.metering,
            "identification": self.identification,
            "dynamicDefinitions": self.dynamic_definitions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VdcCapabilities:
        """Create a :class:`VdcCapabilities` from a persisted dictionary."""
        return cls(
            metering=bool(data.get("metering", False)),
            identification=bool(data.get("identification", False)),
            dynamic_definitions=bool(data.get("dynamicDefinitions", False)),
        )


# ---------------------------------------------------------------------------
# Vdc
# ---------------------------------------------------------------------------


class Vdc:
    """Represents a logical virtual Device Connector.

    Parameters
    ----------
    host:
        The owning :class:`VdcHost`.  Used for triggering persistence
        and obtaining the active session for announcement.
    implementation_id:
        Unique identifier for this vDC implementation.  Non-digitalSTROM
        vDCs must use an ``"x-company-"`` prefix.  Used together with
        the host dSUID to derive the vDC's own dSUID when *dsuid* is not
        provided.
    dsuid:
        Explicit dSUID.  When omitted the dSUID is derived from
        *implementation_id* using :meth:`DsUid.from_name_in_space`
        with the well-known ``VDC`` namespace.
    name:
        User-facing name of this vDC.
    model:
        Human-readable model description.
    model_version:
        Firmware / version string.
    model_uid:
        System-unique ID for the functional model.  Derived
        deterministically from *model* when omitted.
    hardware_version:
        Human-readable hardware version string.
    hardware_guid:
        Native hardware GUID in ``schema:id`` format.
    hardware_model_guid:
        Native hardware model GUID.
    vendor_name:
        Human-readable vendor name.
    vendor_id:
        Short vendor identifier in ``schema:id`` format (e.g.
        ``enoceanvendor:002:Themokon`` or a GS1 GLN).  Read by the
        firmware alongside *vendor_guid*.
    vendor_guid:
        Globally unique vendor identifier.
    descriptions_group:
        System-ID used to look up the device's UI description group in
        the dSS configurator database.
    descriptions_class:
        System-ID used to look up the device's UI description class in
        the dSS configurator database.
    oem_guid:
        OEM product GUID.
    oem_model_guid:
        OEM product-model GUID.
    config_url:
        URL to the web configuration interface.
    device_icon_16:
        16×16 PNG icon as ``bytes``.
    device_icon_name:
        Filename-safe icon identifier for caching.
    device_class:
        digitalSTROM device class profile name.
    device_class_version:
        Revision number of the device class profile.
    capabilities:
        :class:`VdcCapabilities` flags.
    zone_id:
        Default dS zone ID assigned by the vdSM.
    """

    #: Attribute names whose mutation triggers a debounced auto-save
    #: on the parent :class:`VdcHost`.
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
            "vendor_id",
            "vendor_guid",
            "descriptions_group",
            "descriptions_class",
            "oem_guid",
            "oem_model_guid",
            "config_url",
            "device_icon_name",
            "device_class",
            "device_class_version",
            "zone_id",
        }
    )

    # ---- attribute change tracking -----------------------------------

    def __setattr__(self, name: str, value: object) -> None:
        """Set an attribute and schedule an auto-save on the host.

        Only attributes listed in :attr:`_TRACKED_ATTRS` are monitored.
        Auto-save is suppressed while ``_auto_save_enabled`` is ``False``
        (during ``__init__`` and state restoration).
        """
        super().__setattr__(name, value)
        if name in self._TRACKED_ATTRS and getattr(self, "_auto_save_enabled", False):
            host = getattr(self, "_host", None)
            if host is not None:
                host._schedule_auto_save()

    # ---- constructor -------------------------------------------------

    def __init__(
        self,
        *,
        host: VdcHost,
        implementation_id: str,
        dsuid: DsUid | None = None,
        name: str,
        model: str,
        model_version: str | None = None,
        model_uid: str | None = None,
        hardware_version: str | None = None,
        hardware_guid: str | None = None,
        hardware_model_guid: str | None = None,
        vendor_name: str | None = None,
        vendor_id: str | None = None,
        vendor_guid: str | None = None,
        descriptions_group: str | None = None,
        descriptions_class: str | None = None,
        oem_guid: str | None = None,
        oem_model_guid: str | None = None,
        config_url: str | None = None,
        device_icon_16: bytes | None = None,
        device_icon_name: str | None = None,
        device_class: str | None = None,
        device_class_version: str | None = None,
        capabilities: VdcCapabilities = VdcCapabilities(),
        zone_id: int = 0,
        template_path: str | Path | None = None,
    ) -> None:
        # Auto-save must be disabled during construction.
        self._auto_save_enabled: bool = False

        # --- parent reference -----------------------------------------
        self._host: VdcHost = host

        # --- identity -------------------------------------------------
        self._implementation_id: str = implementation_id

        if dsuid is not None:
            self._dsuid: DsUid = dsuid
        else:
            self._dsuid = self._derive_dsuid(implementation_id)

        # --- common properties ----------------------------------------
        if not name:
            raise ValueError("Vdc.name must not be empty")
        if not model:
            raise ValueError("Vdc.model must not be empty")
        self.name: str = name
        self.model: str = model
        self.model_version: str | None = model_version
        self.model_uid: str = model_uid or self._derive_model_uid(self.model)
        self.hardware_version: str | None = hardware_version
        self.hardware_guid: str | None = hardware_guid
        self.hardware_model_guid: str | None = hardware_model_guid
        self.vendor_name: str | None = vendor_name
        self.vendor_id: str | None = vendor_id
        self.vendor_guid: str | None = vendor_guid
        self.descriptions_group: str | None = descriptions_group
        self.descriptions_class: str | None = descriptions_class
        self.oem_guid: str | None = oem_guid
        self.oem_model_guid: str | None = oem_model_guid
        self.config_url: str | None = config_url
        self.device_icon_16: bytes | None = device_icon_16
        self.device_icon_name: str | None = device_icon_name
        self.device_class: str | None = device_class
        self.device_class_version: str | None = device_class_version

        # --- vDC-specific properties ----------------------------------
        self._capabilities: VdcCapabilities = capabilities
        self.zone_id: int = zone_id

        # --- device registry ------------------------------------------
        self._devices: dict[str, Device] = {}  # keyed by base dSUID str

        # --- runtime state --------------------------------------------
        self._active: bool = True
        self._announced: bool = False

        # --- template path --------------------------------------------
        self._template_path: Path | None = (
            Path(template_path) if template_path is not None else None
        )

        # Enable auto-save now that construction is complete.
        self._auto_save_enabled = True

    # ---- derived / computed properties --------------------------------

    @staticmethod
    def _derive_dsuid(implementation_id: str) -> DsUid:
        """Derive a vDC dSUID from *implementation_id*.

        Uses UUIDv5 hashing with the well-known VDC namespace so that
        the same implementation ID always produces the same dSUID.
        """
        return DsUid.from_name_in_space(implementation_id, DsUidNamespace.VDC)

    @staticmethod
    def _derive_model_uid(model: str) -> str:
        """Derive a deterministic ``modelUID`` from the model name."""
        uid = DsUid.from_name_in_space(model, DsUidNamespace.VDC)
        return str(uid)

    # ---- read-only accessors -----------------------------------------

    @property
    def dsuid(self) -> DsUid:
        """The dSUID of this vDC (read-only)."""
        return self._dsuid

    @property
    def display_id(self) -> str:
        """Human-readable identification (hex dSUID)."""
        return str(self._dsuid)

    @property
    def entity_type(self) -> str:
        """Entity type string (always ``"vDC"``)."""
        return ENTITY_TYPE_VDC

    @property
    def implementation_id(self) -> str:
        """The unique implementation identifier (read-only)."""
        return self._implementation_id

    @property
    def active(self) -> bool:
        """Whether this vDC is currently active / operational."""
        return self._active

    @active.setter
    def active(self, value: bool) -> None:
        self._active = bool(value)

    @property
    def capabilities(self) -> VdcCapabilities:
        """Capability flags (read-only structure).

        To modify, replace the entire object::

            vdc.capabilities = VdcCapabilities(metering=True)
        """
        return self._capabilities

    @capabilities.setter
    def capabilities(self, value: VdcCapabilities) -> None:
        self._capabilities = value
        if getattr(self, "_auto_save_enabled", False):
            host = getattr(self, "_host", None)
            if host is not None:
                host._schedule_auto_save()

    @property
    def host(self) -> VdcHost:
        """The owning :class:`VdcHost` (read-only)."""
        return self._host

    @property
    def is_announced(self) -> bool:
        """``True`` if this vDC has been announced to the vdSM."""
        return self._announced

    # ---- device management -------------------------------------------

    def add_device(self, device: Device) -> None:
        """Register a :class:`Device` with this vDC.

        The device is stored keyed by its base dSUID string.
        Triggers auto-save on the host.
        """
        key = str(device.dsuid)
        self._devices[key] = device
        logger.info(
            "Registered device %s with vDC '%s' (%d vdSD(s))",
            key,
            self.name,
            len(device.vdsds),
        )
        if getattr(self, "_auto_save_enabled", False):
            self._host._schedule_auto_save()

    def remove_device(self, dsuid: DsUid) -> Device | None:
        """Remove a device by its base dSUID.

        Returns the removed :class:`Device` or ``None``.
        """
        key = str(dsuid.device_base())
        device = self._devices.pop(key, None)
        if device is not None:
            logger.info("Removed device %s from vDC '%s'", key, self.name)
            if getattr(self, "_auto_save_enabled", False):
                self._host._schedule_auto_save()
        return device

    def get_device(self, dsuid: DsUid) -> Device | None:
        """Look up a device by its base dSUID."""
        return self._devices.get(str(dsuid.device_base()))

    def get_vdsd_by_dsuid(self, dsuid: DsUid) -> Vdsd | None:
        """Look up a vdSD across all devices by its full dSUID."""
        for device in self._devices.values():
            vdsd = device.get_vdsd_by_dsuid(dsuid)
            if vdsd is not None:
                return vdsd
        return None

    @property
    def devices(self) -> dict[str, Device]:
        """A read-only view of all registered devices."""
        return dict(self._devices)

    async def announce_devices(self, session: VdcSession) -> int:
        """Announce all devices (and their vdSDs) to the vdSM.

        This should be called after the vDC itself has been announced.

        Devices are announced concurrently.  The dSM may query all
        registered devices immediately upon receiving the first
        ``ANNOUNCE_DEVICE`` message, and will not confirm any single
        announce until all pending announces are in flight.  Sequential
        announcement would therefore deadlock on multi-device vDCs.

        Returns the total number of vdSDs successfully announced.
        """
        import asyncio as _asyncio

        unannounced = [d for d in self._devices.values() if not d.is_announced]

        async def _announce_one(device: Any) -> int:
            try:
                result = await device.announce(session)
                return int(result)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to announce device %s", device.dsuid)
                return 0

        results = await _asyncio.gather(*[_announce_one(d) for d in unannounced])
        total = sum(results)
        logger.info(
            "vDC '%s': announced %d vdSD(s) across %d device(s)",
            self.name,
            total,
            len(self._devices),
        )
        return total

    def _schedule_auto_save(self) -> None:
        """Delegate auto-save scheduling to the owning host."""
        self._host._schedule_auto_save()

    # ---- device templates --------------------------------------------

    def save_template(
        self,
        device: Device,
        *,
        template_type: str,
        integration: str,
        name: str,
        description: str | None = None,
    ) -> Path:
        """Save a device template to disk.

        Parameters
        ----------
        device:
            The :class:`~pydsvdcapi.vdsd.Device` to use as the source.
        template_type:
            Either ``"generic"`` or ``"model"``.  Controls the
            sub-directory (``generic_templates/`` or
            ``model_templates/``).
        integration:
            Integration identifier used as a second-level sub-folder
            (e.g. ``"x-acme-light"``).
        name:
            File stem for the YAML template file (e.g.
            ``"dimmable-light"``).
        description:
            Optional human-readable description stored in the template.

        Returns
        -------
        pathlib.Path
            Absolute path of the saved YAML file.

        Raises
        ------
        RuntimeError
            If no ``template_path`` was set on this vDC.
        """
        if self._template_path is None:
            raise RuntimeError(
                "No template_path configured on this Vdc.  "
                "Pass template_path=... to the Vdc constructor."
            )

        import yaml

        from pydsvdcapi.device_template import (
            DeviceTemplate,
            build_required_callbacks,
            build_required_fields,
        )

        vdsd_trees = [vdsd.get_property_tree() for vdsd in device.vdsds.values()]
        stripped_tree = device.get_template_tree()

        template = DeviceTemplate(
            template_type=template_type,
            integration=integration,
            name=name,
            tree=stripped_tree,
            required_fields=build_required_fields(vdsd_trees),
            required_callbacks=build_required_callbacks(vdsd_trees),
            description=description,
        )

        folder = self._template_path / f"{template_type}_templates" / integration
        folder.mkdir(parents=True, exist_ok=True)
        file_path = folder / f"{name}.yaml"

        with file_path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(
                template.to_dict(),
                fh,
                allow_unicode=True,
                sort_keys=False,
            )

        logger.info(
            "Saved %s template '%s/%s' to %s",
            template_type,
            integration,
            name,
            file_path,
        )
        return file_path

    def load_template(
        self,
        template_type: str,
        integration: str,
        name: str,
    ) -> DeviceTemplate:
        """Load a device template from disk.

        Parameters
        ----------
        template_type:
            Either ``"generic"`` or ``"model"``.
        integration:
            Integration identifier (sub-folder).
        name:
            File stem (without ``.yaml`` extension).

        Returns
        -------
        DeviceTemplate
            A :class:`~pydsvdcapi.device_template.DeviceTemplate`
            ready to configure and instantiate.

        Raises
        ------
        RuntimeError
            If no ``template_path`` was set on this vDC.
        FileNotFoundError
            If the template file does not exist.
        """
        if self._template_path is None:
            raise RuntimeError(
                "No template_path configured on this Vdc.  "
                "Pass template_path=... to the Vdc constructor."
            )

        import yaml

        from pydsvdcapi.device_template import DeviceTemplate

        file_path = (
            self._template_path
            / f"{template_type}_templates"
            / integration
            / f"{name}.yaml"
        )

        with file_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        template = DeviceTemplate.from_dict(data)
        logger.info(
            "Loaded %s template '%s/%s' from %s",
            template_type,
            integration,
            name,
            file_path,
        )
        return template

    @property
    def template_path(self) -> Path | None:
        """The base directory for device templates (read-only)."""
        return self._template_path

    # ---- common-property dict ----------------------------------------

    def get_properties(self) -> dict[str, Any]:
        """Return all properties as a flat dictionary.

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
            "vendorId": self.vendor_id,
            "vendorGuid": self.vendor_guid,
            "descriptionsGroup": self.descriptions_group,
            "descriptionsClass": self.descriptions_class,
            "oemGuid": self.oem_guid,
            "oemModelGuid": self.oem_model_guid,
            "configURL": self.config_url,
            "deviceIcon16": self.device_icon_16,
            "deviceIconName": self.device_icon_name,
            "name": self.name,
            "deviceClass": self.device_class,
            "deviceClassVersion": self.device_class_version,
            "active": self._active,
            "implementationId": self._implementation_id,
            "capabilities": self._capabilities.to_dict(),
            "zoneID": self.zone_id,
        }

    # ---- property tree (for persistence) -----------------------------

    def get_property_tree(self) -> dict[str, Any]:
        """Return the vDC data suitable for inclusion in the host's
        YAML property tree.

        The structure is::

            dSUID: "..."
            implementationId: "x-company-light"
            name: "Light Controller"
            model: "Light vDC v1"
            ...
            capabilities:
              metering: false
              identification: false
              dynamicDefinitions: false
            zoneID: 0
        """
        node: dict[str, Any] = {
            "dSUID": str(self._dsuid),
            "implementationId": self._implementation_id,
            "name": self.name,
            "model": self.model,
            "modelVersion": self.model_version,
            "modelUID": self.model_uid,
            "hardwareVersion": self.hardware_version,
            "hardwareGuid": self.hardware_guid,
            "hardwareModelGuid": self.hardware_model_guid,
            "vendorName": self.vendor_name,
            "vendorId": self.vendor_id,
            "vendorGuid": self.vendor_guid,
            "descriptionsGroup": self.descriptions_group,
            "descriptionsClass": self.descriptions_class,
            "oemGuid": self.oem_guid,
            "oemModelGuid": self.oem_model_guid,
            "configURL": self.config_url,
            "deviceIconName": self.device_icon_name,
            "deviceClass": self.device_class,
            "deviceClassVersion": self.device_class_version,
            "capabilities": self._capabilities.to_dict(),
            "zoneID": self.zone_id,
        }
        if self._devices:
            node["devices"] = [
                dev.get_property_tree() for dev in self._devices.values()
            ]
        return node

    # ---- state restoration -------------------------------------------

    def _apply_state(self, state: dict[str, Any]) -> None:
        """Apply a persisted state dict to this vDC's properties.

        Auto-save is suppressed during restoration to avoid triggering
        a redundant write.
        """
        prev = self._auto_save_enabled
        self._auto_save_enabled = False
        try:
            if "dSUID" in state:
                self._dsuid = DsUid.from_string(state["dSUID"])
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
            if "vendorId" in state:
                self.vendor_id = state["vendorId"]
            if "vendorGuid" in state:
                self.vendor_guid = state["vendorGuid"]
            if "descriptionsGroup" in state:
                self.descriptions_group = state["descriptionsGroup"]
            if "descriptionsClass" in state:
                self.descriptions_class = state["descriptionsClass"]
            if "oemGuid" in state:
                self.oem_guid = state["oemGuid"]
            if "oemModelGuid" in state:
                self.oem_model_guid = state["oemModelGuid"]
            if "configURL" in state:
                self.config_url = state["configURL"]
            if "deviceIconName" in state:
                self.device_icon_name = state["deviceIconName"]
            if "deviceClass" in state:
                self.device_class = state["deviceClass"]
            if "deviceClassVersion" in state:
                self.device_class_version = state["deviceClassVersion"]
            if "capabilities" in state:
                self._capabilities = VdcCapabilities.from_dict(state["capabilities"])
            if "zoneID" in state:
                self.zone_id = state["zoneID"]

            # Restore devices from persisted state.
            if "devices" in state:
                from pydsvdcapi.vdsd import Device

                for dev_state in state["devices"]:
                    base_dsuid_str = dev_state.get("baseDsUID")
                    if base_dsuid_str:
                        base = DsUid.from_string(base_dsuid_str)
                        device = self._devices.get(str(base.device_base()))
                        if device is None:
                            device = Device(vdc=self, dsuid=base)
                            self._devices[str(device.dsuid)] = device
                        device._apply_state(dev_state)
        finally:
            self._auto_save_enabled = prev

    # ---- announcement ------------------------------------------------

    async def announce(self, session: VdcSession) -> bool:
        """Announce this vDC to the connected vdSM.

        Sends a ``VDC_SEND_ANNOUNCE_VDC`` protobuf request with this
        vDC's dSUID and awaits a ``GENERIC_RESPONSE``.

        Parameters
        ----------
        session:
            The active :class:`VdcSession` to use for sending the
            announcement.

        Returns
        -------
        bool
            ``True`` if the vdSM accepted the announcement
            (``ERR_OK``), ``False`` otherwise.

        Raises
        ------
        ConnectionError
            If the session is not in the ``ACTIVE`` state.
        asyncio.TimeoutError
            If the vdSM does not respond within the request timeout.
        """
        msg = pb.Message()
        msg.type = pb.VDC_SEND_ANNOUNCE_VDC
        msg.vdc_send_announce_vdc.dSUID = str(self._dsuid)

        logger.info("Announcing vDC '%s' (dSUID %s)", self.name, self._dsuid)

        response = await session.send_request(msg)

        code = response.generic_response.code
        if code == pb.ERR_OK:
            self._announced = True
            logger.info("vDC '%s' announced successfully", self.name)
            return True

        description = response.generic_response.description
        logger.warning(
            "vDC '%s' announcement failed: code=%s description=%s",
            self.name,
            pb.ResultCode.Name(code),
            description,
        )
        self._announced = False
        return False

    def reset_announcement(self) -> None:
        """Reset the announcement state (e.g. on session disconnect).

        Called by the host when the session ends to mark all vDCs
        and their devices as unannounced so they will be re-announced
        on the next session.
        """
        self._announced = False
        for device in self._devices.values():
            device.reset_announcement()

    # ---- dunder -------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Vdc(dsuid={self._dsuid!r}, "
            f"implementation_id={self._implementation_id!r}, "
            f"name={self.name!r})"
        )
