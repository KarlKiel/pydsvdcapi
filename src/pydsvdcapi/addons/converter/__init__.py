"""Value converter helpers — pydsvdcapi.addons.converter.

A *converter* is a small Python code snippet provided by the end-user
at runtime that reshapes a value before it is stored or forwarded.
The snippet operates on a pre-bound variable ``value`` and may
reassign it any number of times.  The library automatically appends
``return value`` so no return statement is needed.

Example snippets
----------------

Simple expression::

    "value = value * 100.0 / 255.0"

Multi-line block::

    \"\"\"
    mapping = {"stopped": 0, "paused": 1, "playing": 2}
    value = mapping.get(str(value), 0)
    \"\"\"

None-guarded conversion::

    \"\"\"
    if value is None:
        value = 0
    else:
        value = round(float(value) * 255.0 / 100.0)
    \"\"\"

The snippet is the *body* of an implicit ``def convert(value):`` —
just write the mutation logic, ``value`` is the only pre-bound name.
Standard library modules can be imported inside the snippet if needed
(``import math``).

Public API
----------
compile_converter(code)
    Compile a snippet string into a callable.  Raises ``SyntaxError``
    immediately on invalid code.
apply_converter(fn, value, *, component_id, direction)
    Invoke ``fn(value)``.  On any exception logs a warning and returns
    the original unconverted value (fail-open).
"""

from __future__ import annotations

import logging
import textwrap
from collections.abc import Callable
from typing import Any, cast

logger = logging.getLogger(__name__)


def compile_converter(code: str) -> Callable[[Any], Any]:
    """Compile a converter snippet into a callable.

    The snippet is wrapped as the body of::

        def _converter(value):
            <snippet>
            return value

    ``return value`` is appended automatically so the user only needs
    to write reassignment statements.

    Parameters
    ----------
    code:
        Python code snippet.  Common leading whitespace is stripped
        automatically (safe to pass triple-quoted strings).

    Returns
    -------
    Callable
        A callable that accepts a single ``value`` argument and
        returns the (possibly converted) value.

    Raises
    ------
    SyntaxError
        If the snippet contains a syntax error.  The error is raised
        eagerly so configuration mistakes surface at setup time.
    """
    # Strip common leading whitespace from triple-quoted blocks.
    body = textwrap.dedent(code).strip()
    # Indent one level to form a valid function body.
    indented = textwrap.indent(body, "    ")
    func_src = f"def _converter(value):\n{indented}\n    return value\n"

    # compile() validates syntax; raises SyntaxError on bad code.
    compiled = compile(func_src, "<converter>", "exec")

    # exec into an isolated namespace to retrieve the function object.
    namespace: dict = {}
    exec(compiled, namespace)  # noqa: S102
    return cast(Callable[[Any], Any], namespace["_converter"])


def apply_converter(
    fn: Callable[[Any], Any] | None,
    value: Any,
    *,
    component_id: str,
    direction: str,
) -> Any:
    """Apply a compiled converter to *value*, with fail-open error handling.

    If *fn* is ``None`` the value is returned unchanged.

    If the converter raises any exception a ``WARNING`` is logged
    (including the component identity, direction, and error) and the
    **original unconverted value** is returned so that data is never
    silently dropped.

    Parameters
    ----------
    fn:
        Compiled converter callable (from :func:`compile_converter`),
        or ``None`` for passthrough.
    value:
        Incoming value to convert.
    component_id:
        Human-readable identifier for logging (e.g.
        ``"SensorInput[0] 'Room Temp'"``.
    direction:
        ``"uplink"`` or ``"downlink"`` for log context.

    Returns
    -------
    Any
        Converted value, or the original *value* on error / no converter.
    """
    if fn is None:
        return value
    try:
        return fn(value)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Converter error in %s (%s): %s — using original value %r",
            component_id,
            direction,
            exc,
            value,
        )
        return value
