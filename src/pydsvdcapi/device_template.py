# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024–2026 Arne Speck
"""Device template — save and load device configurations.

A :class:`DeviceTemplate` is a structural snapshot of a :class:`Device`
(with all its :class:`Vdsd` instances and components) with
instance-specific values stripped out.  Templates can be saved to YAML
files and loaded later to create new, identically structured devices
with minimal per-instance configuration.

Workflow::

    # -- Saving a template -------------------------------------------
    vdc.save_template(
        device,
        template_type="generic",           # or "model"
        integration="x-acme-light",
        name="dimmable-light",
        description="Standard dimmable light bulb",
    )

    # -- Loading and using a template --------------------------------
    tmpl = vdc.load_template(
        template_type="generic",
        integration="x-acme-light",
        name="dimmable-light",
    )

    tmpl.configure({
        "vdsds[0].name": "Kitchen Light",
    })

    if tmpl.is_ready():
        device = tmpl.instantiate(vdc=vdc, dsuid=my_dsuid)
        device.vdsds[0].on_identify = my_identify_handler
        device.vdsds[0].output.on_channel_applied = my_channel_handler
        await device.announce(session)

Fields stripped from a template
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The following instance-specific values are removed when building a
template tree:

* ``baseDsUID`` (Device level)
* Per-vdSD: ``dSUID``, ``name``, ``zoneID``

All other structural and semantic fields are retained, including
component types, model features, converters, configurations, etc.

``requiredFields``
~~~~~~~~~~~~~~~~~~
The template records which per-instance fields must be supplied before
:meth:`DeviceTemplate.instantiate` will succeed.  Currently the only
required field per vdSD is ``name``.

``requiredCallbacks``
~~~~~~~~~~~~~~~~~~~~~
The template records which callbacks must be set on the instantiated
device **before** calling :meth:`Device.announce`.  The rules are:

* ``vdsds[N].on_invoke_action`` — if the vdSD has ``actionDescriptions``
  or ``standardActions``
* ``vdsds[N].on_identify`` — if ``"identification"`` is in
  ``modelFeatures``
* ``vdsds[N].on_control_value`` — if the vdSD has ``controlValues``
* ``vdsds[N].output.on_channel_applied`` — if the vdSD has an ``output``
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydsvdcapi.dsuid import DsUid
    from pydsvdcapi.vdsd import Device

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TemplateNotConfiguredError(Exception):
    """Raised when :meth:`DeviceTemplate.instantiate` is called before
    all required fields have been supplied.

    Attributes
    ----------
    missing_fields:
        List of field path strings that are still ``None``.
    """

    def __init__(self, missing_fields: list[str]) -> None:
        self.missing_fields = list(missing_fields)
        joined = ", ".join(missing_fields)
        super().__init__(
            f"Template is not fully configured.  Missing required fields: {joined}"
        )


class AnnouncementNotReadyError(Exception):
    """Raised by :meth:`Device.announce` when required callbacks have not
    been set on the device.

    Attributes
    ----------
    missing_callbacks:
        List of callback path strings that are still ``None``.
    """

    def __init__(self, missing_callbacks: list[str]) -> None:
        self.missing_callbacks = list(missing_callbacks)
        joined = ", ".join(missing_callbacks)
        super().__init__(
            f"Device is not ready to announce.  "
            f"Required callbacks are not set: {joined}"
        )


# ---------------------------------------------------------------------------
# DeviceTemplate
# ---------------------------------------------------------------------------


class DeviceTemplate:
    """A structural snapshot of a :class:`Device`, minus instance fields.

    Parameters
    ----------
    template_type:
        Either ``"generic"`` or ``"model"``.
    integration:
        The integration identifier (e.g. ``"x-acme-light"``).  Used as
        a sub-folder name when saving/loading templates.
    name:
        The template's file stem (without extension).
    tree:
        The stripped structural tree as returned by
        :meth:`Device.get_template_tree`.
    required_fields:
        Dict mapping field-path strings (e.g. ``"vdsds[0].name"``) to
        their current values (``None`` = not yet configured).
    required_callbacks:
        Dict mapping callback-path strings (e.g.
        ``"vdsds[0].on_identify"``) to ``None`` (always; present only to
        enumerate which callbacks must be set before announcement).
    description:
        Optional human-readable description of the template.
    created_at:
        ISO-8601 timestamp of when the template was saved.
    """

    def __init__(
        self,
        *,
        template_type: str,
        integration: str,
        name: str,
        tree: dict[str, Any],
        required_fields: dict[str, Any],
        required_callbacks: dict[str, None],
        description: str | None = None,
        created_at: str | None = None,
    ) -> None:
        self._template_type = template_type
        self._integration = integration
        self._name = name
        self._tree = copy.deepcopy(tree)
        self._required_fields: dict[str, Any] = dict(required_fields)
        self._required_callbacks: dict[str, None] = dict(required_callbacks)
        self.description = description
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

    # ---- read-only accessors -----------------------------------------

    @property
    def template_type(self) -> str:
        """Either ``"generic"`` or ``"model"``."""
        return self._template_type

    @property
    def integration(self) -> str:
        """The integration identifier."""
        return self._integration

    @property
    def name(self) -> str:
        """The template name (file stem)."""
        return self._name

    @property
    def required_fields(self) -> dict[str, Any]:
        """Current values of required instance fields (copy)."""
        return dict(self._required_fields)

    @property
    def required_callbacks(self) -> dict[str, None]:
        """Callback paths that must be set before announcement (copy)."""
        return dict(self._required_callbacks)

    # ---- configuration -----------------------------------------------

    def configure(self, values: dict[str, Any]) -> DeviceTemplate:
        """Set required instance-field values.

        Parameters
        ----------
        values:
            Dict mapping field-path strings (e.g.
            ``"vdsds[0].name"``) to their values.  Only keys that
            appear in :attr:`required_fields` are accepted.

        Returns
        -------
        DeviceTemplate
            ``self`` for chaining.

        Raises
        ------
        KeyError
            If a supplied key is not a known required field.
        """
        for key, val in values.items():
            if key not in self._required_fields:
                raise KeyError(
                    f"'{key}' is not a required field for this "
                    f"template.  Known required fields: "
                    f"{list(self._required_fields)}"
                )
            self._required_fields[key] = val
        return self

    def is_ready(self) -> bool:
        """Return ``True`` if all required fields have been supplied."""
        return all(v is not None for v in self._required_fields.values())

    # ---- instantiation -----------------------------------------------

    def instantiate(
        self,
        *,
        vdc: Any,
        dsuid: DsUid | None = None,
    ) -> Device:
        """Create a :class:`Device` from this template.

        Parameters
        ----------
        vdc:
            The :class:`~pydsvdcapi.vdc.Vdc` that will own the device.
        dsuid:
            The base dSUID for the new device.  A random dSUID is
            generated if omitted.

        Returns
        -------
        Device
            A fully constructed, unannounced :class:`Device` with all
            structural components restored.  Required callbacks are
            **not** set — the caller must supply them before calling
            :meth:`Device.announce`.

        Raises
        ------
        TemplateNotConfiguredError
            If :meth:`is_ready` returns ``False``.
        """
        if not self.is_ready():
            missing = [k for k, v in self._required_fields.items() if v is None]
            raise TemplateNotConfiguredError(missing)

        from pydsvdcapi.dsuid import DsUid
        from pydsvdcapi.vdsd import Device

        if dsuid is None:
            dsuid = DsUid.random()

        device = Device(vdc=vdc, dsuid=dsuid)

        # Build a state dict that _apply_state can consume by merging
        # the template tree with the configured instance values.
        state = copy.deepcopy(self._tree)
        state["baseDsUID"] = str(dsuid.device_base())

        # Apply required field values into the state tree.
        for field_path, value in self._required_fields.items():
            _set_field_in_state(state, field_path, value)

        device._apply_state(state)

        # Store required-callbacks manifest on the device so that
        # Device.announce() can validate them.
        device._required_callbacks = dict(self._required_callbacks)

        return device

    # ---- serialisation -----------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise this template to a plain dict (for YAML)."""
        return {
            "templateType": self._template_type,
            "integration": self._integration,
            "name": self._name,
            "description": self.description,
            "createdAt": self.created_at,
            "requiredFields": dict(self._required_fields),
            "requiredCallbacks": list(self._required_callbacks.keys()),
            "tree": copy.deepcopy(self._tree),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceTemplate:
        """Restore a :class:`DeviceTemplate` from a serialised dict."""
        required_callbacks = {k: None for k in data.get("requiredCallbacks", [])}
        return cls(
            template_type=data["templateType"],
            integration=data["integration"],
            name=data["name"],
            tree=data["tree"],
            required_fields=data.get("requiredFields", {}),
            required_callbacks=required_callbacks,
            description=data.get("description"),
            created_at=data.get("createdAt"),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_required_fields(vdsd_trees: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the ``requiredFields`` manifest from a list of vdSD trees.

    Currently the only required field per vdSD is ``name``.
    """
    fields: dict[str, Any] = {}
    for idx, _ in enumerate(vdsd_trees):
        fields[f"vdsds[{idx}].name"] = None
    return fields


def build_required_callbacks(
    vdsd_trees: list[dict[str, Any]],
) -> dict[str, None]:
    """Build the ``requiredCallbacks`` manifest from a list of vdSD trees.

    Rules:
    * ``vdsds[N].on_invoke_action`` — if the vdSD has
      ``actionDescriptions`` or ``standardActions``
    * ``vdsds[N].on_identify`` — if ``"identification"`` is in
      ``modelFeatures``
    * ``vdsds[N].on_control_value`` — if the vdSD has ``controlValues``
    * ``vdsds[N].output.on_channel_applied`` — if the vdSD has an
      ``output``
    """
    callbacks: dict[str, None] = {}
    for idx, vdsd_tree in enumerate(vdsd_trees):
        if vdsd_tree.get("actionDescriptions") or vdsd_tree.get("standardActions"):
            callbacks[f"vdsds[{idx}].on_invoke_action"] = None

        model_features: list[str] = vdsd_tree.get("modelFeatures", [])
        if "identification" in model_features:
            callbacks[f"vdsds[{idx}].on_identify"] = None

        if vdsd_tree.get("controlValues"):
            callbacks[f"vdsds[{idx}].on_control_value"] = None

        if vdsd_tree.get("output") is not None:
            callbacks[f"vdsds[{idx}].output.on_channel_applied"] = None

    return callbacks


def strip_instance_fields(device_tree: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *device_tree* with instance-specific fields removed.

    Strips:
    * ``baseDsUID`` (Device level)
    * Per-vdSD: ``dSUID``, ``name``, ``zoneID``
    """
    tree = copy.deepcopy(device_tree)
    tree.pop("baseDsUID", None)

    for vdsd_tree in tree.get("vdsds", []):
        vdsd_tree.pop("dSUID", None)
        vdsd_tree.pop("name", None)
        vdsd_tree.pop("zoneID", None)

    return tree


def _set_field_in_state(state: dict[str, Any], path: str, value: Any) -> None:
    """Apply a required-field value into a state dict.

    Supported path formats:
    * ``"vdsds[N].name"`` → sets ``state["vdsds"][N]["name"] = value``
    """
    import re

    m = re.fullmatch(r"vdsds\[(\d+)\]\.(\w+)", path)
    if m:
        idx = int(m.group(1))
        field = m.group(2)
        vdsds = state.get("vdsds", [])
        if idx < len(vdsds):
            vdsds[idx][field] = value
        return

    # Fallback: set top-level key.
    state[path] = value
