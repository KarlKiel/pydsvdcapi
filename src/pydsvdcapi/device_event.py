# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024–2026 Arne Speck
"""Device event component for vdSD devices (§4.7).

A :class:`DeviceEvent` models one stateless event on a virtual device.
Unlike inputs or sensors, device events carry **no state** — they
represent one-shot occurrences that are pushed to the vdSM via
``VDC_SEND_PUSH_NOTIFICATION`` with ``deviceevents`` payloads.

Each event owns a single property group visible to the vdSM:

* **deviceEventDescriptions** — read-only descriptive properties
  (``name``, ``description``).  These are persisted so the vdSM
  can query them at any time.

There are no *settings* or *state* groups — events are stateless
by definition.

Raising events
~~~~~~~~~~~~~~

The physical device fires events via :meth:`DeviceEvent.raise_event`.
When the owning vdSD is announced and a session is active, the library
sends a ``VDC_SEND_PUSH_NOTIFICATION`` notification to the vdSM carrying
the ``deviceevents`` payload (the ``deviceevents`` field of the
``vdc_SendPushNotification`` message).

Persistence
~~~~~~~~~~~

Only description properties (``name``, ``description``) are persisted
(via the owning Vdsd's property tree → Device → Vdc → VdcHost YAML).
Event occurrences are transient by definition.

Usage::

    from pydsvdcapi.device_event import DeviceEvent

    evt = DeviceEvent(
        vdsd=my_vdsd,
        ds_index=0,
        name="doorbell",
        description="Doorbell button pressed",
    )
    my_vdsd.add_device_event(evt)

    # Later, when the hardware fires the event:
    await evt.raise_event()
"""

from __future__ import annotations

import logging
from typing import (
    TYPE_CHECKING,
    Any,
)

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.vdcapi_pb2 import PropertyElement as _PropertyElement

if TYPE_CHECKING:
    from pydsvdcapi.session import VdcSession
    from pydsvdcapi.vdsd import Vdsd

logger = logging.getLogger(__name__)


class DeviceEvent:
    """One device event definition on a vdSD (§4.7).

    Parameters
    ----------
    vdsd:
        The owning :class:`~pydsvdcapi.vdsd.Vdsd` instance.
    ds_index:
        Numeric index of this event within the device
        (position in ``deviceEventDescriptions``).
    name:
        Event name (e.g. ``"doorbell"``).
    description:
        Optional human-readable description.
    """

    __slots__ = (
        "_vdsd",
        "_ds_index",
        "_name",
        "_description",
    )

    def __init__(
        self,
        *,
        vdsd: Vdsd,
        ds_index: int = 0,
        name: str = "",
        description: str | None = None,
    ) -> None:
        self._vdsd = vdsd
        self._ds_index = ds_index
        self._name = name
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
        """Event name (e.g. ``"doorbell"``)."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def description(self) -> str | None:
        """Optional human-readable description."""
        return self._description

    @description.setter
    def description(self, value: str | None) -> None:
        self._description = value

    # ---- property dicts ----------------------------------------------

    def get_description_properties(self) -> dict[str, Any]:
        """Return **deviceEventDescriptions** properties (§4.7.1).

        Format::

            {"name": "myEvent", "description": "..."}  # desc optional

        Keys in the parent dict are numeric string indices
        (``str(ds_index)``).  The ``name`` field identifies the event.
        """
        props: dict[str, Any] = {
            "name": self._name,
        }
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
        if self._description is not None:
            node["description"] = self._description
        return node

    def _apply_state(self, state: dict[str, Any]) -> None:
        """Restore from a persisted state dict."""
        if "name" in state:
            self._name = state["name"]
        if "description" in state:
            self._description = state.get("description")

    # ---- raising events ----------------------------------------------

    async def raise_event(self, session: VdcSession | None = None) -> None:
        """Raise this event — sends a push notification to the vdSM.

        Parameters
        ----------
        session:
            The session to send through.  When ``None``, the owning
            vdSD's current session is used.

        If no active session is available the call is silently
        skipped with a warning.
        """
        session = session or self._vdsd._session
        if session is None or not session.is_active:
            logger.warning(
                "DeviceEvent[%d] '%s': cannot raise — no active session for vdSD %s",
                self._ds_index,
                self._name,
                self._vdsd.dsuid,
            )
            return

        msg = pb.Message()
        msg.type = pb.VDC_SEND_PUSH_NOTIFICATION
        msg.vdc_send_push_notification.dSUID = str(self._vdsd.dsuid)

        # Each raised event is a PropertyElement keyed by name.
        event_elem = _PropertyElement()
        event_elem.name = self._name
        msg.vdc_send_push_notification.deviceevents.append(event_elem)

        try:
            await session.send_notification(msg)
            logger.debug(
                "DeviceEvent[%d] '%s': raised for vdSD %s",
                self._ds_index,
                self._name,
                self._vdsd.dsuid,
            )
        except (ConnectionError, OSError) as exc:
            logger.warning(
                "DeviceEvent[%d] '%s': failed to raise: %s",
                self._ds_index,
                self._name,
                exc,
            )

    # ---- repr --------------------------------------------------------

    def __repr__(self) -> str:
        return f"DeviceEvent(ds_index={self._ds_index!r}, name={self._name!r})"
