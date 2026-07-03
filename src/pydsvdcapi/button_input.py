# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024–2026 Arne Speck
"""Button input component for vdSD devices.

A :class:`ButtonInput` models one pushbutton input element on a virtual
device.  It owns three property groups visible to the vdSM:

* **buttonInputDescriptions** — read-only hardware characteristics
  (name, dsIndex, supportsLocalKeyMode, buttonID, buttonType,
  buttonElementID).
* **buttonInputSettings** — writable configuration stored persistently
  (group, function, mode, channel, setsLocalPriority, callsPresent).
* **buttonInputStates** — volatile runtime state that is **not**
  persisted.  Has two alternative representations:

  * **Click mode** (§4.2.3, primary) — ``value`` (active/inactive),
    ``clickType`` (enum), ``age`` and ``error``.
  * **Action mode** (§4.2.3, alternative) — ``actionId`` (scene
    number), ``actionMode`` (normal/force/undo), ``age`` and
    ``error``.

  The most recent event determines which representation is returned.

Button elements
~~~~~~~~~~~~~~~

A physical button's :attr:`ButtonInput.button_type` defines the number
and arrangement of button elements.  Each element is a separate
:class:`ButtonInput` instance sharing the same ``buttonID`` but having
a distinct ``buttonElementID`` and ``dsIndex``.

+-------------------------------+---+-------------------------------------+
| ButtonType                    | N | Elements (ButtonElementID)          |
+===============================+===+=====================================+
| SINGLE_PUSHBUTTON (1)         | 1 | CENTER                              |
+-------------------------------+---+-------------------------------------+
| TWO_WAY_PUSHBUTTON (2)        | 2 | DOWN, UP                            |
+-------------------------------+---+-------------------------------------+
| FOUR_WAY_NAVIGATION (3)       | 4 | DOWN, UP, LEFT, RIGHT               |
+-------------------------------+---+-------------------------------------+
| FOUR_WAY_WITH_CENTER (4)      | 5 | CENTER, DOWN, UP, LEFT, RIGHT       |
+-------------------------------+---+-------------------------------------+
| EIGHT_WAY_WITH_CENTER (5)     | 9 | CENTER, DOWN, UP, LEFT, RIGHT,      |
|                               |   | UPPER_LEFT, LOWER_LEFT,             |
|                               |   | UPPER_RIGHT, LOWER_RIGHT            |
+-------------------------------+---+-------------------------------------+
| ON_OFF_SWITCH (6)             | 2 | DOWN (off), UP (on)                 |
+-------------------------------+---+-------------------------------------+

The :func:`get_required_elements` helper returns the standard element
IDs for a given button type, and :func:`create_button_group` can
instantiate all of them at once.

Click detection
~~~~~~~~~~~~~~~

There are three ways to supply events to a :class:`ButtonInput`:

1. **State machine mode** — call :meth:`ButtonInput.press` and
   :meth:`ButtonInput.release` to feed raw press/release events into
   the built-in :class:`ClickDetector` state machine.  The state
   machine resolves timing patterns (single-click, double-click, hold,
   short-long combos, …) and pushes the resulting ``clickType`` to the
   vdSM automatically.

2. **Direct click mode** — call :meth:`ButtonInput.update_click` with
   an already-resolved :class:`ButtonClickType`.  Use this when the
   physical device can directly report click events.

3. **Action mode** — call :meth:`ButtonInput.update_action` with a
   scene ID and :class:`ActionMode`.  Use this when the button
   directly calls a scene instead of generating a click event.

Persistence
~~~~~~~~~~~

Only description and settings properties are persisted (via the owning
Vdsd's property tree → Device → Vdc → VdcHost YAML).  The runtime
state is transient by definition.

Usage::

    from pydsvdcapi.button_input import ButtonInput, ClickDetector
    from pydsvdcapi.enums import (
        ButtonType, ButtonElementID, ButtonClickType, ActionMode,
    )

    # Single pushbutton using the click state machine:
    btn = ButtonInput(
        vdsd=my_vdsd,
        ds_index=0,
        button_type=ButtonType.SINGLE_PUSHBUTTON,
        button_element_id=ButtonElementID.CENTER,
        button_id=0,
        name="Main Button",
    )
    my_vdsd.add_button_input(btn)

    # When physical button pressed / released:
    btn.press()     # feeds ClickDetector — pushes resolved event later
    btn.release()   # ClickDetector resolves timing and pushes

    # Or direct click type (bypasses state machine):
    await btn.update_click(ButtonClickType.CLICK_1X)

    # Or direct scene call:
    await btn.update_action(action_id=5, action_mode=ActionMode.NORMAL)
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time
from collections.abc import Callable, Coroutine
from typing import (
    TYPE_CHECKING,
    Any,
)

from pydsvdcapi import vdc_messages_pb2 as pb
from pydsvdcapi.enums import (
    ActionMode,
    ButtonClickType,
    ButtonElementID,
    ButtonFunction,
    ButtonFunctionJoker,
    ButtonMode,
    ButtonType,
    InputError,
    button_function_for_group,
)
from pydsvdcapi.property_handling import dict_to_elements

if TYPE_CHECKING:
    from pydsvdcapi.session import VdcSession
    from pydsvdcapi.vdsd import Vdsd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants — button type → required elements mapping
# ---------------------------------------------------------------------------

#: Standard element arrangement for each ButtonType.
#:
#: ``UNDEFINED`` maps to an empty list because the element layout is
#: determined by the integrating application.
BUTTON_TYPE_ELEMENTS: dict[ButtonType, list[ButtonElementID]] = {
    ButtonType.UNDEFINED: [],
    ButtonType.SINGLE_PUSHBUTTON: [
        ButtonElementID.CENTER,
    ],
    ButtonType.TWO_WAY_PUSHBUTTON: [
        ButtonElementID.DOWN,
        ButtonElementID.UP,
    ],
    ButtonType.FOUR_WAY_NAVIGATION: [
        ButtonElementID.DOWN,
        ButtonElementID.UP,
        ButtonElementID.LEFT,
        ButtonElementID.RIGHT,
    ],
    ButtonType.FOUR_WAY_WITH_CENTER: [
        ButtonElementID.CENTER,
        ButtonElementID.DOWN,
        ButtonElementID.UP,
        ButtonElementID.LEFT,
        ButtonElementID.RIGHT,
    ],
    ButtonType.EIGHT_WAY_WITH_CENTER: [
        ButtonElementID.CENTER,
        ButtonElementID.DOWN,
        ButtonElementID.UP,
        ButtonElementID.LEFT,
        ButtonElementID.RIGHT,
        ButtonElementID.UPPER_LEFT,
        ButtonElementID.LOWER_LEFT,
        ButtonElementID.UPPER_RIGHT,
        ButtonElementID.LOWER_RIGHT,
    ],
    ButtonType.ON_OFF_SWITCH: [
        ButtonElementID.DOWN,
        ButtonElementID.UP,
    ],
}


# ---------------------------------------------------------------------------
# Default timing constants for ClickDetector (seconds)
# ---------------------------------------------------------------------------

#: Maximum press duration that counts as a "tip" (short press).
DEFAULT_TIP_TIMEOUT: float = 0.25

#: Maximum gap between consecutive short presses in a multi-click sequence.
DEFAULT_MULTI_CLICK_WINDOW: float = 0.3

#: Interval between ``HOLD_REPEAT`` events while button is held.
DEFAULT_HOLD_REPEAT_INTERVAL: float = 1.0


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

#: Type alias for the button-input-settings-changed callback.
#: ``async def callback(button_input: ButtonInput, changed: dict[str, Any]) -> None``
ButtonInputSettingsChangedCallback = Callable[
    ["ButtonInput", dict[str, Any]],
    Coroutine[Any, Any, None],
]


# ---------------------------------------------------------------------------
# ClickDetector — state machine for press/release → clickType
# ---------------------------------------------------------------------------


class _ClickState(enum.Enum):
    """Internal states of the click detection state machine."""

    IDLE = "idle"
    PRESSED = "pressed"
    TIP_WAIT = "tip_wait"
    HOLDING = "holding"


class ClickDetector:
    """State machine that interprets raw button press/release events
    into :class:`~pydsvdcapi.enums.ButtonClickType` values.

    When a click pattern is resolved the *on_click* callback is called
    with ``(click_type, value)`` where:

    * *click_type* — the resolved :class:`ButtonClickType`.
    * *value* — ``True`` if the button is currently pressed,
      ``False`` if released.

    The callback may return a coroutine, which will be scheduled via
    ``asyncio.create_task``.

    Timing parameters
    -----------------

    * *tip_timeout* — maximum press duration (seconds) for a
      "tip" (short press).  Presses held longer than this threshold
      trigger a hold sequence.  Default: 250 ms.

    * *multi_click_window* — maximum gap (seconds) between
      consecutive short presses in a multi-click sequence.
      If the window expires the multi-click count is resolved.
      Default: 300 ms.

    * *hold_repeat_interval* — time (seconds) between consecutive
      ``HOLD_REPEAT`` events while the button is held.
      Default: 1.0 s.

    Click vs. Tip events
    --------------------

    * When *use_tip_events* is ``False`` (default), resolved short
      presses emit ``CLICK_1X`` / ``CLICK_2X`` / ``CLICK_3X``.
    * When *use_tip_events* is ``True``, they emit
      ``TIP_1X`` / ``TIP_2X`` / ``TIP_3X`` / ``TIP_4X`` instead.

    State machine
    -------------

    ::

        IDLE ─── press() ───► PRESSED
                                │
                    ┌───────────┤
                    │           │
             release() before   tip_timeout fires
             tip_timeout        │
                    │           ▼
                    ▼        HOLDING ──► HOLD_REPEAT (periodic)
              TIP_WAIT          │
                │   │        release()
                │   │           │
         press()│   multi_click │
                │   window      ▼
                │   expires   IDLE
                ▼      │      (emit HOLD_END)
             PRESSED   ▼
                     IDLE
                     (emit CLICK_Nx / TIP_Nx)

    Hold-combo detection:

    * 0 short presses + hold → ``HOLD_START``
    * 1 short press  + hold → ``SHORT_LONG``
    * 2+ short presses + hold → ``SHORT_SHORT_LONG``
    """

    def __init__(
        self,
        on_click: Callable[[ButtonClickType, bool], Any],
        *,
        tip_timeout: float = DEFAULT_TIP_TIMEOUT,
        multi_click_window: float = DEFAULT_MULTI_CLICK_WINDOW,
        hold_repeat_interval: float = DEFAULT_HOLD_REPEAT_INTERVAL,
        use_tip_events: bool = False,
    ) -> None:
        self._on_click = on_click
        self._tip_timeout = tip_timeout
        self._multi_click_window = multi_click_window
        self._hold_repeat_interval = hold_repeat_interval
        self._use_tip_events = use_tip_events

        self._state: _ClickState = _ClickState.IDLE
        self._tip_count: int = 0

        self._tip_timer: asyncio.TimerHandle | None = None
        self._multi_click_timer: asyncio.TimerHandle | None = None
        self._hold_repeat_timer: asyncio.TimerHandle | None = None
        self._background_tasks: set[asyncio.Task[Any]] = set()

    # ---- public API --------------------------------------------------

    @property
    def state(self) -> str:
        """Current state name (for debugging / testing)."""
        return self._state.value

    @property
    def tip_count(self) -> int:
        """Short-press count in the current multi-click sequence."""
        return self._tip_count

    @property
    def tip_timeout(self) -> float:
        """Maximum press duration for a short press (seconds)."""
        return self._tip_timeout

    @property
    def multi_click_window(self) -> float:
        """Maximum gap between multi-click presses (seconds)."""
        return self._multi_click_window

    @property
    def hold_repeat_interval(self) -> float:
        """Interval between HOLD_REPEAT events (seconds)."""
        return self._hold_repeat_interval

    @property
    def use_tip_events(self) -> bool:
        """Whether to emit TIP_Nx instead of CLICK_Nx."""
        return self._use_tip_events

    def press(self) -> None:
        """Signal that the button has been physically pressed.

        Call this when the hardware detects a button-down event.
        Ignored if the button is already in a pressed state.
        """
        if self._state == _ClickState.IDLE:
            self._tip_count = 0
            self._state = _ClickState.PRESSED
            self._schedule_tip_timer()

        elif self._state == _ClickState.TIP_WAIT:
            # Another press within the multi-click window.
            self._cancel_multi_click_timer()
            self._state = _ClickState.PRESSED
            self._schedule_tip_timer()

        # In PRESSED or HOLDING: already pressed — ignore.

    def release(self) -> None:
        """Signal that the button has been physically released.

        Call this when the hardware detects a button-up event.
        Ignored if the button is not in a pressed state.
        """
        if self._state == _ClickState.PRESSED:
            self._cancel_tip_timer()
            self._tip_count += 1
            self._state = _ClickState.TIP_WAIT
            self._schedule_multi_click_timer()

        elif self._state == _ClickState.HOLDING:
            self._cancel_hold_repeat_timer()
            self._state = _ClickState.IDLE
            self._emit(ButtonClickType.HOLD_END, False)
            self._tip_count = 0

        # In IDLE or TIP_WAIT: not pressed — ignore.

    def stop(self) -> None:
        """Cancel all pending timers and reset to IDLE.

        Call when the button is removed, the vdSD vanishes, or the
        session disconnects.
        """
        self._cancel_tip_timer()
        self._cancel_multi_click_timer()
        self._cancel_hold_repeat_timer()
        self._state = _ClickState.IDLE
        self._tip_count = 0

    # ---- tip timer ---------------------------------------------------

    def _schedule_tip_timer(self) -> None:
        """Start the tip-vs-hold discrimination timer."""
        self._cancel_tip_timer()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._tip_timer = loop.call_later(self._tip_timeout, self._on_tip_timeout)

    def _cancel_tip_timer(self) -> None:
        if self._tip_timer is not None:
            self._tip_timer.cancel()
            self._tip_timer = None

    def _on_tip_timeout(self) -> None:
        """Button held past tip threshold → start hold sequence."""
        self._tip_timer = None
        if self._state != _ClickState.PRESSED:
            return

        self._state = _ClickState.HOLDING

        # Determine the hold-combo type based on preceding short presses.
        if self._tip_count == 0:
            self._emit(ButtonClickType.HOLD_START, True)
        elif self._tip_count == 1:
            self._emit(ButtonClickType.SHORT_LONG, True)
        else:
            self._emit(ButtonClickType.SHORT_SHORT_LONG, True)

        self._schedule_hold_repeat_timer()

    # ---- multi-click timer -------------------------------------------

    def _schedule_multi_click_timer(self) -> None:
        """Start the multi-click window timer."""
        self._cancel_multi_click_timer()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._multi_click_timer = loop.call_later(
            self._multi_click_window, self._on_multi_click_timeout
        )

    def _cancel_multi_click_timer(self) -> None:
        if self._multi_click_timer is not None:
            self._multi_click_timer.cancel()
            self._multi_click_timer = None

    def _on_multi_click_timeout(self) -> None:
        """Multi-click window expired → emit resolved click type."""
        self._multi_click_timer = None
        if self._state != _ClickState.TIP_WAIT:
            return

        self._state = _ClickState.IDLE

        if self._use_tip_events:
            click_map = {
                1: ButtonClickType.TIP_1X,
                2: ButtonClickType.TIP_2X,
                3: ButtonClickType.TIP_3X,
            }
            ct = click_map.get(self._tip_count, ButtonClickType.TIP_4X)
        else:
            click_map = {
                1: ButtonClickType.CLICK_1X,
                2: ButtonClickType.CLICK_2X,
                3: ButtonClickType.CLICK_3X,
            }
            ct = click_map.get(self._tip_count, ButtonClickType.CLICK_3X)

        self._emit(ct, False)
        self._tip_count = 0

    # ---- hold repeat timer -------------------------------------------

    def _schedule_hold_repeat_timer(self) -> None:
        """Start the hold-repeat interval timer."""
        self._cancel_hold_repeat_timer()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._hold_repeat_timer = loop.call_later(
            self._hold_repeat_interval,
            self._on_hold_repeat_timeout,
        )

    def _cancel_hold_repeat_timer(self) -> None:
        if self._hold_repeat_timer is not None:
            self._hold_repeat_timer.cancel()
            self._hold_repeat_timer = None

    def _on_hold_repeat_timeout(self) -> None:
        """Emit HOLD_REPEAT and re-arm the timer."""
        self._hold_repeat_timer = None
        if self._state != _ClickState.HOLDING:
            return
        self._emit(ButtonClickType.HOLD_REPEAT, True)
        self._schedule_hold_repeat_timer()

    # ---- event emission ----------------------------------------------

    def _emit(self, click_type: ButtonClickType, value: bool) -> None:
        """Invoke the registered callback, scheduling coroutines."""
        try:
            result = self._on_click(click_type, value)
            if asyncio.iscoroutine(result):
                _task = asyncio.create_task(result)
                self._background_tasks.add(_task)
                _task.add_done_callback(self._background_tasks.discard)
        except Exception:
            logger.exception(
                "ClickDetector callback error for %s",
                click_type.name,
            )

    # ---- dunder ------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"ClickDetector(state={self._state.value!r}, tip_count={self._tip_count})"
        )


# ---------------------------------------------------------------------------
# ButtonInput
# ---------------------------------------------------------------------------


class ButtonInput:
    """One button input element on a vdSD.

    Parameters
    ----------
    vdsd:
        The owning :class:`~pydsvdcapi.vdsd.Vdsd`.
    ds_index:
        Zero-based index among **all** button inputs of this device.
        Must be unique within the device.
    name:
        Human-readable name or label for this element (e.g.
        ``"Rocker Up"``).
    supports_local_key_mode:
        Whether this button can act as a local button.
    button_id:
        ID of the physical button.  All elements of a multi-contact
        button share the same ``button_id``.  ``None`` means no
        fixed assignment.
    button_type:
        Physical button type (defines element arrangement, see
        :data:`BUTTON_TYPE_ELEMENTS`).
    button_element_id:
        Element within a multi-contact button.
    group:
        dS group number (writable setting, persisted).
    function:
        Button function / LTNUM (writable, persisted).
    mode:
        Button mode / LTMODE (writable, persisted).
    channel:
        Output channel this button controls.
        ``0`` = default channel (writable, persisted).
    sets_local_priority:
        Whether button sets local priority (writable, persisted).
    calls_present:
        Whether button calls present if system state is absent
        (writable, persisted).
    click_detector_config:
        Optional dict of timing overrides for the built-in
        :class:`ClickDetector`.  Supported keys:
        ``tip_timeout``, ``multi_click_window``,
        ``hold_repeat_interval``, ``use_tip_events``.
    """

    def __init__(
        self,
        *,
        vdsd: Vdsd,
        ds_index: int = 0,
        name: str = "",
        supports_local_key_mode: bool = False,
        button_id: int | None = None,
        button_type: ButtonType = ButtonType.UNDEFINED,
        button_element_id: ButtonElementID = ButtonElementID.CENTER,
        # Settings (writable, persisted)
        group: int = 0,
        function: ButtonFunction | ButtonFunctionJoker | int = ButtonFunction.DEVICE,
        mode: ButtonMode | int = ButtonMode.STANDARD,
        channel: int = 0,
        sets_local_priority: bool = False,
        calls_present: bool = False,
        # Click detector configuration
        click_detector_config: dict[str, Any] | None = None,
    ) -> None:
        # ---- parent reference ----------------------------------------
        self._vdsd: Vdsd = vdsd

        # ---- description properties (read-only, not persisted) -------
        self._ds_index: int = ds_index
        self._name: str = name
        self._supports_local_key_mode: bool = supports_local_key_mode
        self._button_id: int | None = button_id
        self._button_type: ButtonType = button_type
        self._button_element_id: ButtonElementID = button_element_id

        # ---- settings properties (read/write, persisted) -------------
        self._group: int = group
        self._function: ButtonFunction | ButtonFunctionJoker | int = (
            button_function_for_group(group, int(function))
        )
        self._mode: ButtonMode = ButtonMode(int(mode))
        self._channel: int = channel
        self._sets_local_priority: bool = sets_local_priority
        self._calls_present: bool = calls_present

        # ---- state properties (volatile, NOT persisted) --------------
        self._value: bool | None = None
        self._click_type: ButtonClickType = ButtonClickType.IDLE
        self._action_id: int | None = None
        self._action_mode: ActionMode | None = None
        self._error: InputError = InputError.OK
        #: Monotonic timestamp of the last state event (for age calc).
        self._last_update: float | None = None
        #: Whether the most recent event was an action (vs. click).
        self._last_state_is_action: bool = False

        # ---- session reference (set on announcement) -----------------
        self._session: VdcSession | None = None
        self._on_settings_changed: ButtonInputSettingsChangedCallback | None = None

        # ---- click detector (state machine) --------------------------
        valid_keys = {
            "tip_timeout",
            "multi_click_window",
            "hold_repeat_interval",
            "use_tip_events",
        }
        config = {
            k: v for k, v in (click_detector_config or {}).items() if k in valid_keys
        }
        self._click_detector = ClickDetector(
            on_click=self._on_click_detected,
            **config,
        )

    # ---- read-only accessors -----------------------------------------

    @property
    def ds_index(self) -> int:
        """Zero-based index (``dsIndex``)."""
        return self._ds_index

    @property
    def name(self) -> str:
        """Human-readable label for this button element."""
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value

    @property
    def supports_local_key_mode(self) -> bool:
        """Whether this button can be a local button."""
        return self._supports_local_key_mode

    @property
    def button_id(self) -> int | None:
        """Physical button ID (shared by all elements of one button).

        ``None`` means no fixed assignment.
        """
        return self._button_id

    @property
    def button_type(self) -> ButtonType:
        """Physical button type."""
        return self._button_type

    @property
    def button_element_id(self) -> ButtonElementID:
        """Element within a multi-contact button."""
        return self._button_element_id

    @property
    def vdsd(self) -> Vdsd:
        """The owning :class:`Vdsd`."""
        return self._vdsd

    @property
    def click_detector(self) -> ClickDetector:
        """The built-in click detection state machine."""
        return self._click_detector

    # ---- settings accessors (writable, persisted) --------------------

    @property
    def group(self) -> int:
        """dS group number (writable, persisted)."""
        return self._group

    @group.setter
    def group(self, value: int) -> None:
        self._group = int(value)
        self._function = button_function_for_group(self._group, int(self._function))
        self._schedule_auto_save()

    @property
    def function(self) -> ButtonFunction | ButtonFunctionJoker | int:
        """Button function / LTNUM (writable, persisted)."""
        return self._function

    @function.setter
    def function(self, value: ButtonFunction | ButtonFunctionJoker | int) -> None:
        self._function = button_function_for_group(self._group, int(value))
        self._schedule_auto_save()

    @property
    def mode(self) -> ButtonMode:
        """Button mode / LTMODE (writable, persisted)."""
        return self._mode

    @mode.setter
    def mode(self, value: ButtonMode | int) -> None:
        self._mode = ButtonMode(int(value))
        self._schedule_auto_save()

    @property
    def channel(self) -> int:
        """Output channel this button controls (writable, persisted).

        ``0`` = default channel.
        """
        return self._channel

    @channel.setter
    def channel(self, value: int) -> None:
        self._channel = int(value)
        self._schedule_auto_save()

    @property
    def sets_local_priority(self) -> bool:
        """Whether button sets local priority (writable, persisted)."""
        return self._sets_local_priority

    @sets_local_priority.setter
    def sets_local_priority(self, value: bool) -> None:
        self._sets_local_priority = bool(value)
        self._schedule_auto_save()

    @property
    def calls_present(self) -> bool:
        """Whether button calls present on absent (writable, persisted)."""
        return self._calls_present

    @calls_present.setter
    def calls_present(self, value: bool) -> None:
        self._calls_present = bool(value)
        self._schedule_auto_save()

    # ---- state accessors (volatile) ----------------------------------

    @property
    def value(self) -> bool | None:
        """Current boolean value (``None`` = unknown).

        ``True`` = active (pressed), ``False`` = inactive (released).

        Note: For buttons the real information carrier is
        :attr:`click_type` or :attr:`action_id`, not this value.
        """
        return self._value

    @property
    def click_type(self) -> ButtonClickType:
        """Most recent click type (default ``IDLE``)."""
        return self._click_type

    @property
    def action_id(self) -> int | None:
        """Scene ID of the most recent direct action call.

        ``None`` when the last event was a click, not an action.
        """
        return self._action_id

    @property
    def action_mode(self) -> ActionMode | None:
        """Action mode of the most recent direct action call.

        ``None`` when the last event was a click, not an action.
        """
        return self._action_mode

    @property
    def age(self) -> float | None:
        """Seconds since the last state event (``None`` = unknown)."""
        if self._last_update is None:
            return None
        return time.monotonic() - self._last_update

    @property
    def error(self) -> InputError:
        """Current error status."""
        return self._error

    @error.setter
    def error(self, value: InputError | int) -> None:
        self._error = InputError(int(value))

    # ---- state machine (press / release) API -------------------------

    def press(self) -> None:
        """Signal a physical button press.

        Feeds the built-in :class:`ClickDetector`.  When the state
        machine resolves the timing pattern, the resulting click event
        is pushed to the vdSM automatically.

        Also updates :attr:`value` to ``True`` immediately so that
        property queries return the current physical state.
        """
        self._value = True
        self._click_detector.press()

    def release(self) -> None:
        """Signal a physical button release.

        Feeds the built-in :class:`ClickDetector`.

        Also updates :attr:`value` to ``False`` immediately.
        """
        self._value = False
        self._click_detector.release()

    # ---- direct click type update ------------------------------------

    async def update_click(
        self,
        click_type: ButtonClickType | int,
        value: bool | None = None,
        session: VdcSession | None = None,
    ) -> None:
        """Set the click type directly and push state.

        Use this when the physical device can directly report click
        events, bypassing the built-in :class:`ClickDetector`.

        Parameters
        ----------
        click_type:
            The resolved click event.
        value:
            Optional current button state.  If ``None`` the existing
            :attr:`value` is kept.
        session:
            Active session for the push notification.  Falls back to
            the stored session if ``None``.
        """
        self._click_type = ButtonClickType(int(click_type))
        if value is not None:
            self._value = value
        self._last_update = time.monotonic()
        self._last_state_is_action = False
        logger.debug(
            "ButtonInput[%d] '%s' clickType → %s (value=%s)",
            self._ds_index,
            self._name,
            self._click_type.name,
            self._value,
        )
        await self._push_state(session or self._session)

    # ---- direct action update ----------------------------------------

    async def update_action(
        self,
        action_id: int,
        action_mode: ActionMode | int = ActionMode.NORMAL,
        session: VdcSession | None = None,
    ) -> None:
        """Set a direct scene call and push state.

        Use this when the button directly calls a scene instead of
        generating a click event.  The resulting push notification
        carries ``actionId`` and ``actionMode`` instead of ``value``
        and ``clickType``.

        Parameters
        ----------
        action_id:
            Scene number to call.
        action_mode:
            How the scene is applied (normal / force / undo).
        session:
            Active session for the push notification.
        """
        self._action_id = action_id
        self._action_mode = ActionMode(int(action_mode))
        self._last_update = time.monotonic()
        self._last_state_is_action = True
        logger.debug(
            "ButtonInput[%d] '%s' actionId → %d (mode=%s)",
            self._ds_index,
            self._name,
            action_id,
            self._action_mode.name,
        )
        await self._push_state(session or self._session)

    # ---- error update ------------------------------------------------

    async def update_error(
        self,
        error: InputError | int,
        session: VdcSession | None = None,
    ) -> None:
        """Set the error status and push a state notification.

        Parameters
        ----------
        error:
            Updated error code.
        session:
            Active session for the push notification.
        """
        self._error = InputError(int(error))
        logger.debug(
            "ButtonInput[%d] '%s' error → %s",
            self._ds_index,
            self._name,
            self._error.name,
        )
        await self._push_state(session or self._session)

    # ---- click detector callback (internal) --------------------------

    async def _on_click_detected(
        self, click_type: ButtonClickType, value: bool
    ) -> None:
        """Called by the :class:`ClickDetector` when an event resolves.

        Updates internal state and pushes to the vdSM.
        """
        self._click_type = click_type
        self._value = value
        self._last_update = time.monotonic()
        self._last_state_is_action = False
        logger.debug(
            "ButtonInput[%d] '%s' click detected: %s (value=%s)",
            self._ds_index,
            self._name,
            click_type.name,
            value,
        )
        await self._push_state(self._session)

    # ---- property dicts (for getProperty responses) ------------------

    def get_description_properties(self) -> dict[str, Any]:
        """Return the ``buttonInputDescriptions[N]`` property dict.

        These are read-only hardware characteristics.
        """
        desc: dict[str, Any] = {
            "name": self._name,
            "dsIndex": self._ds_index,
            "supportsLocalKeyMode": self._supports_local_key_mode,
            "buttonType": int(self._button_type),
            "buttonElementID": int(self._button_element_id),
        }
        if self._button_id is not None:
            desc["buttonID"] = self._button_id
        return desc

    def get_settings_properties(self) -> dict[str, Any]:
        """Return the ``buttonInputSettings[N]`` property dict.

        These are read/write, persisted.
        """
        return {
            "group": self._group,
            "function": int(self._function),
            "mode": int(self._mode),
            "channel": self._channel,
            "setsLocalPriority": self._sets_local_priority,
            "callsPresent": self._calls_present,
        }

    def get_state_properties(self) -> dict[str, Any]:
        """Return the ``buttonInputStates[N]`` property dict.

        The format depends on the most recent event type:

        * **Click mode** — ``value``, ``clickType``, ``age``, ``error``
        * **Action mode** — ``actionId``, ``actionMode``, ``age``,
          ``error``
        """
        state: dict[str, Any] = {}

        if self._last_state_is_action:
            state["actionId"] = self._action_id
            state["actionMode"] = (
                int(self._action_mode)
                if self._action_mode is not None
                else int(ActionMode.NORMAL)
            )
        else:
            state["value"] = self._value  # may be None (NULL)
            state["clickType"] = int(self._click_type)

        state["age"] = self.age  # may be None (NULL)
        state["error"] = int(self._error)
        return state

    # ---- settings mutation (called from vdc_host setProperty) --------

    def apply_settings(self, incoming: dict[str, Any]) -> None:
        """Apply writable settings from a ``setProperty`` request.

        Parameters
        ----------
        incoming:
            Dict of setting name → value (e.g.
            ``{"group": 1, "function": 5, "mode": 0}``).
        """
        changed = False
        if "group" in incoming:
            self._group = int(incoming["group"])
            changed = True
        if "function" in incoming:
            self._function = button_function_for_group(
                self._group, int(incoming["function"])
            )
            changed = True
        if "mode" in incoming:
            self._mode = ButtonMode(int(incoming["mode"]))
            changed = True
        if "channel" in incoming:
            self._channel = int(incoming["channel"])
            changed = True
        if "setsLocalPriority" in incoming:
            self._sets_local_priority = bool(incoming["setsLocalPriority"])
            changed = True
        if "callsPresent" in incoming:
            self._calls_present = bool(incoming["callsPresent"])
            changed = True
        if changed:
            logger.debug(
                "ButtonInput[%d] settings updated: group=%d, "
                "function=%s, mode=%s, channel=%d",
                self._ds_index,
                self._group,
                getattr(self._function, "name", self._function),
                self._mode.name,
                self._channel,
            )
            self._schedule_auto_save()

    @property
    def on_settings_changed(self) -> ButtonInputSettingsChangedCallback | None:
        """Callback invoked when the vdSM writes ``buttonInputSettings``."""
        return self._on_settings_changed

    @on_settings_changed.setter
    def on_settings_changed(
        self, callback: ButtonInputSettingsChangedCallback | None
    ) -> None:
        self._on_settings_changed = callback

    # ---- persistence -------------------------------------------------

    def get_property_tree(self) -> dict[str, Any]:
        """Return the persisted representation of this button input.

        Only description and settings properties are included (state
        is volatile and not persisted).
        """
        tree: dict[str, Any] = {
            "dsIndex": self._ds_index,
            "name": self._name,
            "supportsLocalKeyMode": self._supports_local_key_mode,
            "buttonType": int(self._button_type),
            "buttonElementID": int(self._button_element_id),
        }
        if self._button_id is not None:
            tree["buttonID"] = self._button_id
        # Settings (writable)
        tree.update(
            {
                "group": self._group,
                "function": int(self._function),
                "mode": int(self._mode),
                "channel": self._channel,
                "setsLocalPriority": self._sets_local_priority,
                "callsPresent": self._calls_present,
            }
        )
        return tree

    def _apply_state(self, state: dict[str, Any]) -> None:
        """Restore from a persisted property tree dict.

        Restores both description and settings properties.  State
        properties are left at their defaults (unknown / IDLE / OK).
        """
        # Description
        if "dsIndex" in state:
            self._ds_index = int(state["dsIndex"])
        if "name" in state:
            self._name = state["name"]
        if "supportsLocalKeyMode" in state:
            self._supports_local_key_mode = bool(state["supportsLocalKeyMode"])
        if "buttonID" in state:
            self._button_id = int(state["buttonID"])
        if "buttonType" in state:
            self._button_type = ButtonType(int(state["buttonType"]))
        if "buttonElementID" in state:
            self._button_element_id = ButtonElementID(int(state["buttonElementID"]))
        # Settings
        if "group" in state:
            self._group = int(state["group"])
        if "function" in state:
            self._function = button_function_for_group(
                self._group, int(state["function"])
            )
        if "mode" in state:
            self._mode = ButtonMode(int(state["mode"]))
        if "channel" in state:
            self._channel = int(state["channel"])
        if "setsLocalPriority" in state:
            self._sets_local_priority = bool(state["setsLocalPriority"])
        if "callsPresent" in state:
            self._calls_present = bool(state["callsPresent"])

    # ---- push notification -------------------------------------------

    async def _push_state(
        self,
        session: VdcSession | None,
    ) -> None:
        """Push current state to the vdSM.

        Unlike binary/sensor inputs, button events are pushed
        immediately without throttling (no ``minPushInterval`` or
        ``changesOnlyInterval``).
        """
        if session is None:
            return
        if not self._vdsd.is_announced:
            logger.debug(
                "ButtonInput[%d]: vdSD not announced — skipping push",
                self._ds_index,
            )
            return

        state_dict = self.get_state_properties()

        push_tree: dict[str, Any] = {
            "buttonInputStates": {
                str(self._ds_index): state_dict,
            }
        }

        msg = pb.Message()
        msg.type = pb.VDC_SEND_PUSH_NOTIFICATION
        msg.vdc_send_push_notification.dSUID = str(self._vdsd.dsuid)
        for elem in dict_to_elements(push_tree):
            msg.vdc_send_push_notification.changedproperties.append(elem)

        try:
            await session.send_notification(msg)
            logger.debug(
                "ButtonInput[%d] '%s': pushed state %s for vdSD %s",
                self._ds_index,
                self._name,
                state_dict,
                self._vdsd.dsuid,
            )
        except (ConnectionError, OSError) as exc:
            logger.warning(
                "ButtonInput[%d] '%s': failed to push state: %s",
                self._ds_index,
                self._name,
                exc,
            )

    async def push_settings(self, session: VdcSession | None = None) -> None:
        """Push the current ``buttonInputSettings`` to the vdSM.

        Sends a ``VDC_SEND_PUSH_NOTIFICATION`` carrying the full
        ``buttonInputSettings`` subtree for this input.  A no-op if no
        session is active or the vdSD is not announced.
        """
        session = session or self._session
        if session is None:
            logger.debug(
                "ButtonInput[%d]: no active session — skipping push_settings",
                self._ds_index,
            )
            return
        if not self._vdsd.is_announced:
            logger.debug(
                "ButtonInput[%d]: vdSD not announced — skipping push_settings",
                self._ds_index,
            )
            return

        settings_dict = self.get_settings_properties()
        push_tree: dict[str, Any] = {
            "buttonInputSettings": {str(self._ds_index): settings_dict}
        }

        msg = pb.Message()
        msg.type = pb.VDC_SEND_PUSH_NOTIFICATION
        msg.vdc_send_push_notification.dSUID = str(self._vdsd.dsuid)
        for elem in dict_to_elements(push_tree):
            msg.vdc_send_push_notification.changedproperties.append(elem)

        try:
            await session.send_notification(msg)
            logger.debug(
                "ButtonInput[%d]: pushed settings for vdSD %s",
                self._ds_index,
                self._vdsd.dsuid,
            )
        except (ConnectionError, OSError) as exc:
            logger.warning(
                "ButtonInput[%d]: failed to push settings: %s",
                self._ds_index,
                exc,
            )

    # ---- session management ------------------------------------------
    #
    #  Buttons do NOT have alive timers.  These methods follow the
    #  same naming convention as BinaryInput / SensorInput so that
    #  Vdsd.announce() / vanish() / reset_announcement() can use a
    #  uniform loop across all component types.

    def start_alive_timer(self, session: VdcSession) -> None:
        """Store the session reference for push notifications.

        Called when the vdSD is announced.  Unlike binary/sensor
        inputs, buttons do not start an actual alive timer — this
        method just records the session so that click or action
        events can be pushed.
        """
        self._session = session

    def stop_alive_timer(self) -> None:
        """Clear the session and stop the click detector.

        Called when the vdSD vanishes or the session disconnects.
        """
        self._click_detector.stop()
        self._session = None

    # ---- auto-save ---------------------------------------------------

    def _schedule_auto_save(self) -> None:
        """Trigger a debounced auto-save up through the Vdsd → Device
        → Vdc → VdcHost chain."""
        device = getattr(self._vdsd, "_device", None)
        if device is not None:
            device._schedule_auto_save()

    # ---- dunder ------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"ButtonInput(ds_index={self._ds_index}, "
            f"name={self._name!r}, "
            f"type={self._button_type.name}, "
            f"element={self._button_element_id.name})"
        )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def get_required_elements(
    button_type: ButtonType,
) -> list[ButtonElementID]:
    """Return the standard :class:`ButtonElementID` values for a button type.

    Parameters
    ----------
    button_type:
        The physical button type.

    Returns
    -------
    list[ButtonElementID]
        Element IDs required for that type.  Empty for
        ``UNDEFINED`` (layout is application-defined).
    """
    return list(BUTTON_TYPE_ELEMENTS.get(button_type, []))


def create_button_group(
    vdsd: Vdsd,
    button_id: int,
    button_type: ButtonType,
    *,
    start_index: int = 0,
    name_prefix: str = "Button",
    supports_local_key_mode: bool = False,
    group: int = 0,
    function: ButtonFunction | int = ButtonFunction.DEVICE,
    mode: ButtonMode | int = ButtonMode.STANDARD,
    channel: int = 0,
    sets_local_priority: bool = False,
    calls_present: bool = False,
    click_detector_config: dict[str, Any] | None = None,
) -> list[ButtonInput]:
    """Create all :class:`ButtonInput` instances for a multi-element button.

    The button type determines how many elements are created and which
    :class:`ButtonElementID` each receives.  All elements share the
    same ``button_id``.

    .. note::

       The returned instances are **not** automatically added to
       *vdsd*.  Call ``vdsd.add_button_input(btn)`` for each one.

    Parameters
    ----------
    vdsd:
        The owning vdSD.
    button_id:
        Physical button ID shared by all elements.
    button_type:
        Physical button type.
    start_index:
        Starting ``dsIndex`` for the first element.  Subsequent
        elements get consecutive indices.
    name_prefix:
        Prefix for auto-generated element names (e.g.
        ``"Button Up"``, ``"Button Down"``).
    supports_local_key_mode:
        Applied to every element.
    group, function, mode, channel, sets_local_priority, calls_present:
        Settings applied to every element.
    click_detector_config:
        Timing overrides applied to every element's ClickDetector.

    Returns
    -------
    list[ButtonInput]
        One :class:`ButtonInput` per element.

    Raises
    ------
    ValueError
        If *button_type* is ``UNDEFINED`` (which has no standard
        element layout).
    """
    elements = get_required_elements(button_type)
    if not elements:
        raise ValueError(
            f"ButtonType.{button_type.name} has no standard element "
            f"layout — create ButtonInput instances manually."
        )

    buttons: list[ButtonInput] = []
    for i, element_id in enumerate(elements):
        element_label = element_id.name.replace("_", " ").title()
        btn = ButtonInput(
            vdsd=vdsd,
            ds_index=start_index + i,
            name=f"{name_prefix} {element_label}",
            supports_local_key_mode=supports_local_key_mode,
            button_id=button_id,
            button_type=button_type,
            button_element_id=element_id,
            group=group,
            function=function,
            mode=mode,
            channel=channel,
            sets_local_priority=sets_local_priority,
            calls_present=calls_present,
            click_detector_config=click_detector_config,
        )
        buttons.append(btn)
    return buttons
