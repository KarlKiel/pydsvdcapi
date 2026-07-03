# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024–2026 Arne Speck
"""Property handling — query/response helpers for the vDC API.

The vDC API uses a recursive ``PropertyElement`` tree structure for
reading and writing named properties on addressable entities (vDC host,
vDCs, devices).  This module provides utility functions to:

* **Build** ``PropertyElement`` trees from plain Python dicts.
* **Match** incoming property queries against a dict of available
  properties, producing the correctly shaped response tree.
* **Apply** incoming ``setProperty`` elements to a mutable dict of
  entity properties.

PropertyElement structure (protobuf)::

    message PropertyElement {
        optional string name  = 1;
        optional PropertyValue value = 2;
        repeated PropertyElement elements = 3;
    }

Python → protobuf type mapping:

  ========  ======================
  Python    PropertyValue field
  ========  ======================
  ``str``   ``v_string``
  ``int``   ``v_uint64`` (≥ 0) or ``v_int64`` (< 0)
  ``bool``  ``v_bool``
  ``float`` ``v_double``
  ``bytes`` ``v_bytes``
  ``dict``  nested ``elements``
  ``None``  empty ``PropertyValue`` (explicit NULL)
  ========  ======================
"""

from __future__ import annotations

import logging
from typing import Any

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.vdcapi_pb2 import PropertyElement as _PropertyElement
from pydsvdcapi.vdcapi_pb2 import PropertyValue as _PropertyValue

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sentinel: name-only PropertyElement (no value field on the wire)
# ---------------------------------------------------------------------------


class _NoValue:
    """Sentinel indicating a PropertyElement should carry **only** a name.

    Use this as a dict value when building property trees where the
    resulting ``PropertyElement`` must have its ``name`` set but its
    ``value`` field completely absent (not even an empty
    ``PropertyValue``).  This matches the vDC API specification for
    enumeration value-list entries in state/property descriptions.
    """

    _instance: _NoValue | None = None

    def __new__(cls) -> _NoValue:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover
        return "NO_VALUE"

    def __bool__(self) -> bool:  # noqa: D105
        return False


NO_VALUE: _NoValue = _NoValue()
"""Singleton sentinel — use as a dict value to produce a name-only
``PropertyElement`` with no ``value`` field on the wire."""


# ---------------------------------------------------------------------------
# Python value → PropertyValue
# ---------------------------------------------------------------------------


def _to_property_value(value: Any) -> _PropertyValue | None:
    """Convert a Python value to a :class:`PropertyValue` protobuf.

    Returns ``None`` when *value* is :data:`NO_VALUE`, a ``dict``
    (use nested elements instead), or an unsupported type.
    """
    if value is NO_VALUE:
        # Name-only entry — no value field should appear on the wire.
        return None

    if value is None:
        # Explicit NULL — an empty PropertyValue with no fields set.
        return _PropertyValue()

    pv = _PropertyValue()
    # bool must be checked before int (bool is a subclass of int).
    if isinstance(value, bool):
        pv.v_bool = value
    elif isinstance(value, int):
        # The vdSM expects unsigned integers (v_uint64) for most
        # numeric properties (zoneID, primaryGroup, etc.).  Use
        # v_int64 only for genuinely negative values.
        if value < 0:
            pv.v_int64 = value
        else:
            pv.v_uint64 = value
    elif isinstance(value, float):
        pv.v_double = value
    elif isinstance(value, str):
        pv.v_string = value
    elif isinstance(value, (bytes, bytearray)):
        pv.v_bytes = bytes(value)
    else:
        return None
    return pv


# ---------------------------------------------------------------------------
# dict → PropertyElement list (full expansion)
# ---------------------------------------------------------------------------


def dict_to_elements(
    properties: dict[str, Any],
) -> list[_PropertyElement]:
    """Convert a Python dict to a list of ``PropertyElement`` messages.

    Nested dicts become sub-elements; scalars become values.
    """
    elements: list[_PropertyElement] = []
    for key, val in properties.items():
        elem = _PropertyElement()
        elem.name = str(key)
        if val is NO_VALUE:
            # Name-only PropertyElement — no value or sub-elements.
            pass
        elif isinstance(val, dict):
            for sub in dict_to_elements(val):
                elem.elements.append(sub)
        else:
            pv = _to_property_value(val)
            if pv is not None:
                elem.value.CopyFrom(pv)
        elements.append(elem)
    return elements


# ---------------------------------------------------------------------------
# Query matching
# ---------------------------------------------------------------------------


def match_query(
    properties: dict[str, Any],
    query: Any,
) -> list[_PropertyElement]:
    """Match an incoming property *query* against *properties*.

    Parameters
    ----------
    properties:
        Flat or nested dict of property name → value.
    query:
        The ``query`` repeated field from a
        ``vdsm_RequestGetProperty`` message (a sequence of
        ``PropertyElement`` messages).

    Returns
    -------
    list[PropertyElement]
        Response elements matching the query structure, with values
        filled in from *properties*.  Unknown property names are
        silently dropped.  Wildcard queries (empty ``name``) expand
        to all available properties on that level.
    """
    result: list[_PropertyElement] = []

    for q_elem in query:
        name = q_elem.name

        if not name:
            # Wildcard — return everything at this level.
            for k, v in properties.items():
                elem = _PropertyElement()
                elem.name = k
                if isinstance(v, dict):
                    # If the wildcard has sub-elements, apply them.
                    if len(q_elem.elements) > 0:
                        for sub in match_query(v, q_elem.elements):
                            elem.elements.append(sub)
                    else:
                        # No sub-query → expand all nested elements.
                        for sub in dict_to_elements(v):
                            elem.elements.append(sub)
                else:
                    pv = _to_property_value(v)
                    if pv is not None:
                        elem.value.CopyFrom(pv)
                result.append(elem)
        elif name in properties:
            val = properties[name]
            elem = _PropertyElement()
            elem.name = name

            if isinstance(val, dict):
                if len(q_elem.elements) > 0:
                    # Recurse into the nested dict.
                    for sub in match_query(val, q_elem.elements):
                        elem.elements.append(sub)
                else:
                    # No sub-query — return all nested elements.
                    for sub in dict_to_elements(val):
                        elem.elements.append(sub)
            else:
                pv = _to_property_value(val)
                if pv is not None:
                    elem.value.CopyFrom(pv)
            result.append(elem)
        # else: unknown property — silently omit from response.

    return result


# ---------------------------------------------------------------------------
# Building a complete GetProperty response message
# ---------------------------------------------------------------------------


def build_get_property_response(
    request: pb.Message,
    properties: dict[str, Any],
) -> pb.Message:
    """Build a ``VDC_RESPONSE_GET_PROPERTY`` from a request and dict.

    Parameters
    ----------
    request:
        The incoming ``VDSM_REQUEST_GET_PROPERTY`` message.
    properties:
        Dict of property name → value for the addressed entity.

    Returns
    -------
    Message
        A properly formed ``VDC_RESPONSE_GET_PROPERTY`` correlated
        to the request via ``message_id``.
    """
    query = request.vdsm_request_get_property.query
    matched = match_query(properties, query)

    response = pb.Message()
    response.type = pb.VDC_RESPONSE_GET_PROPERTY
    response.message_id = request.message_id

    # Ensure the sub-message is always present in the serialized
    # output, even when *matched* is empty.  Without this the
    # vdSM receives a packet whose type says "getProperty
    # response" but the actual ``vdc_response_get_property``
    # field is missing, causing an "ERR_MISSING_SUBMESSAGE"
    # and aborting the device registration.
    response.vdc_response_get_property.SetInParent()

    for elem in matched:
        response.vdc_response_get_property.properties.append(elem)

    return response


# ---------------------------------------------------------------------------
# setProperty helpers
# ---------------------------------------------------------------------------


def _extract_value(pv: _PropertyValue) -> Any:
    """Extract a Python value from a ``PropertyValue`` message.

    Returns ``None`` if no field is set (explicit NULL).
    """
    if pv.HasField("v_bool"):
        return pv.v_bool
    if pv.HasField("v_uint64"):
        return pv.v_uint64
    if pv.HasField("v_int64"):
        return pv.v_int64
    if pv.HasField("v_double"):
        return pv.v_double
    if pv.HasField("v_string"):
        return pv.v_string
    if pv.HasField("v_bytes"):
        return pv.v_bytes
    return None


def elements_to_dict(
    elements: Any,
) -> dict[str, Any]:
    """Convert a sequence of ``PropertyElement`` messages to a Python dict.

    Nested elements are converted recursively.  This is the inverse of
    :func:`dict_to_elements`.

    Empty-name elements (wildcards in ``setProperty`` context, see
    §7.1.2) are preserved under the ``""`` key.  If multiple
    empty-name elements exist at the same level only the last one
    is kept.
    """
    result: dict[str, Any] = {}
    for elem in elements:
        name = elem.name  # May be "" for wildcard.
        if len(elem.elements) > 0:
            result[name] = elements_to_dict(elem.elements)
        elif elem.HasField("value"):
            result[name] = _extract_value(elem.value)
        else:
            result[name] = None
    return result


def expand_setproperty_wildcards(
    container: dict[str, Any],
    all_keys: Any,
) -> dict[str, Any]:
    """Expand wildcard (empty-name) entries for ``setProperty`` semantics.

    Per vDC API §7.1.2: *"If the name is specified empty, this is a
    wildcard meaning all elements of that level (for example: all
    inputs or all scenes) should be set to the same value."*

    If *container* has an empty-string key (``""``), its value is
    used as the template for every key in *all_keys* that is not
    already explicitly present in *container*.

    Parameters
    ----------
    container:
        The incoming property dict for a container level (e.g.
        ``scenes``, ``buttonInputSettings``).  May contain a
        ``""`` key representing a wildcard.
    all_keys:
        The universe of existing keys at this level (e.g. all scene
        indices, all input indices).  Each key is stringified via
        ``str()`` before comparison.

    Returns
    -------
    dict
        A new dict with the wildcard expanded.  The ``""`` key
        itself is removed from the result.
    """
    wildcard = container.get("")
    result: dict[str, Any] = {k: v for k, v in container.items() if k != ""}
    if wildcard is not None:
        for key in all_keys:
            key_str = str(key)
            if key_str not in result:
                result[key_str] = wildcard
    return result
