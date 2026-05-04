"""Mock device simulators for the developer guide demo.

Each ``Mock*`` class wraps a fully configured :class:`Device` and
simulates periodic sensor readings, button presses, binary-input
toggles, and other hardware-level activity in the background.

The mocks are **not** pydsvdcapi components — they model what a real
hardware driver would do: call ``update_value()`` on sensors, ``press()``
/ ``release()`` on buttons, etc.  Think of them as tiny stand-ins for
Zigbee, KNX, or GPIO bridges.

Each mock has:

* ``start()``  — launch a background :class:`asyncio.Task`.
* ``stop()``   — cancel the background task gracefully.
* One or more ``trigger_*()`` helpers for the interactive menu.

The ``TICK`` constant (seconds) controls the simulation resolution.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional

from pydsvdcapi import (
    BinaryInput,
    ButtonInput,
    Device,
    DeviceEvent,
    DeviceProperty,
    Output,
    OutputChannelType,
    SensorInput,
    Vdsd,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

#: Simulation tick interval in seconds.
TICK: float = 0.5

# ANSI colour shortcuts (duplicated here so mock_devices.py stays
# self-contained — the demo file has its own copy).
_RST = "\033[0m"
_CYN = "\033[96m"
_MAG = "\033[95m"
_YEL = "\033[93m"
_GRN = "\033[92m"


def _first_vdsd(device: Device) -> Vdsd:
    """Return the first (and usually only) vdSD of *device*."""
    return next(iter(device.vdsds.values()))


# ===========================================================================
# Mock 1 — Simple pushbutton + on/off brightness
# ===========================================================================


class MockDevice1:
    """Simulates a simple on/off light with a single pushbutton.

    Background behaviour (every ``TICK``):
    * Every ~6 s randomly presses and releases the button (click).

    The output brightness is controlled by the dSS via scenes; the mock
    does **not** change the channel value itself.
    """

    def __init__(self, device: Device) -> None:
        self._vdsd = _first_vdsd(device)
        self._btn: ButtonInput = self._vdsd.button_inputs[0]
        self._output: Output = self._vdsd.output
        self._task: Optional[asyncio.Task] = None
        self._log = logging.getLogger("mock-1")

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        cycle = 0
        try:
            while True:
                # Simulate a button click roughly every 6 s.
                if cycle % 12 == 0 and cycle > 0:
                    self._btn.press()
                    await asyncio.sleep(0.08)
                    self._btn.release()
                    self._log.info(
                        "%s[1] Button%s click (press+release)",
                        _CYN,
                        _RST,
                    )
                cycle += 1
                await asyncio.sleep(TICK)
        except asyncio.CancelledError:
            raise


# ===========================================================================
# Mock 2 — 2-way button + dimmer (brightness + colour temperature)
# ===========================================================================


class MockDevice2:
    """Simulates a CT-dimmable light with a two-way rocker button.

    Background behaviour:
    * Every ~8 s presses one of the two rocker elements (UP / DOWN).
    * The output channels are driven by the dSS via scenes; the mock
      does not change them directly.
    """

    def __init__(self, device: Device) -> None:
        self._vdsd = _first_vdsd(device)
        # Two-way button creates two ButtonInput elements (DOWN=idx0, UP=idx1).
        self._btn_down: ButtonInput = self._vdsd.button_inputs[0]
        self._btn_up: ButtonInput = self._vdsd.button_inputs[1]
        self._output: Output = self._vdsd.output
        self._task: Optional[asyncio.Task] = None
        self._log = logging.getLogger("mock-2")

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        cycle = 0
        try:
            while True:
                if cycle % 16 == 0 and cycle > 0:
                    # Alternate between UP and DOWN.
                    btn = self._btn_up if (cycle // 16) % 2 == 0 else self._btn_down
                    btn.press()
                    await asyncio.sleep(0.08)
                    btn.release()
                    self._log.info(
                        "%s[2] Rocker%s %s click",
                        _CYN,
                        _RST,
                        "UP" if btn is self._btn_up else "DOWN",
                    )
                cycle += 1
                await asyncio.sleep(TICK)
        except asyncio.CancelledError:
            raise


# ===========================================================================
# Mock 3 — Garage-door contact (binary) + blinds output
# ===========================================================================


class MockDevice3:
    """Simulates a garage-door contact and motorised blinds.

    Background behaviour:
    * Every ~10 s toggles the garage-door open/closed state with 30 % probability.
    * Slowly drifts the shade position and blade angle to simulate motor
      movement (±0.5 % per tick) and pushes the value.
    """

    def __init__(self, device: Device) -> None:
        self._vdsd = _first_vdsd(device)
        self._bi: BinaryInput = self._vdsd.binary_inputs[0]
        self._output: Output = self._vdsd.output
        self._task: Optional[asyncio.Task] = None
        self._log = logging.getLogger("mock-3")
        self._door_open = False
        self._shade_pos = 0.0
        self._blade_angle = 50.0

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        cycle = 0
        try:
            while True:
                # Toggle garage-door state every ~10 s with 30 % chance.
                if cycle % 20 == 0 and random.random() < 0.30:
                    self._door_open = not self._door_open
                    await self._bi.update_value(self._door_open)
                    self._log.info(
                        "%s[3] Garage door%s → %s",
                        _CYN,
                        _RST,
                        "OPEN" if self._door_open else "closed",
                    )

                # Drift shade position and blade angle.
                self._shade_pos = max(
                    0.0,
                    min(
                        100.0,
                        self._shade_pos + random.uniform(-0.5, 0.5),
                    ),
                )
                self._blade_angle = max(
                    0.0,
                    min(
                        100.0,
                        self._blade_angle + random.uniform(-0.5, 0.5),
                    ),
                )
                ch_pos = self._output.get_channel_by_type(
                    OutputChannelType.SHADE_POSITION_OUTSIDE,
                )
                ch_angle = self._output.get_channel_by_type(
                    OutputChannelType.SHADE_OPENING_ANGLE_OUTSIDE,
                )
                if ch_pos is not None:
                    await ch_pos.update_value(round(self._shade_pos, 1))
                if ch_angle is not None:
                    await ch_angle.update_value(round(self._blade_angle, 1))

                cycle += 1
                await asyncio.sleep(TICK)
        except asyncio.CancelledError:
            raise


# ===========================================================================
# Mock 4 — Illumination + Active-Power sensors + RGBW output
# ===========================================================================


class MockDevice4:
    """Simulates two sensors (illumination + active power) and RGBW output.

    Background behaviour:
    * Every ~5 s pushes new illumination and active-power readings.
    * Slowly drifts RGBW output channels.
    """

    def __init__(self, device: Device) -> None:
        self._vdsd = _first_vdsd(device)
        self._si_lux: SensorInput = self._vdsd.sensor_inputs[0]
        self._si_power: SensorInput = self._vdsd.sensor_inputs[1]
        self._output: Output = self._vdsd.output
        self._task: Optional[asyncio.Task] = None
        self._log = logging.getLogger("mock-4")
        # Simulated readings.
        self._lux = 350.0
        self._watts = 42.0
        # RGBW state.
        self._brightness = 80.0
        self._hue = 180.0
        self._saturation = 60.0

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._run())
        # Push initial sensor values immediately.
        asyncio.ensure_future(self._si_lux.update_value(self._lux))
        asyncio.ensure_future(self._si_power.update_value(self._watts))

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        cycle = 0
        try:
            while True:
                # Push sensor readings every ~5 s.
                if cycle % 10 == 0:
                    self._lux = max(
                        0.0,
                        min(
                            100_000.0,
                            self._lux + random.uniform(-20.0, 20.0),
                        ),
                    )
                    self._watts = max(
                        0.0,
                        min(
                            3680.0,
                            self._watts + random.uniform(-2.0, 2.0),
                        ),
                    )
                    await self._si_lux.update_value(round(self._lux, 1))
                    await self._si_power.update_value(round(self._watts, 1))
                    self._log.info(
                        "%s[4] Sensors%s  lux=%.1f  power=%.1f W",
                        _MAG,
                        _RST,
                        self._lux,
                        self._watts,
                    )

                # Drift RGBW channels slowly.
                self._brightness = max(
                    0.0,
                    min(
                        100.0,
                        self._brightness + random.uniform(-1.0, 1.0),
                    ),
                )
                self._hue = (self._hue + random.uniform(-2.0, 2.0)) % 360.0
                self._saturation = max(
                    0.0,
                    min(
                        100.0,
                        self._saturation + random.uniform(-1.0, 1.0),
                    ),
                )

                ch_br = self._output.get_channel_by_type(OutputChannelType.BRIGHTNESS)
                ch_hue = self._output.get_channel_by_type(OutputChannelType.HUE)
                ch_sat = self._output.get_channel_by_type(OutputChannelType.SATURATION)
                if ch_br:
                    await ch_br.update_value(round(self._brightness, 1))
                if ch_hue:
                    await ch_hue.update_value(round(self._hue, 1))
                if ch_sat:
                    await ch_sat.update_value(round(self._saturation, 1))

                cycle += 1
                await asyncio.sleep(TICK)
        except asyncio.CancelledError:
            raise


# ===========================================================================
# Mock 5 — Custom property + event + action (SingleDevice / White)
# ===========================================================================


class MockDevice5:
    """Simulates a white (SingleDevice) with property, event, and action.

    Background behaviour:
    * Every ~10 s increments the custom device property (counter).
    * The event is raised only via ``trigger_event()``.

    Interactive triggers:
    * ``trigger_event()`` — fire the device event to the dSS.
    """

    def __init__(self, device: Device) -> None:
        self._vdsd = _first_vdsd(device)
        self._prop: DeviceProperty = self._vdsd.device_properties[0]
        self._event: DeviceEvent = self._vdsd.device_events[0]
        self._task: Optional[asyncio.Task] = None
        self._log = logging.getLogger("mock-5")
        self._counter = 0.0

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        cycle = 0
        try:
            while True:
                # Increment the counter every ~10 s.
                if cycle % 20 == 0 and cycle > 0:
                    self._counter += 1.0
                    await self._prop.update_value(self._counter)
                    self._log.info(
                        "%s[5] Property%s counter → %.0f",
                        _MAG,
                        _RST,
                        self._counter,
                    )
                cycle += 1
                await asyncio.sleep(TICK)
        except asyncio.CancelledError:
            raise

    async def trigger_event(self) -> None:
        """Fire the device event (called from the interactive menu)."""
        await self._event.raise_event()
        self._log.info(
            "%s[5] Event%s 'customAlert' raised!",
            _MAG,
            _RST,
        )
