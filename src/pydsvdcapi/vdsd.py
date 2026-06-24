"""vdSD — virtual digitalSTROM device.

A :class:`Vdsd` is the API-visible unit that the vdSM (and dSS) recognise
as an individual device.  Each Vdsd has its own dSUID and is announced
separately via ``VDC_SEND_ANNOUNCE_DEVICE``.

One physical piece of hardware may be represented by **one or several**
Vdsd instances, depending on the rules laid out in the vDC API
(§5.2 / ``docs/device-splitting-guidelines.md``):

  * Each independent output → separate Vdsd.
  * Different zones / primary groups → separate Vdsd.
  * Buttons, sensors, binary inputs may be combined in one Vdsd.

To model "one physical device → N vdSDs" correctly the library provides
the :class:`Device` wrapper.  A Device holds one or more Vdsd instances
that share the first 16 bytes of their dSUID (byte 17 = sub-device
index).  For the common case of a physical device with only one
function, the Device simply contains one Vdsd.

Lifecycle
~~~~~~~~~

1. Create a :class:`Device` (or use the convenience ``Vdc.create_device``).
2. Attach one or more Vdsd instances via ``device.add_vdsd()``.
3. Configure each Vdsd (primary group, model features, …).
4. When configuration is final, call ``device.announce(session)`` to
   announce **all** contained Vdsd instances to the vdSM and register
   the device for persistence.
5. To change structural properties after announcement, call
   ``device.update(session, callback)`` which will vanish/re-announce.

Persistence
~~~~~~~~~~~

Vdsd state is serialised into the Vdc's property tree (and from there
into the VdcHost's YAML file).  On restore, the Vdc re-creates its
Device/Vdsd objects from the persisted data.

Usage example::

    from pydsvdcapi import Vdc, Device, Vdsd
    from pydsvdcapi.enums import ColorGroup

    vdc = Vdc(host=host, implementation_id="x-acme-light")

    # Single-vdSD device (common case)
    device = Device(vdc=vdc, dsuid=my_dsuid)
    vdsd = Vdsd(device=device, primary_group=ColorGroup.YELLOW,
                name="Kitchen Light")
    device.add_vdsd(vdsd)
    await device.announce(session)

    # Multi-vdSD device (e.g. combined light + shade)
    base = DsUid.from_enocean("0512ABCD")
    device2 = Device(vdc=vdc, dsuid=base)
    vdsd_light = Vdsd(device=device2, primary_group=ColorGroup.YELLOW,
                      subdevice_index=0, name="Light")
    vdsd_shade = Vdsd(device=device2, primary_group=ColorGroup.GREY,
                      subdevice_index=1, name="Shade")
    device2.add_vdsd(vdsd_light)
    device2.add_vdsd(vdsd_shade)
    await device2.announce(session)
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
)

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.dsuid import DsUid
from pydsvdcapi.enums import ColorGroup, DeviceLifecycleState
from pydsvdcapi.property_handling import dict_to_elements

if TYPE_CHECKING:
    from pydsvdcapi.actions import (
        CustomAction,
        DeviceActionDescription,
        DynamicAction,
        StandardAction,
    )
    from pydsvdcapi.binary_input import BinaryInput
    from pydsvdcapi.button_input import ButtonInput
    from pydsvdcapi.device_event import DeviceEvent
    from pydsvdcapi.device_property import DeviceProperty
    from pydsvdcapi.device_state import DeviceState
    from pydsvdcapi.output import Output
    from pydsvdcapi.sensor_input import SensorInput
    from pydsvdcapi.session import VdcSession
    from pydsvdcapi.vdc import Vdc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Entity type string for a vdSD (common property ``type``).
ENTITY_TYPE_VDSD: str = "vdSD"

#: Type alias for the control-value callback.
#:
#: Signature::
#:
#:     async def callback(vdsd, name, value, group, zone_id) -> None
#:     # or sync:
#:     def callback(vdsd, name, value, group, zone_id) -> None
#:
#: ``vdsd`` is the :class:`Vdsd` instance that received the
#: control value, ``name`` is the control-value name (e.g.
#: ``"heatingLevel"``), ``value`` is the numeric value, and
#: ``group`` / ``zone_id`` are optional contextual integers
#: (``None`` when not provided by the vdSM).
ControlValueCallback = Callable[
    ["Vdsd", str, float, int | None, int | None],
    None | Awaitable[None],
]

#: Type alias for the invoke-action callback.
#:
#: Signature::
#:
#:     async def callback(vdsd, action_id, params) -> None
#:     # or sync:
#:     def callback(vdsd, action_id, params) -> None
#:
#: ``vdsd`` is the :class:`Vdsd` instance that received the
#: action invocation, ``action_id`` is the action name string
#: (e.g. ``"std.play"``), and ``params`` is a dict of any
#: additional parameter name → value pairs (may be empty).
InvokeActionCallback = Callable[
    ["Vdsd", str, dict[str, Any]],
    None | Awaitable[None],
]

#: Type alias for the identify callback.
#:
#: Signature::
#:
#:     async def callback(vdsd) -> None
#:     # or sync:
#:     def callback(vdsd) -> None
#:
#: ``vdsd`` is the :class:`Vdsd` instance that received the
#: identify notification (§7.3.7).  The callback should trigger
#: a visual or acoustic identification signal on the native
#: device (e.g. blink an LED, beep, etc.).
IdentifyCallback = Callable[
    ["Vdsd"],
    None | Awaitable[None],
]


# ---------------------------------------------------------------------------
# Vdsd — one API-visible device
# ---------------------------------------------------------------------------


class Vdsd:
    """A single virtual digitalSTROM device (one dSUID).

    Each Vdsd is a fully addressable entity with its own dSUID,
    announced individually to the vdSM.

    Parameters
    ----------
    device:
        The owning :class:`Device`.  Provides the base dSUID and the
        link to the Vdc for persistence.
    primary_group:
        The dS class (colour) of this device.
    subdevice_index:
        Byte-17 sub-device enumeration within the hardware device.
        For single-vdSD devices, leave at 0.
    name:
        User-facing name (writable by the vdSM via ``setProperty``).
    model:
        Human-readable model description.
    model_version:
        Firmware / version string.
    model_uid:
        Functional model UID.  Derived from *model* when omitted.
    hardware_version:
        Hardware version string.
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
    zone_id:
        dS zone assigned by the vdSM.
    model_features:
        Set of model-feature flag names (e.g. ``{"blink",
        "identification"}``).  See §4.1.1.1 for valid names.
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
        super().__setattr__(name, value)
        if name in self._TRACKED_ATTRS and getattr(self, "_auto_save_enabled", False):
            device = getattr(self, "_device", None)
            if device is not None:
                device._schedule_auto_save()

    # ---- constructor -------------------------------------------------

    def __init__(
        self,
        *,
        device: Device,
        primary_group: ColorGroup,
        subdevice_index: int = 0,
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
        zone_id: int = 0,
        model_features: set[str] | None = None,
        prog_mode: bool | None = None,
        current_config_id: str | None = None,
        configurations: list[str] | None = None,
    ) -> None:
        # Auto-save must be disabled during construction.
        self._auto_save_enabled: bool = False

        # --- parent reference -----------------------------------------
        self._device: Device = device

        # --- identity -------------------------------------------------
        self._subdevice_index: int = subdevice_index
        self._dsuid: DsUid = device.dsuid.derive_subdevice(subdevice_index)

        # --- common properties ----------------------------------------
        if not name:
            raise ValueError("Vdsd.name must not be empty")
        if not model:
            raise ValueError("Vdsd.model must not be empty")
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

        # --- vdSD-specific properties ---------------------------------
        if primary_group is None:
            raise ValueError("primary_group is mandatory and must not be None.")
        self._primary_group: ColorGroup = primary_group
        self.zone_id: int = zone_id
        self._model_features: set[str] = (
            set(model_features) if model_features else set()
        )
        self._features_derived: bool = False
        self.prog_mode: bool | None = prog_mode
        self.current_config_id: str | None = current_config_id
        self._configurations: list[str] = list(configurations) if configurations else []

        # --- components -----------------------------------------------
        self._binary_inputs: dict[int, BinaryInput] = {}
        self._button_inputs: dict[int, ButtonInput] = {}
        self._sensor_inputs: dict[int, SensorInput] = {}
        self._device_events: dict[int, DeviceEvent] = {}
        self._device_states: dict[int, DeviceState] = {}
        self._device_properties: dict[int, DeviceProperty] = {}
        self._action_descriptions: dict[int, DeviceActionDescription] = {}
        self._standard_actions: dict[int, StandardAction] = {}
        self._custom_actions: dict[int, CustomAction] = {}
        self._dynamic_actions: dict[int, DynamicAction] = {}
        self._output: Output | None = None

        # --- runtime state --------------------------------------------
        self._lifecycle_state: DeviceLifecycleState = DeviceLifecycleState.ACTIVE
        self._announced: bool = False
        self._session: VdcSession | None = None

        # --- control values (volatile – NOT persisted) ----------------
        #: Stores the latest control values received from the dSS.
        #: Keyed by control-value name (e.g. ``"heatingLevel"``).
        #: Each entry is a dict with ``value``, ``group``, ``zone_id``.
        self._control_values: dict[str, dict[str, Any]] = {}
        self._on_control_value: ControlValueCallback | None = None
        self._on_invoke_action: InvokeActionCallback | None = None
        self._on_identify: IdentifyCallback | None = None

        # Enable auto-save now that construction is complete.
        self._auto_save_enabled = True

    # ---- derived / computed helpers ----------------------------------

    @staticmethod
    def _derive_model_uid(model: str) -> str:
        """Derive a deterministic ``modelUID`` from the model name."""
        from pydsvdcapi.dsuid import DsUidNamespace

        uid = DsUid.from_name_in_space(model, DsUidNamespace.VDC)
        return str(uid)

    # ---- read-only accessors -----------------------------------------

    @property
    def dsuid(self) -> DsUid:
        """The dSUID of this vdSD (read-only)."""
        return self._dsuid

    @property
    def display_id(self) -> str:
        """Human-readable identification (hex dSUID)."""
        return str(self._dsuid)

    @property
    def entity_type(self) -> str:
        """Entity type string (always ``"vdSD"``)."""
        return ENTITY_TYPE_VDSD

    @property
    def subdevice_index(self) -> int:
        """Sub-device enumeration byte (byte 17)."""
        return self._subdevice_index

    @property
    def primary_group(self) -> ColorGroup | None:
        """The primary dS class (colour) of this device."""
        return self._primary_group

    @property
    def active(self) -> bool:
        """Whether this vdSD is currently active / operational.

        Derived from :attr:`lifecycle_state`.  ``True`` only when
        ``lifecycle_state == DeviceLifecycleState.ACTIVE``.
        Use :meth:`set_lifecycle_state` to change this value.
        """
        return self._lifecycle_state == DeviceLifecycleState.ACTIVE

    @property
    def lifecycle_state(self) -> DeviceLifecycleState:
        """Current lifecycle state of this vdSD."""
        return self._lifecycle_state

    @property
    def model_features(self) -> set[str]:
        """Set of model-feature flag names (read-only view).

        Modify via :meth:`add_model_feature` /
        :meth:`remove_model_feature`.
        """
        return set(self._model_features)

    @property
    def configurations(self) -> list[str]:
        """List of supported configuration/profile IDs (§4.1.1, read-only).

        Set via constructor or persistence restore.
        """
        return list(self._configurations)

    @property
    def device(self) -> Device:
        """The owning :class:`Device`."""
        return self._device

    @property
    def is_announced(self) -> bool:
        """``True`` if this vdSD has been announced to the vdSM."""
        return self._announced

    # ---- control values (volatile runtime state from dSS) -----------

    @property
    def control_values(self) -> dict[str, dict[str, Any]]:
        """All current control values as ``{name: {value, group, zone_id}}``.

        Returns a shallow copy — callers cannot mutate the internal
        store.
        """
        return {name: dict(entry) for name, entry in self._control_values.items()}

    def get_control_value(self, name: str) -> dict[str, Any] | None:
        """Return a single control value entry, or ``None`` if unset.

        The returned dict has keys ``value`` (float), ``group``
        (int | None), ``zone_id`` (int | None).
        """
        entry = self._control_values.get(name)
        if entry is not None:
            return dict(entry)
        return None

    @property
    def on_control_value(self) -> ControlValueCallback | None:
        """Callback invoked when the dSS pushes a control value."""
        return self._on_control_value

    @on_control_value.setter
    def on_control_value(self, callback: ControlValueCallback | None) -> None:
        self._on_control_value = callback

    async def set_control_value(
        self,
        name: str,
        value: float,
        group: int | None = None,
        zone_id: int | None = None,
    ) -> None:
        """Store a control value received from the dSS.

        Parameters
        ----------
        name:
            The control-value name (e.g. ``"heatingLevel"``).
        value:
            The numeric value.
        group:
            Optional dS colour-group integer.
        zone_id:
            Optional dS zone ID.
        """
        self._control_values[name] = {
            "value": value,
            "group": group,
            "zone_id": zone_id,
        }
        logger.debug(
            "vdSD %s: control value '%s' = %s (group=%s, zone_id=%s)",
            self._dsuid,
            name,
            value,
            group,
            zone_id,
        )
        if self._on_control_value is not None:
            import asyncio

            result = self._on_control_value(self, name, value, group, zone_id)
            if asyncio.iscoroutine(result):
                await result

    @property
    def on_identify(self) -> IdentifyCallback | None:
        """Callback invoked when the vdSM sends an identify notification (§7.3.7)."""
        return self._on_identify

    @on_identify.setter
    def on_identify(self, callback: IdentifyCallback | None) -> None:
        self._on_identify = callback

    async def identify(self) -> None:
        """Handle an identify notification from the vdSM (§7.3.7).

        Triggers the ``on_identify`` callback so the user can
        implement a visual/acoustic identification signal on the
        native device (e.g. blink an LED, beep, vibrate).
        """
        logger.info(
            "vdSD %s: identify requested",
            self._dsuid,
        )
        if self._on_identify is not None:
            import asyncio as _asyncio

            try:
                result = self._on_identify(self)
                if _asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception(
                    "on_identify callback raised for vdSD '%s'",
                    self.name,
                )

    @property
    def on_invoke_action(self) -> InvokeActionCallback | None:
        """Callback invoked when the vdSM invokes a device action (§7.3.10)."""
        return self._on_invoke_action

    @on_invoke_action.setter
    def on_invoke_action(self, callback: InvokeActionCallback | None) -> None:
        self._on_invoke_action = callback

    async def invoke_action(
        self,
        action_id: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Handle an ``invokeDeviceAction`` request from the vdSM (§7.3.10).

        Parameters
        ----------
        action_id:
            The action identifier (e.g. ``"std.play"``).
        params:
            Optional dict of parameter name → value pairs.

        Invokes the ``on_invoke_action`` callback if set.
        """
        params = params or {}
        logger.debug(
            "vdSD %s: invokeDeviceAction id='%s' params=%s",
            self._dsuid,
            action_id,
            params,
        )
        if self._on_invoke_action is not None:
            import asyncio as _asyncio

            result = self._on_invoke_action(self, action_id, params)
            if _asyncio.iscoroutine(result):
                await result

    # ---- model features management -----------------------------------

    def add_model_feature(self, feature: str) -> None:
        """Add a model feature flag.

        :raises ValueError: if *feature* is a member of
            :attr:`_UNSUPPORTED_MODEL_FEATURES` (i.e. it has no effect on
            TCP/IP VDC devices and must never be declared).
        """
        if feature in self._UNSUPPORTED_MODEL_FEATURES:
            raise ValueError(
                f"modelFeature {feature!r} is not supported for TCP/IP VDC "
                "devices and must not be declared — see "
                "docs/model-features-auto-assignment.md for details."
            )
        self._model_features.add(feature)

    def remove_model_feature(self, feature: str) -> None:
        """Remove a model feature flag (no-op if absent).

        Also prevents :meth:`announce` from auto-deriving features,
        so that manual removals are not silently overwritten.
        """
        self._model_features.discard(feature)
        self._features_derived = True

    # Channel-type IDs that support transitions (used by derive_model_features).
    _TRANST_CHANNEL_TYPES: frozenset = frozenset(
        set(range(1, 13))  # 1–12
        | set(range(14, 19))  # 14–18
        | set(range(22, 25))  # 22–24
    )

    # Channel-type IDs for ventilation control.
    _VENTILATION_CHANNEL_TYPES: frozenset = frozenset({12, 13, 14, 15, 20, 21})

    # Features that cannot be used with TCP/IP VDC devices and must never be
    # declared.  Three root causes:
    #   1. Output-mode selectors (outmode, outmodeswitch, …) write to the dSS
    #      m_OutputMode field via DS485 CfgFunction_Mode.  The written value is
    #      never forwarded to the VDC, so VDC devices cannot observe or react
    #      to the change.
    #   2. Hardware-only features (ledauto, leddark, dimmodeconfig, …) relate
    #      to physical device capabilities that have no VDC write-back path.
    #   3. AKM input configuration (akminput, akmdelay) writes to DS485 bus
    #      registers via setAKMInputProperty() / setAKMInputTimeouts(); the
    #      written values are never forwarded to the VDC.
    # Note: "shadeprops" and "motiontimefins" are NOT in this set — they are
    # not auto-derived but may be added manually via add_model_feature().
    _UNSUPPORTED_MODEL_FEATURES: frozenset = frozenset(
        {
            # LED indicators — not API-controlled on VDC devices
            "ledauto",
            "leddark",
            # Hardware dimmer type selection — no VDC path
            "dimmodeconfig",
            # Hardware LED on consumption events — no VDC path
            "consumptioneventled",
            # Output-mode selectors that write via DS485, not via VDC
            "outmode",
            "outmodeswitch",
            "heatingoutmode",
            "umroutmode",
            "extradimmer",
            "optypeconfig",
            "outmodetempcontrol",
            "outmodeenoceanvalve",
            # Button-type features tied to physical TKM hardware
            "twowayconfig",
            "pushbcombined",
            # Hardware-device-specific features with no VDC equivalent
            "ftwdisplaysettings",
            "ftwbacklighttimeout",
            "grkl387workaround",
            # AKM input/delay config — DS485 bus only, never reaches VDC
            "akminput",
            "akmdelay",
        }
    )

    def derive_model_features(self) -> None:
        """Derive and add model-feature flags from the configured components.

        Applies the following rules, **adding** to any already-set features
        (duplicates are prevented automatically).

        After this method returns a flag is set so that :meth:`announce`
        will **not** run derivation again automatically.  This means you
        can call this method early to obtain the derived set, then freely
        add or remove features with :meth:`add_model_feature` /
        :meth:`remove_model_feature`, confident that :meth:`announce`
        will not undo those changes.

        Calling :meth:`remove_model_feature` without first calling this
        method also sets the flag, preventing the removed feature from
        being re-added during announcement.

        If neither this method nor :meth:`remove_model_feature` is called
        before :meth:`announce`, derivation runs automatically at
        announcement time.

        See ``docs/model-features-auto-assignment.md`` for the full rule
        reference, rationale, and guidance on features that require
        manual configuration.

        **Output / channel rules**

        * Any output present → ``"dontcare"``, ``"blink"``
        * Any channel with ``channelType`` in 1–12, 14–18, or 22–24
          AND ``function`` ≠ POSITIONAL(2) → ``"transt"``
          (positional outputs use hardware motor timing, not transition
          time, so ``"transt"`` is never derived for them)
        * ``primaryGroup`` 2 (GREY / outdoor shade) + ``function``
          POSITIONAL (2) → ``"shadeposition"``; additionally
          ``channelType`` 9 or 10 present → ``"shadebladeang"``
          (``"shadeprops"`` and ``"motiontimefins"`` are **not**
          auto-derived — add them manually via :meth:`add_model_feature`
          if the device supports motor timing configuration)
        * ``primaryGroup`` ≠ 2 → ``"outvalue8"``
        * Both ``channelType`` 2 (HUE) and 3 (SATURATION) present, or
          both 1 (BRIGHTNESS) and 4 (COLOR_TEMPERATURE) present →
          ``"outputchannels"``
        * ``function`` DIMMER (1), DIMMER_COLOR_TEMP (3), or
          FULL_COLOR_DIMMER (4) → ``"dimtimeconfig"``
        * ``function`` ON_OFF (0) → ``"outconfigswitch"`` +
          ``"impulseconfig"``
        * ``primaryGroup`` 3 (BLUE) + ``function`` ON_OFF (0) →
          ``"pwmvalue"``
        * ``channelType`` 16 (HEATING_POWER) present →
          ``"pwmvalue"``
        * Any ventilation channel (types 12, 13, 14, 15, 20, 21)
          present → ``"ventconfig"``

        **Sensor rules**

        * ``sensorType`` in {14, 15, 16, 17} (ACTIVE_POWER,
          ELECTRIC_CURRENT, ENERGY_METER, APPARENT_POWER) →
          ``"consumption"``
        * ``sensorType`` 1 (TEMPERATURE) + ``primaryGroup`` 3
          (BLUE) → ``"temperatureoffset"``

        **Binary input rules**

        * Any binary input present → ``"akmsensor"``

        **Button rules**

        * Any button → ``"pushbutton"`` + ``"pushbadvanced"`` +
          ``"pushbdisabled"``
        * Button with ``group`` ≠ 8 → ``"pushbarea"``
        * Button with ``group`` ≠ 8 + ``supportsLocalKeyMode`` →
          ``"pushbdevice"``
        * Button with ``group`` == 8 → ``"pushbsensor"`` +
          ``"highlevel"``

        **Primary-group rules**

        * ``primaryGroup`` 3 (BLUE) → ``"heatingprops"`` +
          ``"heatinggroup"``; if output present also ``"valvetype"`` +
          ``"extendedvalvetypes"``; additionally, if ventilation channel
          types (12, 13, 14, 15, 20, 21) present → ``"fcu"``
        * ``primaryGroup`` 2 (GREY) + output present →
          ``"locationconfig"`` + ``"operationlock"`` +
          ``"windprotectionconfigblind"`` (when ``channelType`` 9 or 10
          present) or ``"windprotectionconfigawning"`` (otherwise)
        * ``primaryGroup`` 8 (BLACK/Joker) → ``"jokerconfig"``

        **Identification rules**

        * ``on_identify`` callback registered → ``"identification"``

        Note: features in :attr:`_UNSUPPORTED_MODEL_FEATURES` are
        **never** auto-derived and will raise :exc:`ValueError` if
        passed to :meth:`add_model_feature`.  ``"shadeprops"`` and
        ``"motiontimefins"`` are **not** in that blocked set — they are
        not auto-derived but may be added manually when the device
        supports motor timing configuration (e.g. grey shade devices
        with ``outputSettings`` motor timing fields).  See
        ``docs/model-features-auto-assignment.md`` for the full list and
        rationale.
        """
        # primaryGroup integer — needed by both output and sensor rules
        pg = int(self._primary_group)

        # ---- output / channel rules ----------------------------------
        ch_types: set = set()  # populated below when output present
        if self._output is not None:
            self._model_features.add("dontcare")
            self._model_features.add("blink")

            fn = int(self._output.function)
            ch_types = {int(ch.channel_type) for ch in self._output.channels.values()}
            has_blade_channel = bool(ch_types & {9, 10})

            # transt: smooth transition support — not for POSITIONAL outputs,
            # which use hardware motor timing rather than software transition time.
            if fn != 2 and ch_types & self._TRANST_CHANNEL_TYPES:
                self._model_features.add("transt")

            # shade vs. normal output — determined by primaryGroup (ColorGroup.GREY=2)
            # "shadeprops" and "motiontimefins" are NOT auto-derived; add them
            # manually via add_model_feature() when motor timing config is needed.
            if pg == 2:  # ColorGroup.GREY — outdoor shade device
                if fn == 2:  # OutputFunction.POSITIONAL
                    self._model_features.add("shadeposition")
                    if has_blade_channel:
                        self._model_features.add("shadebladeang")
            else:
                self._model_features.add("outvalue8")

            # multi-channel colour output:
            #   HUE (2) + SATURATION (3) → RGB/RGBW full-colour
            #   BRIGHTNESS (1) + COLOR_TEMPERATURE (4) → tunable white
            if {2, 3} <= ch_types or {1, 4} <= ch_types:
                self._model_features.add("outputchannels")

            # dimmer features: DIMMER (1), DIMMER_COLOR_TEMP (3), FULL_COLOR_DIMMER (4)
            if fn in {1, 3, 4}:
                self._model_features.add("dimtimeconfig")

            # ON_OFF (binary) output features
            if fn == 0:  # OutputFunction.ON_OFF
                self._model_features.add("outconfigswitch")
                self._model_features.add("impulseconfig")

            # heating/climate valve: BLUE + ON_OFF → PWM UI component
            if pg == 3 and fn == 0:  # ColorGroup.BLUE
                self._model_features.add("pwmvalue")

            # HEATING_POWER channel (16) always implies valve/heating output
            if 16 in ch_types:
                self._model_features.add("pwmvalue")

            # ventilation control channels → ventconfig
            if ch_types & self._VENTILATION_CHANNEL_TYPES:
                self._model_features.add("ventconfig")

        # ---- sensor / consumption rules ------------------------------
        sensor_types: set[int] = {
            int(si.sensor_type) for si in self._sensor_inputs.values()
        }

        # base consumption display (any power/energy sensor)
        if sensor_types & {14, 15, 16, 17}:
            self._model_features.add("consumption")

        # temperature offset UI: climate device with a room-temperature sensor
        if 1 in sensor_types and pg == 3:  # TEMPERATURE + BLUE
            self._model_features.add("temperatureoffset")

        # ---- binary input rules --------------------------------------
        if self._binary_inputs:  # any binary input → AKM sensor function UI
            self._model_features.add("akmsensor")

        # ---- button rules --------------------------------------------
        if self._button_inputs:
            self._model_features.add("pushbutton")
            self._model_features.add("pushbadvanced")
            self._model_features.add("pushbdisabled")

            for btn in self._button_inputs.values():
                grp = btn.group

                if grp != 8:
                    self._model_features.add("pushbarea")
                    if btn.supports_local_key_mode:
                        self._model_features.add("pushbdevice")
                else:
                    self._model_features.add("pushbsensor")
                    self._model_features.add("highlevel")

        # ---- primary-group rules -------------------------------------

        if pg == 3:  # ColorGroup.BLUE — all climate devices
            self._model_features.add("heatingprops")
            self._model_features.add("heatinggroup")
            if self._output is not None:
                self._model_features.add("valvetype")
                self._model_features.add("extendedvalvetypes")
                # FCU / ventilation devices are identified by airflow channel types
                if ch_types & self._VENTILATION_CHANNEL_TYPES:
                    self._model_features.add("fcu")

        if pg == 2 and self._output is not None:  # ColorGroup.GREY
            self._model_features.add("locationconfig")
            ch_types_grey = {
                int(ch.channel_type) for ch in self._output.channels.values()
            }
            # Outdoor shade devices have channel type 7 (shadePositionOutside)
            # or 9 (shadeOpeningAngleOutside); indoor devices use only 8/10.
            if ch_types_grey & {7, 9}:
                self._model_features.add("operationlock")
                if ch_types_grey & {9}:  # outside slat/angle → jalousie/blind
                    self._model_features.add("windprotectionconfigblind")
                else:  # outdoor position only → awning / roller blind
                    self._model_features.add("windprotectionconfigawning")

        if pg == 8:  # ColorGroup.BLACK — joker / configurable
            self._model_features.add("jokerconfig")

        # ---- identification / blink ----------------------------------
        if self._on_identify is not None:
            self._model_features.add("identification")

        self._features_derived = True
        logger.debug(
            "derive_model_features '%s': %s",
            self.name,
            sorted(self._model_features),
        )

    # ---- binary input management -------------------------------------

    @property
    def binary_inputs(self) -> dict[int, BinaryInput]:
        """All binary inputs keyed by ``dsIndex`` (read-only view)."""
        return dict(self._binary_inputs)

    def add_binary_input(self, bi: BinaryInput) -> None:
        """Register a :class:`BinaryInput` with this vdSD.

        The input is indexed by its ``dsIndex``.  Adding an input
        with a ``dsIndex`` that already exists replaces the previous
        one.

        Raises
        ------
        ValueError
            If the binary input's owning vdSD is not this instance.
        """
        if bi.vdsd is not self:
            raise ValueError(
                f"BinaryInput belongs to a different vdSD "
                f"(expected {self._dsuid}, got {bi.vdsd.dsuid})"
            )
        self._binary_inputs[bi.ds_index] = bi
        logger.debug(
            "Added BinaryInput[%d] '%s' to vdSD %s",
            bi.ds_index,
            bi.name,
            self._dsuid,
        )
        # If already announced, start the alive timer immediately.
        if self._announced and self._session is not None:
            bi.start_alive_timer(self._session)
        self._schedule_auto_save_if_enabled()

    def remove_binary_input(self, ds_index: int) -> BinaryInput | None:
        """Remove a binary input by ``dsIndex``.

        Returns the removed :class:`BinaryInput` or ``None``.
        """
        bi = self._binary_inputs.pop(ds_index, None)
        if bi is not None:
            self._schedule_auto_save_if_enabled()
        return bi

    def get_binary_input(self, ds_index: int) -> BinaryInput | None:
        """Look up a binary input by ``dsIndex``."""
        return self._binary_inputs.get(ds_index)

    # ---- button input management -------------------------------------

    @property
    def button_inputs(self) -> dict[int, ButtonInput]:
        """All button inputs keyed by ``dsIndex`` (read-only view)."""
        return dict(self._button_inputs)

    def add_button_input(self, btn: ButtonInput) -> None:
        """Register a :class:`ButtonInput` with this vdSD.

        The input is indexed by its ``dsIndex``.  Adding an input
        with a ``dsIndex`` that already exists replaces the previous
        one.

        Raises
        ------
        ValueError
            If the button input's owning vdSD is not this instance.
        """
        if btn.vdsd is not self:
            raise ValueError(
                f"ButtonInput belongs to a different vdSD "
                f"(expected {self._dsuid}, got {btn.vdsd.dsuid})"
            )
        self._button_inputs[btn.ds_index] = btn
        logger.debug(
            "Added ButtonInput[%d] '%s' to vdSD %s",
            btn.ds_index,
            btn.name,
            self._dsuid,
        )
        # If already announced, start the session hook immediately.
        if self._announced and self._session is not None:
            btn.start_alive_timer(self._session)
        self._schedule_auto_save_if_enabled()

    def remove_button_input(self, ds_index: int) -> ButtonInput | None:
        """Remove a button input by ``dsIndex``.

        Returns the removed :class:`ButtonInput` or ``None``.
        """
        btn = self._button_inputs.pop(ds_index, None)
        if btn is not None:
            self._schedule_auto_save_if_enabled()
        return btn

    def get_button_input(self, ds_index: int) -> ButtonInput | None:
        """Look up a button input by ``dsIndex``."""
        return self._button_inputs.get(ds_index)

    # ---- sensor inputs -----------------------------------------------

    @property
    def sensor_inputs(self) -> dict[int, SensorInput]:
        """All sensor inputs keyed by ``dsIndex`` (read-only view)."""
        return dict(self._sensor_inputs)

    def add_sensor_input(self, si: SensorInput) -> None:
        """Register a :class:`SensorInput` with this vdSD.

        The input is indexed by its ``dsIndex``.  Adding an input
        with a ``dsIndex`` that already exists replaces the previous
        one.

        Raises
        ------
        ValueError
            If the sensor input's owning vdSD is not this instance.
        """
        if si.vdsd is not self:
            raise ValueError(
                f"SensorInput belongs to a different vdSD "
                f"(expected {self._dsuid}, got {si.vdsd.dsuid})"
            )
        self._sensor_inputs[si.ds_index] = si
        logger.debug(
            "Added SensorInput[%d] '%s' to vdSD %s",
            si.ds_index,
            si.name,
            self._dsuid,
        )
        # If already announced, start the alive timer immediately.
        if self._announced and self._session is not None:
            si.start_alive_timer(self._session)
        self._schedule_auto_save_if_enabled()

    def remove_sensor_input(self, ds_index: int) -> SensorInput | None:
        """Remove a sensor input by ``dsIndex``.

        Returns the removed :class:`SensorInput` or ``None``.
        """
        si = self._sensor_inputs.pop(ds_index, None)
        if si is not None:
            self._schedule_auto_save_if_enabled()
        return si

    def get_sensor_input(self, ds_index: int) -> SensorInput | None:
        """Look up a sensor input by ``dsIndex``."""
        return self._sensor_inputs.get(ds_index)

    # ---- output management ---------------------------------------------

    @property
    def output(self) -> Output | None:
        """The output component, or ``None``."""
        return self._output

    def set_output(self, output: Output) -> None:
        """Set the single output for this vdSD.

        Replaces any previously set output.

        Raises
        ------
        ValueError
            If the output's owning vdSD is not this instance.
        """
        if output.vdsd is not self:
            raise ValueError(
                f"Output belongs to a different vdSD "
                f"(expected {self._dsuid}, got {output.vdsd.dsuid})"
            )
        self._output = output
        logger.debug(
            "Set Output '%s' on vdSD %s",
            output.name,
            self._dsuid,
        )
        # If already announced, start the session hook immediately.
        if self._announced and self._session is not None:
            output.start_session(self._session)
        self._schedule_auto_save_if_enabled()

    def remove_output(self) -> Output | None:
        """Remove the output from this vdSD.

        Returns the removed :class:`Output` or ``None``.
        """
        output = self._output
        if output is not None:
            output.stop_session()
            self._output = None
            self._schedule_auto_save_if_enabled()
        return output

    # ---- device state management ------------------------------------

    @property
    def device_states(self) -> dict[int, DeviceState]:
        """All device states keyed by ``dsIndex`` (read-only view)."""
        return dict(self._device_states)

    def add_device_state(self, st: DeviceState) -> None:
        """Register a :class:`DeviceState` with this vdSD.

        The state is indexed by its ``dsIndex``.  Adding a state
        with a ``dsIndex`` that already exists replaces the previous
        one.

        Raises
        ------
        ValueError
            If the state's owning vdSD is not this instance.
        """
        if st.vdsd is not self:
            raise ValueError(
                f"DeviceState belongs to a different vdSD "
                f"(expected {self._dsuid}, got {st.vdsd.dsuid})"
            )
        self._device_states[st.ds_index] = st
        logger.debug(
            "Added DeviceState[%d] '%s' to vdSD %s",
            st.ds_index,
            st.name,
            self._dsuid,
        )
        self._schedule_auto_save_if_enabled()

    def remove_device_state(self, ds_index: int) -> DeviceState | None:
        """Remove a device state by ``dsIndex``.

        Returns the removed :class:`DeviceState` or ``None``.
        """
        st = self._device_states.pop(ds_index, None)
        if st is not None:
            self._schedule_auto_save_if_enabled()
        return st

    def get_device_state(self, ds_index: int) -> DeviceState | None:
        """Look up a device state by ``dsIndex``."""
        return self._device_states.get(ds_index)

    async def update_device_state(
        self,
        ds_index: int,
        value: str | int,
        session: VdcSession | None = None,
    ) -> None:
        """Convenience: update the device state at *ds_index*.

        Parameters
        ----------
        ds_index:
            The state index to update.
        value:
            The new state value.
        session:
            Optional session override; defaults to the vdSD's
            current session.

        Raises
        ------
        KeyError
            If no state is registered at *ds_index*.
        """
        st = self._device_states.get(ds_index)
        if st is None:
            raise KeyError(f"No DeviceState at index {ds_index} on vdSD {self._dsuid}")
        await st.update_value(value, session)

    # ---- device property management ----------------------------------

    @property
    def device_properties(self) -> dict[int, DeviceProperty]:
        """All device properties keyed by ``dsIndex`` (read-only view)."""
        return dict(self._device_properties)

    def add_device_property(self, prop: DeviceProperty) -> None:
        """Register a :class:`DeviceProperty` with this vdSD.

        The property is indexed by its ``dsIndex``.  Adding a property
        with a ``dsIndex`` that already exists replaces the previous
        one.

        Raises
        ------
        ValueError
            If the property's owning vdSD is not this instance.
        """
        if prop.vdsd is not self:
            raise ValueError(
                f"DeviceProperty belongs to a different vdSD "
                f"(expected {self._dsuid}, got {prop.vdsd.dsuid})"
            )
        self._device_properties[prop.ds_index] = prop
        logger.debug(
            "Added DeviceProperty[%d] '%s' to vdSD %s",
            prop.ds_index,
            prop.name,
            self._dsuid,
        )
        self._schedule_auto_save_if_enabled()

    def remove_device_property(self, ds_index: int) -> DeviceProperty | None:
        """Remove a device property by ``dsIndex``.

        Returns the removed :class:`DeviceProperty` or ``None``.
        """
        prop = self._device_properties.pop(ds_index, None)
        if prop is not None:
            self._schedule_auto_save_if_enabled()
        return prop

    def get_device_property(self, ds_index: int) -> DeviceProperty | None:
        """Look up a device property by ``dsIndex``."""
        return self._device_properties.get(ds_index)

    async def update_device_property(
        self,
        ds_index: int,
        value: float | int | str,
        session: VdcSession | None = None,
    ) -> None:
        """Convenience: update the device property at *ds_index*.

        Parameters
        ----------
        ds_index:
            The property index to update.
        value:
            The new property value.
        session:
            Optional session override; defaults to the vdSD's
            current session.

        Raises
        ------
        KeyError
            If no property is registered at *ds_index*.
        """
        prop = self._device_properties.get(ds_index)
        if prop is None:
            raise KeyError(
                f"No DeviceProperty at index {ds_index} on vdSD {self._dsuid}"
            )
        await prop.update_value(value, session)

    # ---- device event management ------------------------------------

    @property
    def device_events(self) -> dict[int, DeviceEvent]:
        """All device events keyed by ``dsIndex`` (read-only view)."""
        return dict(self._device_events)

    def add_device_event(self, evt: DeviceEvent) -> None:
        """Register a :class:`DeviceEvent` with this vdSD.

        The event is indexed by its ``dsIndex``.  Adding an event
        with a ``dsIndex`` that already exists replaces the previous
        one.

        Raises
        ------
        ValueError
            If the event's owning vdSD is not this instance.
        """
        if evt.vdsd is not self:
            raise ValueError(
                f"DeviceEvent belongs to a different vdSD "
                f"(expected {self._dsuid}, got {evt.vdsd.dsuid})"
            )
        self._device_events[evt.ds_index] = evt
        logger.debug(
            "Added DeviceEvent[%d] '%s' to vdSD %s",
            evt.ds_index,
            evt.name,
            self._dsuid,
        )
        self._schedule_auto_save_if_enabled()

    def remove_device_event(self, ds_index: int) -> DeviceEvent | None:
        """Remove a device event by ``dsIndex``.

        Returns the removed :class:`DeviceEvent` or ``None``.
        """
        evt = self._device_events.pop(ds_index, None)
        if evt is not None:
            self._schedule_auto_save_if_enabled()
        return evt

    def get_device_event(self, ds_index: int) -> DeviceEvent | None:
        """Look up a device event by ``dsIndex``."""
        return self._device_events.get(ds_index)

    async def raise_device_event(
        self,
        ds_index: int,
        session: VdcSession | None = None,
    ) -> None:
        """Convenience: raise the device event at *ds_index*.

        Parameters
        ----------
        ds_index:
            The event index to raise.
        session:
            Optional session override; defaults to the vdSD's
            current session.

        Raises
        ------
        KeyError
            If no event is registered at *ds_index*.
        """
        evt = self._device_events.get(ds_index)
        if evt is None:
            raise KeyError(f"No DeviceEvent at index {ds_index} on vdSD {self._dsuid}")
        await evt.raise_event(session)

    # ---- action description management (§4.5.2) ---------------------

    @property
    def action_descriptions(
        self,
    ) -> dict[int, DeviceActionDescription]:
        """All action descriptions keyed by ``dsIndex`` (read-only view)."""
        return dict(self._action_descriptions)

    def add_device_action_description(self, desc: DeviceActionDescription) -> None:
        """Register a :class:`DeviceActionDescription` with this vdSD.

        The description is indexed by its ``dsIndex``.  Adding one
        with a ``dsIndex`` that already exists replaces the previous.

        Raises
        ------
        ValueError
            If the description's owning vdSD is not this instance.
        """
        if desc.vdsd is not self:
            raise ValueError(
                f"DeviceActionDescription belongs to a different vdSD "
                f"(expected {self._dsuid}, got {desc.vdsd.dsuid})"
            )
        self._action_descriptions[desc.ds_index] = desc
        logger.debug(
            "Added DeviceActionDescription[%d] '%s' to vdSD %s",
            desc.ds_index,
            desc.name,
            self._dsuid,
        )
        self._schedule_auto_save_if_enabled()

    def remove_device_action_description(
        self, ds_index: int
    ) -> DeviceActionDescription | None:
        """Remove an action description by ``dsIndex``.

        Returns the removed :class:`DeviceActionDescription` or ``None``.
        """
        desc = self._action_descriptions.pop(ds_index, None)
        if desc is not None:
            self._schedule_auto_save_if_enabled()
        return desc

    def get_device_action_description(
        self, ds_index: int
    ) -> DeviceActionDescription | None:
        """Look up an action description by ``dsIndex``."""
        return self._action_descriptions.get(ds_index)

    # ---- standard action management (§4.5.3) ------------------------

    @property
    def standard_actions(self) -> dict[int, StandardAction]:
        """All standard actions keyed by ``dsIndex`` (read-only view)."""
        return dict(self._standard_actions)

    def add_standard_action(self, std: StandardAction) -> None:
        """Register a :class:`StandardAction` with this vdSD.

        The action is indexed by its ``dsIndex``.  Adding one
        with a ``dsIndex`` that already exists replaces the previous.

        Raises
        ------
        ValueError
            If the action's owning vdSD is not this instance.
        """
        if std.vdsd is not self:
            raise ValueError(
                f"StandardAction belongs to a different vdSD "
                f"(expected {self._dsuid}, got {std.vdsd.dsuid})"
            )
        self._standard_actions[std.ds_index] = std
        logger.debug(
            "Added StandardAction[%d] '%s' to vdSD %s",
            std.ds_index,
            std.name,
            self._dsuid,
        )
        self._schedule_auto_save_if_enabled()

    def remove_standard_action(self, ds_index: int) -> StandardAction | None:
        """Remove a standard action by ``dsIndex``.

        Returns the removed :class:`StandardAction` or ``None``.
        """
        std = self._standard_actions.pop(ds_index, None)
        if std is not None:
            self._schedule_auto_save_if_enabled()
        return std

    def get_standard_action(self, ds_index: int) -> StandardAction | None:
        """Look up a standard action by ``dsIndex``."""
        return self._standard_actions.get(ds_index)

    # ---- custom action management (§4.5.3) --------------------------

    @property
    def custom_actions(self) -> dict[int, CustomAction]:
        """All custom actions keyed by ``dsIndex`` (read-only view)."""
        return dict(self._custom_actions)

    def add_custom_action(self, cust: CustomAction) -> None:
        """Register a :class:`CustomAction` with this vdSD.

        The action is indexed by its ``dsIndex``.  Adding one
        with a ``dsIndex`` that already exists replaces the previous.

        Raises
        ------
        ValueError
            If the action's owning vdSD is not this instance.
        """
        if cust.vdsd is not self:
            raise ValueError(
                f"CustomAction belongs to a different vdSD "
                f"(expected {self._dsuid}, got {cust.vdsd.dsuid})"
            )
        self._custom_actions[cust.ds_index] = cust
        logger.debug(
            "Added CustomAction[%d] '%s' to vdSD %s",
            cust.ds_index,
            cust.name,
            self._dsuid,
        )
        self._schedule_auto_save_if_enabled()

    def remove_custom_action(self, ds_index: int) -> CustomAction | None:
        """Remove a custom action by ``dsIndex``.

        Returns the removed :class:`CustomAction` or ``None``.
        """
        cust = self._custom_actions.pop(ds_index, None)
        if cust is not None:
            self._schedule_auto_save_if_enabled()
        return cust

    def get_custom_action(self, ds_index: int) -> CustomAction | None:
        """Look up a custom action by ``dsIndex``."""
        return self._custom_actions.get(ds_index)

    # ---- dynamic action management (§4.5.3) -------------------------

    @property
    def dynamic_actions(self) -> dict[int, DynamicAction]:
        """All dynamic actions keyed by ``dsIndex`` (read-only view)."""
        return dict(self._dynamic_actions)

    def add_dynamic_action(self, dyn: DynamicAction) -> None:
        """Register a :class:`DynamicAction` with this vdSD.

        The action is indexed by its ``dsIndex``.  Adding one
        with a ``dsIndex`` that already exists replaces the previous.

        Raises
        ------
        ValueError
            If the action's owning vdSD is not this instance.
        """
        if dyn.vdsd is not self:
            raise ValueError(
                f"DynamicAction belongs to a different vdSD "
                f"(expected {self._dsuid}, got {dyn.vdsd.dsuid})"
            )
        self._dynamic_actions[dyn.ds_index] = dyn
        logger.debug(
            "Added DynamicAction[%d] '%s' to vdSD %s",
            dyn.ds_index,
            dyn.name,
            self._dsuid,
        )
        # Dynamic actions are transient — no auto-save.

    def remove_dynamic_action(self, ds_index: int) -> DynamicAction | None:
        """Remove a dynamic action by ``dsIndex``.

        Returns the removed :class:`DynamicAction` or ``None``.
        """
        return self._dynamic_actions.pop(ds_index, None)

    def get_dynamic_action(self, ds_index: int) -> DynamicAction | None:
        """Look up a dynamic action by ``dsIndex``."""
        return self._dynamic_actions.get(ds_index)

    def _schedule_auto_save_if_enabled(self) -> None:
        """Trigger auto-save if enabled."""
        if self._auto_save_enabled:
            device = getattr(self, "_device", None)
            if device is not None:
                device._schedule_auto_save()

    # ---- lifecycle state management ----------------------------------

    async def _push_active(self, active: bool) -> None:
        """Push a ``VDC_SEND_PUSH_NOTIFICATION`` for the ``active`` property."""
        if self._session is None:
            return
        msg = pb.Message()
        msg.type = pb.VDC_SEND_PUSH_NOTIFICATION
        msg.vdc_send_push_notification.dSUID = str(self._dsuid)
        for elem in dict_to_elements({"active": active}):
            msg.vdc_send_push_notification.changedproperties.append(elem)
        try:
            await self._session.send_notification(msg)
            logger.debug(
                "vdSD '%s': pushed active=%s", self.name, active
            )
        except (ConnectionError, OSError) as exc:
            logger.warning(
                "vdSD '%s': failed to push active: %s", self.name, exc
            )

    async def set_lifecycle_state(
        self, state: DeviceLifecycleState
    ) -> None:
        """Set the lifecycle state and handle all vdSM communication.

        * If ``active`` changes (``True`` ↔ ``False``) and the device is
          announced, pushes ``VDC_SEND_PUSH_NOTIFICATION`` with the new
          ``active`` value.  Push errors (``ConnectionError``, ``OSError``) are
          logged and suppressed.
        * If *state* is ``REMOVED`` and the device is announced, also
          sends ``VDC_SEND_VANISH``.  Errors from ``vanish`` propagate to the
          caller.
        * If the device is not yet announced, stores the state silently.
        """
        was_active = self._lifecycle_state == DeviceLifecycleState.ACTIVE
        self._lifecycle_state = state
        now_active = state == DeviceLifecycleState.ACTIVE

        if self._announced and self._session is not None:
            if was_active != now_active:
                await self._push_active(now_active)
            if state == DeviceLifecycleState.REMOVED:
                await self.vanish(self._session)

    # ---- property dict (for getProperty responses) -------------------

    def get_properties(self) -> dict[str, Any]:
        """Return all properties as a flat dictionary.

        Keys match the vDC API property names.
        ``None`` values indicate unset optional properties.
        """
        props: dict[str, Any] = {
            # Common properties
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
            "active": self._lifecycle_state == DeviceLifecycleState.ACTIVE,
            # vdSD-specific properties
            "primaryGroup": int(self._primary_group),
            "zoneID": self.zone_id,
            "progMode": self.prog_mode,
            "currentConfigId": self.current_config_id,
        }
        # modelFeatures — sorted by canonical ModelFeatureId enum index (as p44vdc).
        _MODEL_FEATURE_ORDER = {
            "dontcare": 0,
            "blink": 1,
            "transt": 4,
            "outmode": 5,
            "outmodeswitch": 6,
            "outvalue8": 7,
            "shadeposition": 15,
            "shadebladeang": 18,
            "consumption": 20,
            "outputchannels": 26,
            "heatingoutmode": 28,
            "heatingprops": 29,
            "pwmvalue": 30,
            "blinkconfig": 34,
            "umroutmode": 35,
            "impulseconfig": 39,
            "outmodegeneric": 40,
            "outconfigswitch": 41,
            "ventconfig": 47,
            "consumptioneventled": 50,
            "consumptiontimer": 51,
            "dimtimeconfig": 53,
            "outmodeauto": 54,
            "outmodetempcontrol": 60,
            "outmodeenoceanvalve": 61,
        }
        props["modelFeatures"] = {
            f: True
            for f in sorted(
                self._model_features,
                key=lambda x: _MODEL_FEATURE_ORDER.get(x, 999),
            )
        }

        # configurations (§4.1.1) — mandatory; empty dict when no profiles.
        props["configurations"] = {
            str(i): {"id": cid} for i, cid in enumerate(self._configurations)
        }

        # Button input component properties (§4.2 / §4.1.2).
        if self._button_inputs:
            props["buttonInputDescriptions"] = {
                str(btn.ds_index): btn.get_description_properties()
                for btn in self._button_inputs.values()
            }
            props["buttonInputSettings"] = {
                str(btn.ds_index): btn.get_settings_properties()
                for btn in self._button_inputs.values()
            }
            props["buttonInputStates"] = {
                str(btn.ds_index): btn.get_state_properties()
                for btn in self._button_inputs.values()
            }

        # Binary input component properties (§4.3 / §4.1.2).
        if self._binary_inputs:
            props["binaryInputDescriptions"] = {
                str(bi.ds_index): bi.get_description_properties()
                for bi in self._binary_inputs.values()
            }
            props["binaryInputSettings"] = {
                str(bi.ds_index): bi.get_settings_properties()
                for bi in self._binary_inputs.values()
            }
            props["binaryInputStates"] = {
                str(bi.ds_index): bi.get_state_properties()
                for bi in self._binary_inputs.values()
            }

        # Sensor input component properties (§4.3 / §4.1.3).
        if self._sensor_inputs:
            props["sensorDescriptions"] = {
                str(si.ds_index): si.get_description_properties()
                for si in self._sensor_inputs.values()
            }
            props["sensorSettings"] = {
                str(si.ds_index): si.get_settings_properties()
                for si in self._sensor_inputs.values()
            }
            props["sensorStates"] = {
                str(si.ds_index): si.get_state_properties()
                for si in self._sensor_inputs.values()
            }

        # ------------------------------------------------------------------
        # SingleDevice extensions (§4.5 / §4.6 / §4.7)
        # ------------------------------------------------------------------
        # In p44-vdc, enableAsSingleDevice() always creates ALL
        # SingleDevice containers together (deviceActions, dynamicActions,
        # customActions, standardActions, states, events, properties).
        # The vdSM may rely on the presence of the action description
        # properties to recognise a device as a SingleDevice.  We
        # therefore include empty action descriptions whenever ANY
        # SingleDevice feature is defined.
        has_single_device = bool(
            self._device_states
            or self._device_events
            or self._device_properties
            or self._action_descriptions
            or self._standard_actions
            or self._custom_actions
            or self._dynamic_actions
        )

        if has_single_device:
            # Action descriptions (§4.5.2) — always present for
            # SingleDevice, even if empty.
            # The element name (dict key) IS the action ID used by the
            # dSS — it calls vdcAction.getName() to identify the action.
            props["deviceActionDescriptions"] = (
                {
                    desc.name: desc.get_description_properties()
                    for desc in self._action_descriptions.values()
                }
                if self._action_descriptions
                else {}
            )

            # Standard actions (§4.5.3).
            # Key = standard action name, e.g. "std.play".
            props["standardActions"] = (
                {
                    std.name: std.get_properties()
                    for std in self._standard_actions.values()
                }
                if self._standard_actions
                else {}
            )

            # Custom actions (§4.5.3).
            # Key = custom action name, e.g. "custom.play-loud".
            props["customActions"] = (
                {
                    cust.name: cust.get_properties()
                    for cust in self._custom_actions.values()
                }
                if self._custom_actions
                else {}
            )

            # Dynamic device actions (§4.5.3).
            # Key = dynamic action name, e.g. "dynamic.special".
            props["dynamicActionDescriptions"] = (
                {
                    dyn.name: dyn.get_properties()
                    for dyn in self._dynamic_actions.values()
                }
                if self._dynamic_actions
                else {}
            )

            # Device event descriptions (§4.7) — always present for
            # SingleDevice, even if empty.
            # Key = event name, e.g. "customAlert".
            props["deviceEventDescriptions"] = (
                {
                    evt.name: evt.get_description_properties()
                    for evt in self._device_events.values()
                }
                if self._device_events
                else {}
            )

            # Device state descriptions & values (§4.6.1 / §4.6.2).
            # Key = state name, e.g. "operatingState".
            props["deviceStateDescriptions"] = (
                {
                    st.name: st.get_description_properties()
                    for st in self._device_states.values()
                }
                if self._device_states
                else {}
            )
            props["deviceStates"] = (
                {
                    st.name: st.get_state_properties()
                    for st in self._device_states.values()
                }
                if self._device_states
                else {}
            )

            # Device property descriptions & values (§4.6.3 / §4.6.4).
            # Key = property name, e.g. "eventCounter".
            props["devicePropertyDescriptions"] = (
                {
                    prop.name: prop.get_description_properties()
                    for prop in self._device_properties.values()
                }
                if self._device_properties
                else {}
            )
            props["deviceProperties"] = (
                {
                    prop.name: prop.get_value_properties()
                    for prop in self._device_properties.values()
                }
                if self._device_properties
                else {}
            )

        # Output component properties (§4.8).
        if self._output is not None:
            props["outputDescription"] = self._output.get_description_properties()
            props["outputSettings"] = self._output.get_settings_properties()
            props["outputState"] = self._output.get_state_properties()

            # Channel properties (§4.9 / §4.1.3).
            # Each sub-tree is a single PropertyElement whose children are
            # keyed by channel name (e.g. "brightness", "shadePositionOutside").
            ch_desc = self._output.get_channel_descriptions()
            if ch_desc:
                props["channelDescriptions"] = ch_desc
                props["channelSettings"] = self._output.get_channel_settings()
                props["channelStates"] = self._output.get_channel_states()

            # Scene properties (§4.1.4 / §4.10).
            if ch_desc:
                props["scenes"] = self._output.get_scene_properties()

        # Control values (volatile runtime state from dSS, §4.11).
        if self._control_values:
            props["controlValues"] = {
                name: dict(entry) for name, entry in self._control_values.items()
            }

        return props

    # ---- property tree (for YAML persistence) ------------------------

    def get_property_tree(self) -> dict[str, Any]:
        """Return the vdSD data for inclusion in the Device's persisted
        property tree.

        The structure is::

            subdeviceIndex: 0
            dSUID: "..."
            primaryGroup: 1
            name: "Kitchen Light"
            ...
            modelFeatures:
              - blink
              - identification
            zoneID: 0
        """
        node: dict[str, Any] = {
            "subdeviceIndex": self._subdevice_index,
            "dSUID": str(self._dsuid),
            "primaryGroup": int(self._primary_group),
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
            "zoneID": self.zone_id,
            "progMode": self.prog_mode,
            "currentConfigId": self.current_config_id,
        }
        if self._configurations:
            node["configurations"] = list(self._configurations)
        if self._model_features:
            node["modelFeatures"] = sorted(self._model_features)

        # Button inputs (description + settings; state is volatile).
        if self._button_inputs:
            node["buttonInputs"] = [
                btn.get_property_tree() for btn in self._button_inputs.values()
            ]

        # Binary inputs (description + settings; state is volatile).
        if self._binary_inputs:
            node["binaryInputs"] = [
                bi.get_property_tree() for bi in self._binary_inputs.values()
            ]

        # Sensor inputs (description + settings; state is volatile).
        if self._sensor_inputs:
            node["sensorInputs"] = [
                si.get_property_tree() for si in self._sensor_inputs.values()
            ]

        # Device events (description only; events are stateless).
        if self._device_events:
            node["deviceEvents"] = [
                evt.get_property_tree() for evt in self._device_events.values()
            ]

        # Device states (description only; state values are volatile).
        if self._device_states:
            node["deviceStates"] = [
                st.get_property_tree() for st in self._device_states.values()
            ]

        # Device properties (description + value; both persisted).
        if self._device_properties:
            node["deviceProperties"] = [
                prop.get_property_tree() for prop in self._device_properties.values()
            ]

        # Action descriptions (§4.5.2) — template actions, persisted.
        if self._action_descriptions:
            node["actionDescriptions"] = [
                desc.get_property_tree() for desc in self._action_descriptions.values()
            ]

        # Standard actions (§4.5.3) — static, persisted.
        if self._standard_actions:
            node["standardActions"] = [
                std.get_property_tree() for std in self._standard_actions.values()
            ]

        # Custom actions (§4.5.3) — user-configured, persisted.
        if self._custom_actions:
            node["customActions"] = [
                cust.get_property_tree() for cust in self._custom_actions.values()
            ]

        # NOTE: Dynamic actions are transient and NOT persisted.

        # Output (description + settings; state is volatile).
        if self._output is not None:
            node["output"] = self._output.get_property_tree()

        return node

    # ---- state restoration -------------------------------------------

    def _apply_state(self, state: dict[str, Any]) -> None:
        """Apply a persisted state dict to this vdSD's properties.

        Auto-save is suppressed during restoration.
        """
        prev = self._auto_save_enabled
        self._auto_save_enabled = False
        try:
            if "dSUID" in state:
                self._dsuid = DsUid.from_string(state["dSUID"])
            if "subdeviceIndex" in state:
                self._subdevice_index = int(state["subdeviceIndex"])
            if "primaryGroup" in state:
                self._primary_group = ColorGroup(int(state["primaryGroup"]))
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
            if "zoneID" in state and state["zoneID"] is not None:
                self.zone_id = int(state["zoneID"])
            if "modelFeatures" in state:
                self._model_features = set(state["modelFeatures"])
            if "progMode" in state:
                val = state["progMode"]
                self.prog_mode = bool(val) if val is not None else None
            if "currentConfigId" in state:
                self.current_config_id = state["currentConfigId"]
            if "configurations" in state:
                self._configurations = list(state["configurations"])

            # Restore button inputs.
            if "buttonInputs" in state:
                from pydsvdcapi.button_input import ButtonInput

                for btn_state in state["buttonInputs"]:
                    idx = btn_state.get("dsIndex", 0)
                    btn = self._button_inputs.get(idx)
                    if btn is None:
                        btn = ButtonInput(
                            vdsd=self,
                            ds_index=idx,
                        )
                        self._button_inputs[idx] = btn
                    btn._apply_state(btn_state)

            # Restore binary inputs.
            if "binaryInputs" in state:
                from pydsvdcapi.binary_input import BinaryInput

                for bi_state in state["binaryInputs"]:
                    idx = bi_state.get("dsIndex", 0)
                    bi = self._binary_inputs.get(idx)
                    if bi is None:
                        bi = BinaryInput(
                            vdsd=self,
                            ds_index=idx,
                        )
                        self._binary_inputs[idx] = bi
                    bi._apply_state(bi_state)

            # Restore sensor inputs.
            if "sensorInputs" in state:
                from pydsvdcapi.sensor_input import SensorInput

                for si_state in state["sensorInputs"]:
                    idx = si_state.get("dsIndex", 0)
                    si = self._sensor_inputs.get(idx)
                    if si is None:
                        si = SensorInput._restore(
                            vdsd=self,
                            ds_index=idx,
                        )
                        self._sensor_inputs[idx] = si
                    si._apply_state(si_state)

            # Restore device events.
            if "deviceEvents" in state:
                from pydsvdcapi.device_event import DeviceEvent

                for evt_state in state["deviceEvents"]:
                    idx = evt_state.get("dsIndex", 0)
                    evt = self._device_events.get(idx)
                    if evt is None:
                        evt = DeviceEvent(
                            vdsd=self,
                            ds_index=idx,
                        )
                        self._device_events[idx] = evt
                    evt._apply_state(evt_state)

            # Restore device states.
            if "deviceStates" in state:
                from pydsvdcapi.device_state import DeviceState

                for st_state in state["deviceStates"]:
                    idx = st_state.get("dsIndex", 0)
                    st = self._device_states.get(idx)
                    if st is None:
                        st = DeviceState(
                            vdsd=self,
                            ds_index=idx,
                        )
                        self._device_states[idx] = st
                    st._apply_state(st_state)

            # Restore device properties.
            if "deviceProperties" in state:
                from pydsvdcapi.device_property import DeviceProperty

                for prop_state in state["deviceProperties"]:
                    idx = prop_state.get("dsIndex", 0)
                    prop = self._device_properties.get(idx)
                    if prop is None:
                        prop = DeviceProperty(
                            vdsd=self,
                            ds_index=idx,
                        )
                        self._device_properties[idx] = prop
                    prop._apply_state(prop_state)

            # Restore action descriptions (§4.5.2).
            if "actionDescriptions" in state:
                from pydsvdcapi.actions import DeviceActionDescription

                for desc_state in state["actionDescriptions"]:
                    idx = desc_state.get("dsIndex", 0)
                    desc = self._action_descriptions.get(idx)
                    if desc is None:
                        desc = DeviceActionDescription(
                            vdsd=self,
                            ds_index=idx,
                        )
                        self._action_descriptions[idx] = desc
                    desc._apply_state(desc_state)

            # Restore standard actions (§4.5.3).
            if "standardActions" in state:
                from pydsvdcapi.actions import StandardAction

                for std_state in state["standardActions"]:
                    idx = std_state.get("dsIndex", 0)
                    std = self._standard_actions.get(idx)
                    if std is None:
                        std = StandardAction(
                            vdsd=self,
                            ds_index=idx,
                        )
                        self._standard_actions[idx] = std
                    std._apply_state(std_state)

            # Restore custom actions (§4.5.3).
            if "customActions" in state:
                from pydsvdcapi.actions import CustomAction

                for cust_state in state["customActions"]:
                    idx = cust_state.get("dsIndex", 0)
                    cust = self._custom_actions.get(idx)
                    if cust is None:
                        cust = CustomAction(
                            vdsd=self,
                            ds_index=idx,
                        )
                        self._custom_actions[idx] = cust
                    cust._apply_state(cust_state)

            # NOTE: Dynamic actions are transient — not restored.

            # Restore output.
            if "output" in state:
                from pydsvdcapi.output import Output

                out_state = state["output"]
                if self._output is None:
                    self._output = Output(
                        vdsd=self,
                        name=out_state.get("name") or "output",
                        function=out_state.get("function", 0),
                        default_group=out_state.get("defaultGroup", 0),
                        active_group=out_state.get("activeGroup", 0),
                        groups=set(out_state.get("groups") or []),
                    )
                self._output._apply_state(out_state)
        finally:
            self._auto_save_enabled = prev

    # ---- announcement ------------------------------------------------

    async def _wait_for_initial_values(self, timeout: float = 61.0) -> None:
        """Wait until every value-bearing component has reported its first value.

        Raises
        ------
        RuntimeError
            If *timeout* seconds elapse before all components have provided
            an initial value, with a message listing which ones are missing.
        """
        import asyncio

        pending: list[tuple[str, asyncio.Event]] = []

        if self._output is not None:
            for ch in self._output._channels.values():
                if not ch._initial_value_ready.is_set():
                    pending.append(
                        (
                            f"OutputChannel[{ch.ds_index}] '{ch.name}'",
                            ch._initial_value_ready,
                        )
                    )

        for si in self._sensor_inputs.values():
            if not si._initial_value_ready.is_set():
                pending.append(
                    (
                        f"SensorInput[{si.ds_index}]",
                        si._initial_value_ready,
                    )
                )

        for st in self._device_states.values():
            if not st._initial_value_ready.is_set():
                pending.append(
                    (
                        f"DeviceState '{st.name}'",
                        st._initial_value_ready,
                    )
                )

        for prop in self._device_properties.values():
            if not prop._initial_value_ready.is_set():
                pending.append(
                    (
                        f"DeviceProperty '{prop.name}'",
                        prop._initial_value_ready,
                    )
                )

        if not pending:
            return

        logger.info(
            "vdSD '%s': waiting up to %.0fs for initial values from: %s",
            self.name,
            timeout,
            ", ".join(label for label, _ in pending),
        )

        try:
            await asyncio.wait_for(
                asyncio.gather(*[ev.wait() for _, ev in pending]),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            still_missing = [label for label, ev in pending if not ev.is_set()]
            raise RuntimeError(
                f"vdSD '{self.name}': timed out after {timeout:.0f}s waiting "
                f"for initial values. The following components did not report: "
                f"{', '.join(still_missing)}"
            ) from None

    async def announce(self, session: VdcSession) -> bool:
        """Announce this vdSD to the connected vdSM.

        Sends ``VDC_SEND_ANNOUNCE_DEVICE`` with this vdSD's dSUID
        and the containing vDC's dSUID, then awaits ``GENERIC_RESPONSE``.

        This method should normally be called via :meth:`Device.announce`
        rather than directly.

        Returns
        -------
        bool
            ``True`` if the vdSM accepted the announcement.
        """
        # Wait for all value-bearing components to have an initial value.
        await self._wait_for_initial_values()

        # Auto-derive modelFeatures if the caller has not yet called
        # derive_model_features() or remove_model_feature().
        if not self._features_derived:
            self.derive_model_features()

        vdc = self._device.vdc
        msg = pb.Message()
        msg.type = pb.VDC_SEND_ANNOUNCE_DEVICE
        msg.vdc_send_announce_device.dSUID = str(self._dsuid)
        msg.vdc_send_announce_device.vdc_dSUID = str(vdc.dsuid)

        logger.info(
            "Announcing vdSD '%s' (dSUID %s, vdc %s)",
            self.name,
            self._dsuid,
            vdc.dsuid,
        )

        response = await session.send_request(msg)

        code = response.generic_response.code
        if code == pb.ERR_OK:
            self._announced = True
            self._session = session
            # Start session hooks for all button inputs.
            for btn in self._button_inputs.values():
                btn.start_alive_timer(session)
            # Start alive timers for all binary inputs.
            for bi in self._binary_inputs.values():
                bi.start_alive_timer(session)
            # Start alive timers for all sensor inputs.
            for si in self._sensor_inputs.values():
                si.start_alive_timer(session)
            # Push initial state for inputs that already have a value
            # (mirrors vdSMAnnouncementAcknowledged in p44vdc device.cpp).
            for si in self._sensor_inputs.values():
                if si.value is not None:
                    await si._push_state(session, force=True)
            for bi in self._binary_inputs.values():
                if bi.value is not None or bi.extended_value is not None:
                    await bi._push_state(session, force=True)
            # Start session for output.
            if self._output is not None:
                self._output.start_session(session)
            logger.info("vdSD '%s' announced successfully", self.name)
            return True

        description = response.generic_response.description
        logger.warning(
            "vdSD '%s' announcement failed: code=%s description=%s",
            self.name,
            pb.ResultCode.Name(code),
            description,
        )
        self._announced = False
        return False

    async def vanish(self, session: VdcSession) -> None:
        """Notify the vdSM that this vdSD has vanished.

        Sends ``VDC_SEND_VANISH`` as a notification (no response
        expected).  The vdSD is marked as unannounced after sending.
        """
        msg = pb.Message()
        msg.type = pb.VDC_SEND_VANISH
        msg.vdc_send_vanish.dSUID = str(self._dsuid)
        await session.send_notification(msg)
        self._announced = False
        self._session = None
        # Stop session hooks for all button inputs.
        for btn in self._button_inputs.values():
            btn.stop_alive_timer()
        # Stop alive timers for all binary inputs.
        for bi in self._binary_inputs.values():
            bi.stop_alive_timer()
        # Stop alive timers for all sensor inputs.
        for si in self._sensor_inputs.values():
            si.stop_alive_timer()
        # Stop session for output.
        if self._output is not None:
            self._output.stop_session()
        logger.info("vdSD '%s' vanished (dSUID %s)", self.name, self._dsuid)

    def reset_announcement(self) -> None:
        """Mark this vdSD as unannounced (e.g. on session disconnect)."""
        self._announced = False
        self._session = None
        # Stop session hooks for all button inputs.
        for btn in self._button_inputs.values():
            btn.stop_alive_timer()
        # Stop alive timers for all binary inputs.
        for bi in self._binary_inputs.values():
            bi.stop_alive_timer()
        # Stop alive timers for all sensor inputs.
        for si in self._sensor_inputs.values():
            si.stop_alive_timer()
        # Stop session for output.
        if self._output is not None:
            self._output.stop_session()

    # ---- dunder -------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Vdsd(dsuid={self._dsuid!r}, "
            f"primary_group={self._primary_group!r}, "
            f"name={self.name!r})"
        )


# ---------------------------------------------------------------------------
# Device — physical hardware wrapper
# ---------------------------------------------------------------------------


class Device:
    """Represents a single physical hardware device.

    A Device groups one or more :class:`Vdsd` instances that share the
    same base dSUID (bytes 0-15).  The Device is the unit of
    announcement and update — it ensures that:

    * All contained Vdsd instances are announced or vanished together.
    * Structural changes (adding/removing vdSDs) are done atomically
      via a vanish→modify→re-announce cycle.
    * Persistence is handled centrally through the Vdc/VdcHost chain.

    Parameters
    ----------
    vdc:
        The owning :class:`Vdc`.
    dsuid:
        The base dSUID for this device.  Individual vdSDs will derive
        their dSUIDs from this base using ``derive_subdevice(index)``.
        For single-vdSD devices, the default sub-device index 0 is
        used directly.
    """

    def __init__(self, *, vdc: Vdc, dsuid: DsUid) -> None:
        self._vdc: Vdc = vdc
        # Store the device-level base dSUID (sub-device index 0).
        self._dsuid: DsUid = dsuid.device_base()
        # Ordered list preserving insertion order.
        self._vdsds: dict[int, Vdsd] = {}  # keyed by subdevice_index
        self._announced: bool = False
        # Required-callbacks manifest set by DeviceTemplate.instantiate().
        # None means no template was used; an empty dict means all callbacks
        # were already satisfied at template instantiation time.
        self._required_callbacks: dict[str, None] | None = None

    # ---- accessors ---------------------------------------------------

    @property
    def vdc(self) -> Vdc:
        """The owning :class:`Vdc`."""
        return self._vdc

    @property
    def dsuid(self) -> DsUid:
        """The base dSUID (sub-device index 0) for this device."""
        return self._dsuid

    @property
    def vdsds(self) -> dict[int, Vdsd]:
        """All contained Vdsd instances keyed by sub-device index."""
        return dict(self._vdsds)

    @property
    def is_announced(self) -> bool:
        """``True`` if all vdSDs have been announced."""
        return self._announced

    # ---- auto-save ---------------------------------------------------

    def _schedule_auto_save(self) -> None:
        """Forward auto-save request up through the Vdc → VdcHost chain."""
        self._vdc._schedule_auto_save()

    # ---- vdSD management ---------------------------------------------

    def add_vdsd(self, vdsd: Vdsd) -> None:
        """Register a :class:`Vdsd` with this device.

        The vdSD is indexed by its sub-device index.  Adding a vdSD
        with a sub-device index that already exists replaces the
        previous one.

        Raises
        ------
        RuntimeError
            If the device is currently announced.  Use :meth:`update`
            to change structure after announcement.
        ValueError
            If the vdSD's base dSUID does not match this device.
        """
        if self._announced:
            raise RuntimeError(
                "Cannot add vdSD to an announced device.  "
                "Use device.update() to modify structure after "
                "announcement."
            )
        if not vdsd.dsuid.same_device(self._dsuid):
            raise ValueError(
                f"vdSD dSUID {vdsd.dsuid} does not share the same "
                f"base as device dSUID {self._dsuid}"
            )
        idx = vdsd.subdevice_index
        self._vdsds[idx] = vdsd
        logger.debug(
            "Added vdSD '%s' (sub-device %d) to device %s",
            vdsd.name,
            idx,
            self._dsuid,
        )

    def remove_vdsd(self, subdevice_index: int) -> Vdsd | None:
        """Remove a vdSD by sub-device index.

        Returns the removed :class:`Vdsd` or ``None``.

        Raises
        ------
        RuntimeError
            If the device is currently announced.
        """
        if self._announced:
            raise RuntimeError(
                "Cannot remove vdSD from an announced device.  "
                "Use device.update() to modify structure after "
                "announcement."
            )
        return self._vdsds.pop(subdevice_index, None)

    def get_vdsd(self, subdevice_index: int) -> Vdsd | None:
        """Look up a vdSD by sub-device index."""
        return self._vdsds.get(subdevice_index)

    def get_vdsd_by_dsuid(self, dsuid: DsUid) -> Vdsd | None:
        """Look up a vdSD by its full dSUID."""
        dsuid_str = str(dsuid)
        for vdsd in self._vdsds.values():
            if str(vdsd.dsuid) == dsuid_str:
                return vdsd
        return None

    # ---- announcement ------------------------------------------------

    def _check_required_callbacks(self) -> list[str]:
        """Return a list of required-callback paths that are still unset.

        Only called when ``self._required_callbacks`` is not ``None``
        (i.e. the device was created from a template).
        """
        vdsds_by_index = {idx: vdsd for idx, vdsd in enumerate(self._vdsds.values())}
        missing: list[str] = []
        for path in self._required_callbacks or {}:
            # Parse path: "vdsds[N].attr" or "vdsds[N].output.attr"
            if path.startswith("vdsds["):
                # Extract index and remainder.
                bracket_end = path.index("]")
                idx = int(path[6:bracket_end])
                remainder = path[bracket_end + 2 :]  # skip "]."
                vdsd = vdsds_by_index.get(idx)
                if vdsd is None:
                    missing.append(path)
                    continue
                if "." in remainder:
                    # e.g. "output.on_channel_applied"
                    component_name, attr = remainder.split(".", 1)
                    component = getattr(vdsd, f"_{component_name}", None)
                    if component is None:
                        missing.append(path)
                        continue
                    if getattr(component, attr, None) is None:
                        missing.append(path)
                else:
                    if getattr(vdsd, remainder, None) is None:
                        missing.append(path)
        return missing

    async def announce(self, session: VdcSession) -> int:
        """Announce all contained vdSDs to the vdSM.

        Call this only when all components (inputs, outputs, etc.) of
        every vdSD have been fully defined.  The dSS does not handle
        structural updates gracefully — use :meth:`update` to modify
        an already-announced device.

        Returns
        -------
        int
            Number of vdSDs successfully announced.

        Raises
        ------
        RuntimeError
            If the device has no vdSDs or is already announced.
        """
        if not self._vdsds:
            raise RuntimeError("Cannot announce a device with no vdSDs")
        if self._announced:
            raise RuntimeError(
                "Device is already announced.  "
                "Use device.update() to re-announce after changes."
            )

        # If this device was created from a template, verify that all
        # required callbacks have been set before we send any protobuf.
        if self._required_callbacks is not None:
            missing = self._check_required_callbacks()
            if missing:
                from pydsvdcapi.device_template import AnnouncementNotReadyError

                raise AnnouncementNotReadyError(missing)

        # Register with the parent VDC so the device is persisted and
        # visible to vdc.announce_devices() on reconnect.  Idempotent.
        self._vdc.add_device(self)

        count = 0
        for vdsd in self._vdsds.values():
            try:
                ok = await vdsd.announce(session)
                if ok:
                    count += 1
            except Exception:  # noqa: BLE001
                logger.exception("Failed to announce vdSD '%s'", vdsd.name)

        self._announced = count == len(self._vdsds)
        logger.info(
            "Device %s: announced %d/%d vdSDs",
            self._dsuid,
            count,
            len(self._vdsds),
        )
        return count

    async def vanish(self, session: VdcSession) -> None:
        """Notify the vdSM that all vdSDs of this device have vanished.

        Sends ``VDC_SEND_VANISH`` for each announced vdSD.
        """
        for vdsd in self._vdsds.values():
            if vdsd.is_announced:
                try:
                    await vdsd.vanish(session)
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to vanish vdSD '%s'", vdsd.name)
        self._announced = False
        logger.info("Device %s: all vdSDs vanished", self._dsuid)

    async def update(
        self,
        session: VdcSession,
        modify: Callable[[Device], None],
    ) -> int:
        """Vanish, apply structural changes, and re-announce.

        This is the **only** safe way to change normally immutable
        properties or the set of vdSDs after a device has been
        announced.  The dSS cannot handle in-place structural updates,
        so the device must vanish first.

        Parameters
        ----------
        session:
            The active session.
        modify:
            A callback that receives this :class:`Device` with all
            vdSDs in unannounced state.  Add, remove, or reconfigure
            vdSDs inside this callback.

        Returns
        -------
        int
            Number of vdSDs successfully re-announced.

        Example::

            def reconfigure(dev: Device):
                dev.get_vdsd(0).name = "Updated Name"
                dev.add_vdsd(Vdsd(device=dev, subdevice_index=2,
                                  primary_group=ColorGroup.GREY))

            await device.update(session, reconfigure)
        """
        # Step 1: Vanish all currently announced vdSDs.
        if self._announced:
            await self.vanish(session)

        # Step 2: Mark as unannounced to allow structural modifications.
        self._announced = False

        # Step 3: Let the caller modify the device.
        modify(self)

        # Step 4: Re-announce.
        count = await self.announce(session)

        # Step 5: Trigger persistence so the new structure is saved.
        self._vdc._schedule_auto_save()

        return count

    def reset_announcement(self) -> None:
        """Reset announcement state for this device and all vdSDs.

        Called by the vDC when the session ends.
        """
        for vdsd in self._vdsds.values():
            vdsd.reset_announcement()
        self._announced = False

    # ---- persistence -------------------------------------------------

    def get_template_tree(self) -> dict[str, Any]:
        """Return the Device data stripped of instance-specific fields,
        suitable for saving as a device template.

        Strips ``baseDsUID`` at the Device level, and ``dSUID``, ``name``,
        ``zoneID`` from each vdSD.  All structural and semantic fields
        (model features, components, converters, etc.) are retained.

        The returned tree can be passed directly to
        :func:`~pydsvdcapi.device_template.strip_instance_fields` (which
        this method calls internally).
        """
        from pydsvdcapi.device_template import strip_instance_fields

        return strip_instance_fields(self.get_property_tree())

    def get_property_tree(self) -> dict[str, Any]:
        """Return the Device data for inclusion in the Vdc's persisted
        property tree.

        Structure::

            baseDsUID: "..."
            vdsds:
              - subdeviceIndex: 0
                dSUID: "..."
                ...
              - subdeviceIndex: 2
                dSUID: "..."
                ...
        """
        return {
            "baseDsUID": str(self._dsuid),
            "vdsds": [vdsd.get_property_tree() for vdsd in self._vdsds.values()],
        }

    def _apply_state(self, state: dict[str, Any]) -> None:
        """Restore Device state from a persisted dict.

        Creates Vdsd instances for any entries in ``vdsds`` that do
        not already exist.  Existing vdSDs matched by sub-device
        index are updated in-place.
        """
        if "baseDsUID" in state:
            self._dsuid = DsUid.from_string(state["baseDsUID"]).device_base()

        for vdsd_state in state.get("vdsds", []):
            idx = vdsd_state.get("subdeviceIndex", 0)
            vdsd = self._vdsds.get(idx)
            if vdsd is None:
                # Create a new Vdsd for this persisted entry.
                primary_group = ColorGroup(
                    vdsd_state.get("primaryGroup", ColorGroup.BLACK)
                )
                vdsd = Vdsd(
                    device=self,
                    subdevice_index=idx,
                    primary_group=primary_group,
                    name=vdsd_state.get("name") or f"Device {idx}",
                    model=vdsd_state.get("model") or "Restored vdSD",
                )
                self._vdsds[idx] = vdsd
            vdsd._apply_state(vdsd_state)

    # ---- dunder -------------------------------------------------------

    def __repr__(self) -> str:
        n = len(self._vdsds)
        return f"Device(dsuid={self._dsuid!r}, vdsds={n})"
