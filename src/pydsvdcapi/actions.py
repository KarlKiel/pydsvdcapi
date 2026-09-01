# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024–2026 Arne Speck
"""Device action components for vdSD devices (§4.5).

This module implements the action-related components that a virtual
device can define:

* **deviceActionDescriptions** — read-only invariable template
  descriptions (§4.5.2).  Each template defines an action name,
  optional parameter descriptors, and an optional description.
  These serve as the basis for standard, custom, and dynamic actions.

* **standardActions** — static and immutable actions defined by
  the device (§4.5.3).  Each references a template action and may
  override specific parameter values.  Names always start with
  ``"std."``.

* **customActions** — user-configurable actions that can be created
  and modified via the API (§4.5.3).  These are persistently stored.
  Names always start with ``"custom."``.

* **dynamicDeviceActions** — actions created/managed on the native
  device side (§4.5.3).  They can appear, change, or disappear based
  on device interaction.  Names always start with ``"dynamic."``.

Parameter Objects (§4.5.1)
~~~~~~~~~~~~~~~~~~~~~~~~~~

Action templates can define parameters via :class:`ActionParameter`
objects.  Each parameter has a type (``"numeric"``, ``"enumeration"``,
or ``"string"``), optional constraints (min/max/resolution/siunit),
optional enumeration options, and an optional default value.

Invoking Actions (§7.3.10)
~~~~~~~~~~~~~~~~~~~~~~~~~~

The vdSM invokes actions via ``VDSM_REQUEST_GENERIC_REQUEST`` with
``methodname="invokeDeviceAction"``.  The ``id`` parameter in the
``params`` identifies the action to execute, and optional extra
``params`` entries carry parameter values.

Persistence
~~~~~~~~~~~

* Template descriptions, standard actions: persisted (via property tree).
* Custom actions: persisted (user-configured, stored in YAML).
* Dynamic actions: transient — recreated by the device after restart.

Usage::

    from pydsvdcapi.actions import (
        ActionParameter, DeviceActionDescription,
        StandardAction, CustomAction, DynamicAction,
    )

    # Define a template action with parameters
    param = ActionParameter(
        name="volume", type="numeric",
        min_value=0, max_value=100, default=50.0,
    )
    tmpl = DeviceActionDescription(
        vdsd=my_vdsd, ds_index=0, name="play",
        params=[param], description="Play media on the device",
    )
    my_vdsd.add_device_action_description(tmpl)

    # Define a standard action based on the template
    std = StandardAction(
        vdsd=my_vdsd, ds_index=0, name="std.play",
        action="play", params={"volume": 80},
    )
    my_vdsd.add_standard_action(std)

    # Define a custom action
    cust = CustomAction(
        vdsd=my_vdsd, ds_index=0, name="custom.play-loud",
        action="play", title="Play Loud", params={"volume": 100},
    )
    my_vdsd.add_custom_action(cust)

    # Define a dynamic action
    dyn = DynamicAction(
        vdsd=my_vdsd, ds_index=0, name="dynamic.special",
        title="Special Mode",
    )
    my_vdsd.add_dynamic_action(dyn)
"""

from __future__ import annotations

import logging
from typing import (
    TYPE_CHECKING,
    Any,
)

if TYPE_CHECKING:
    from pydsvdcapi.vdsd import Vdsd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ActionParameter — one parameter descriptor (§4.5.1)
# ---------------------------------------------------------------------------


class ActionParameter:
    """One parameter descriptor within a device action template (§4.5.1).

    Parameters
    ----------
    name:
        The parameter name (used as the property-element key within
        the ``params`` container of the parent action description).
    type:
        Data type: ``"numeric"``, ``"enumeration"``, or ``"string"``.
    min_value:
        Minimum value (numeric only).
    max_value:
        Maximum value (numeric only).
    resolution:
        Resolution / LSB size (numeric only).
    siunit:
        SI unit string, e.g. ``"°C"`` (numeric only).
    options:
        Option key → label mapping (enumeration only).
    default:
        Default value (all types).
    """

    __slots__ = (
        "_name",
        "_type",
        "_min_value",
        "_max_value",
        "_resolution",
        "_siunit",
        "_options",
        "_default",
    )

    def __init__(
        self,
        name: str = "",
        type: str = "string",
        min_value: float | None = None,
        max_value: float | None = None,
        resolution: float | None = None,
        siunit: str | None = None,
        options: dict[int | str, str] | None = None,
        default: float | str | None = None,
    ) -> None:
        self._name = name
        self._type = type
        self._min_value = min_value
        self._max_value = max_value
        self._resolution = resolution
        self._siunit = siunit
        self._options: dict[int | str, str] | None = dict(options) if options else None
        self._default = default

    # ---- accessors ---------------------------------------------------

    @property
    def name(self) -> str:
        """Parameter name."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def type(self) -> str:
        """Data type identifier."""
        return self._type

    @type.setter
    def type(self, value: str) -> None:
        self._type = value

    @property
    def min_value(self) -> float | None:
        """Minimum value (numeric only)."""
        return self._min_value

    @min_value.setter
    def min_value(self, value: float | None) -> None:
        self._min_value = value

    @property
    def max_value(self) -> float | None:
        """Maximum value (numeric only)."""
        return self._max_value

    @max_value.setter
    def max_value(self, value: float | None) -> None:
        self._max_value = value

    @property
    def resolution(self) -> float | None:
        """Resolution / LSB size (numeric only)."""
        return self._resolution

    @resolution.setter
    def resolution(self, value: float | None) -> None:
        self._resolution = value

    @property
    def siunit(self) -> str | None:
        """SI unit string (numeric only)."""
        return self._siunit

    @siunit.setter
    def siunit(self, value: str | None) -> None:
        self._siunit = value

    @property
    def options(self) -> dict[int | str, str] | None:
        """Option key → label mapping (enumeration only, copy)."""
        return dict(self._options) if self._options is not None else None

    @options.setter
    def options(self, value: dict[int | str, str] | None) -> None:
        self._options = dict(value) if value is not None else None

    @property
    def default(self) -> float | str | None:
        """Default value."""
        return self._default

    @default.setter
    def default(self, value: float | str | None) -> None:
        self._default = value

    # ---- property generation -----------------------------------------

    def get_properties(self) -> dict[str, Any]:
        """Return the parameter descriptor dict (§4.5.1).

        Format::

            {"type": "numeric", "min": 0, "max": 100, "default": 50}

        The parameter name is **not** included here — it serves as the
        key in the parent ``params`` mapping.
        """
        props: dict[str, Any] = {"type": self._type}
        if self._type == "numeric":
            if self._min_value is not None:
                props["min"] = self._min_value
            if self._max_value is not None:
                props["max"] = self._max_value
            if self._resolution is not None:
                props["resolution"] = self._resolution
            if self._siunit is not None:
                props["siunit"] = self._siunit
        if self._type == "enumeration" and self._options:
            props["options"] = {str(k): v for k, v in self._options.items()}
        if self._default is not None:
            props["default"] = self._default
        return props

    # ---- persistence -------------------------------------------------

    def get_property_tree(self) -> dict[str, Any]:
        """Return a dict suitable for YAML persistence."""
        node: dict[str, Any] = {
            "name": self._name,
            "type": self._type,
        }
        if self._min_value is not None:
            node["minValue"] = self._min_value
        if self._max_value is not None:
            node["maxValue"] = self._max_value
        if self._resolution is not None:
            node["resolution"] = self._resolution
        if self._siunit is not None:
            node["siunit"] = self._siunit
        if self._options is not None:
            node["options"] = {str(k): v for k, v in self._options.items()}
        if self._default is not None:
            node["default"] = self._default
        return node

    @classmethod
    def from_persisted(cls, data: dict[str, Any]) -> ActionParameter:
        """Restore an ActionParameter from a persisted dict."""
        options_raw = data.get("options")
        options = None
        if isinstance(options_raw, dict):
            options = {_parse_option_key(k): v for k, v in options_raw.items()}
        return cls(
            name=data.get("name", ""),
            type=data.get("type", "string"),
            min_value=(float(data["minValue"]) if "minValue" in data else None),
            max_value=(float(data["maxValue"]) if "maxValue" in data else None),
            resolution=(float(data["resolution"]) if "resolution" in data else None),
            siunit=data.get("siunit"),
            options=options,
            default=data.get("default"),
        )

    # ---- repr --------------------------------------------------------

    def __repr__(self) -> str:
        return f"ActionParameter(name={self._name!r}, type={self._type!r})"


# ---------------------------------------------------------------------------
# DeviceActionDescription — one template action (§4.5.2)
# ---------------------------------------------------------------------------


class DeviceActionDescription:
    """One action template on a vdSD (§4.5.2).

    Action descriptions describe basic functionalities and operation
    processes of a device.  They serve as a template to create custom
    defined actions as variations with modified parameter sets.

    Parameters
    ----------
    vdsd:
        The owning :class:`~pydsvdcapi.vdsd.Vdsd` instance.
    ds_index:
        Numeric index of this action description within the device
        (position in ``deviceActionDescriptions``).
    name:
        Action template name (e.g. ``"play"``).
    params:
        Optional list of :class:`ActionParameter` descriptors.
    description:
        Optional human-readable description.
    """

    __slots__ = (
        "_vdsd",
        "_ds_index",
        "_name",
        "_params",
        "_description",
    )

    def __init__(
        self,
        vdsd: Vdsd,
        ds_index: int = 0,
        name: str = "",
        params: list[ActionParameter] | None = None,
        description: str | None = None,
    ) -> None:
        self._vdsd = vdsd
        self._ds_index = ds_index
        self._name = name
        self._params: list[ActionParameter] = list(params) if params else []
        self._description = description

    # ---- read-only accessors -----------------------------------------

    @property
    def vdsd(self) -> Vdsd:
        """The owning vdSD."""
        return self._vdsd

    @property
    def ds_index(self) -> int:
        """Numeric index within the device."""
        return self._ds_index

    # ---- configurable properties -------------------------------------

    @property
    def name(self) -> str:
        """Action template name (e.g. ``"play"``)."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def params(self) -> list[ActionParameter]:
        """Parameter descriptors (copy of the list)."""
        return list(self._params)

    @params.setter
    def params(self, value: list[ActionParameter]) -> None:
        self._params = list(value) if value else []

    @property
    def description(self) -> str | None:
        """Optional human-readable description."""
        return self._description

    @description.setter
    def description(self, value: str | None) -> None:
        self._description = value

    # ---- property generation -----------------------------------------

    def get_description_properties(self) -> dict[str, Any]:
        """Return **deviceActionDescriptions** properties (§4.5.2).

        Format::

            {"name": "play",
             "params": {"volume": {"type": "numeric", ...}},
             "description": "Play media"}

        The ``params`` dict is keyed by parameter name; each value is
        the parameter descriptor (§4.5.1) without the name itself.
        """
        props: dict[str, Any] = {"name": self._name}
        if self._params:
            props["params"] = {p.name: p.get_properties() for p in self._params}
        if self._description is not None:
            props["description"] = self._description
        return props

    # ---- persistence -------------------------------------------------

    def get_property_tree(self) -> dict[str, Any]:
        """Return a dict suitable for YAML persistence."""
        node: dict[str, Any] = {
            "dsIndex": self._ds_index,
            "name": self._name,
        }
        if self._params:
            node["params"] = [p.get_property_tree() for p in self._params]
        if self._description is not None:
            node["description"] = self._description
        return node

    def _apply_state(self, state: dict[str, Any]) -> None:
        """Restore from a persisted state dict."""
        if "name" in state:
            self._name = state["name"]
        if "params" in state:
            raw_params = state["params"]
            if isinstance(raw_params, list):
                self._params = [ActionParameter.from_persisted(p) for p in raw_params]
        if "description" in state:
            self._description = state.get("description")

    # ---- repr --------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"DeviceActionDescription(ds_index={self._ds_index!r}, name={self._name!r})"
        )


# ---------------------------------------------------------------------------
# StandardAction — one static action based on a template (§4.5.3)
# ---------------------------------------------------------------------------


class StandardAction:
    """One standard action on a vdSD (§4.5.3).

    Standard actions are static and immutable, defined by the device.
    Each references a template action (by name) and may override
    specific parameter values.

    Parameters
    ----------
    vdsd:
        The owning :class:`~pydsvdcapi.vdsd.Vdsd` instance.
    ds_index:
        Numeric index of this action within the device
        (position in ``standardActions``).
    name:
        Unique action ID, always prefixed ``"std."``.
    action:
        Name of the template action this standard action is based upon.
    params:
        Optional dict of parameter name → value overrides that differ
        from the template defaults.
    """

    __slots__ = (
        "_vdsd",
        "_ds_index",
        "_name",
        "_action",
        "_params",
    )

    def __init__(
        self,
        vdsd: Vdsd,
        ds_index: int = 0,
        name: str = "",
        action: str = "",
        params: dict[str, Any] | None = None,
    ) -> None:
        self._vdsd = vdsd
        self._ds_index = ds_index
        self._name = name
        self._action = action
        self._params: dict[str, Any] | None = dict(params) if params else None

    # ---- read-only accessors -----------------------------------------

    @property
    def vdsd(self) -> Vdsd:
        """The owning vdSD."""
        return self._vdsd

    @property
    def ds_index(self) -> int:
        """Numeric index within the device."""
        return self._ds_index

    # ---- configurable properties -------------------------------------

    @property
    def name(self) -> str:
        """Unique action ID (prefixed ``"std."``)."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def action(self) -> str:
        """Name of the template action."""
        return self._action

    @action.setter
    def action(self, value: str) -> None:
        self._action = value

    @property
    def params(self) -> dict[str, Any] | None:
        """Parameter name → value overrides (copy)."""
        return dict(self._params) if self._params is not None else None

    @params.setter
    def params(self, value: dict[str, Any] | None) -> None:
        self._params = dict(value) if value is not None else None

    # ---- property generation -----------------------------------------

    def get_properties(self) -> dict[str, Any]:
        """Return **standardActions** properties (§4.5.3).

        Format::

            {"name": "std.play", "action": "play",
             "params": {"volume": 80}}
        """
        props: dict[str, Any] = {
            "name": self._name,
            "action": self._action,
        }
        if self._params:
            props["params"] = dict(self._params)
        return props

    # ---- persistence -------------------------------------------------

    def get_property_tree(self) -> dict[str, Any]:
        """Return a dict suitable for YAML persistence."""
        node: dict[str, Any] = {
            "dsIndex": self._ds_index,
            "name": self._name,
            "action": self._action,
        }
        if self._params:
            node["params"] = dict(self._params)
        return node

    def _apply_state(self, state: dict[str, Any]) -> None:
        """Restore from a persisted state dict."""
        if "name" in state:
            self._name = state["name"]
        if "action" in state:
            self._action = state["action"]
        if "params" in state:
            raw = state["params"]
            self._params = dict(raw) if raw else None

    # ---- repr --------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"StandardAction(ds_index={self._ds_index!r}, "
            f"name={self._name!r}, action={self._action!r})"
        )


# ---------------------------------------------------------------------------
# CustomAction — one user-configurable action (§4.5.3)
# ---------------------------------------------------------------------------


class CustomAction:
    """One custom action on a vdSD (§4.5.3).

    Custom actions are configured by the user.  They can be created
    via the API and are persistently stored on the VDC.

    Parameters
    ----------
    vdsd:
        The owning :class:`~pydsvdcapi.vdsd.Vdsd` instance.
    ds_index:
        Numeric index within the device (position in ``customActions``).
    name:
        Unique action ID, always prefixed ``"custom."``.
    action:
        Reference name of the template action this custom action is
        based upon.
    title:
        Human-readable name (usually assigned by the user).
    params:
        Optional dict of parameter name → value overrides.
    """

    __slots__ = (
        "_vdsd",
        "_ds_index",
        "_name",
        "_action",
        "_title",
        "_params",
    )

    def __init__(
        self,
        vdsd: Vdsd,
        ds_index: int = 0,
        name: str = "",
        action: str = "",
        title: str = "",
        params: dict[str, Any] | None = None,
    ) -> None:
        self._vdsd = vdsd
        self._ds_index = ds_index
        self._name = name
        self._action = action
        self._title = title
        self._params: dict[str, Any] | None = dict(params) if params else None

    # ---- read-only accessors -----------------------------------------

    @property
    def vdsd(self) -> Vdsd:
        """The owning vdSD."""
        return self._vdsd

    @property
    def ds_index(self) -> int:
        """Numeric index within the device."""
        return self._ds_index

    # ---- configurable properties -------------------------------------

    @property
    def name(self) -> str:
        """Unique action ID (prefixed ``"custom."``)."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def action(self) -> str:
        """Reference name of the template action."""
        return self._action

    @action.setter
    def action(self, value: str) -> None:
        self._action = value

    @property
    def title(self) -> str:
        """Human-readable name."""
        return self._title

    @title.setter
    def title(self, value: str) -> None:
        self._title = value

    @property
    def params(self) -> dict[str, Any] | None:
        """Parameter name → value overrides (copy)."""
        return dict(self._params) if self._params is not None else None

    @params.setter
    def params(self, value: dict[str, Any] | None) -> None:
        self._params = dict(value) if value is not None else None

    # ---- property generation -----------------------------------------

    def get_properties(self) -> dict[str, Any]:
        """Return **customActions** properties (§4.5.3).

        Format::

            {"name": "custom.play-loud", "action": "play",
             "title": "Play Loud", "params": {"volume": 100}}
        """
        props: dict[str, Any] = {
            "name": self._name,
            "action": self._action,
            "title": self._title,
        }
        if self._params:
            props["params"] = dict(self._params)
        return props

    # ---- writable via setProperty ------------------------------------

    def apply_settings(self, settings: dict[str, Any]) -> None:
        """Apply writable settings from a ``setProperty`` request.

        Writable fields: ``action``, ``title``, ``params``.
        The ``name`` field is the unique identifier and is not
        overwritten here.
        """
        changed = False
        if "action" in settings:
            self._action = settings["action"]
            changed = True
        if "title" in settings:
            self._title = settings["title"]
            changed = True
        if "params" in settings:
            raw = settings["params"]
            self._params = dict(raw) if raw else None
            changed = True
        if changed:
            self._schedule_auto_save()

    def _schedule_auto_save(self) -> None:
        device = getattr(self._vdsd, "_device", None)
        if device is not None:
            device._schedule_auto_save()

    # ---- persistence -------------------------------------------------

    def get_property_tree(self) -> dict[str, Any]:
        """Return a dict suitable for YAML persistence."""
        node: dict[str, Any] = {
            "dsIndex": self._ds_index,
            "name": self._name,
            "action": self._action,
            "title": self._title,
        }
        if self._params:
            node["params"] = dict(self._params)
        return node

    def _apply_state(self, state: dict[str, Any]) -> None:
        """Restore from a persisted state dict."""
        if "name" in state:
            self._name = state["name"]
        if "action" in state:
            self._action = state["action"]
        if "title" in state:
            self._title = state["title"]
        if "params" in state:
            raw = state["params"]
            self._params = dict(raw) if raw else None

    # ---- repr --------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"CustomAction(ds_index={self._ds_index!r}, "
            f"name={self._name!r}, action={self._action!r}, "
            f"title={self._title!r})"
        )


# ---------------------------------------------------------------------------
# DynamicAction — one device-created action (§4.5.3)
# ---------------------------------------------------------------------------


class DynamicAction:
    """One dynamic device action on a vdSD (§4.5.3).

    Dynamic actions are created on the native device side.  They can
    be created, changed, or deleted by interaction on the device
    itself.  They are transient — not persisted across restarts.

    Parameters
    ----------
    vdsd:
        The owning :class:`~pydsvdcapi.vdsd.Vdsd` instance.
    ds_index:
        Numeric index within the device
        (position in ``dynamicDeviceActions``).
    name:
        Unique action ID, always prefixed ``"dynamic."``.
    title:
        Human-readable name.
    """

    __slots__ = (
        "_vdsd",
        "_ds_index",
        "_name",
        "_title",
    )

    def __init__(
        self,
        vdsd: Vdsd,
        ds_index: int = 0,
        name: str = "",
        title: str = "",
    ) -> None:
        self._vdsd = vdsd
        self._ds_index = ds_index
        self._name = name
        self._title = title

    # ---- read-only accessors -----------------------------------------

    @property
    def vdsd(self) -> Vdsd:
        """The owning vdSD."""
        return self._vdsd

    @property
    def ds_index(self) -> int:
        """Numeric index within the device."""
        return self._ds_index

    # ---- configurable properties -------------------------------------

    @property
    def name(self) -> str:
        """Unique action ID (prefixed ``"dynamic."``)."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def title(self) -> str:
        """Human-readable name."""
        return self._title

    @title.setter
    def title(self, value: str) -> None:
        self._title = value

    # ---- property generation -----------------------------------------

    def get_properties(self) -> dict[str, Any]:
        """Return **dynamicDeviceActions** properties (§4.5.3).

        Format::

            {"name": "dynamic.special", "title": "Special Mode"}
        """
        return {
            "name": self._name,
            "title": self._title,
        }

    # ---- repr --------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"DynamicAction(ds_index={self._ds_index!r}, "
            f"name={self._name!r}, title={self._title!r})"
        )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _parse_option_key(key: Any) -> int | str:
    """Convert a persisted option key back to int when possible."""
    if isinstance(key, int):
        return key
    try:
        return int(key)
    except (ValueError, TypeError):
        return str(key)
