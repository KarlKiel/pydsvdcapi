# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024–2026 Arne Speck
"""digitalSTROM vDC API enumerations.

This module contains all enum definitions required by the digitalSTROM
vDC API protocol, derived from the official documentation:

- ds-basics.pdf (v1.6, May 2020)
- vDC API specification
- vDC API properties specification
- vdcapi.proto
- vdc_messages.proto
- re-engineering of dss-mainline-master
- live testing against dss (1.19.12)
"""

from enum import Enum, IntEnum, unique

# ---------------------------------------------------------------------------
#  Protocol-level enums (from genericVDC.proto)
# ---------------------------------------------------------------------------


@unique
class MessageType(IntEnum):
    """Protobuf message type identifiers (``Type`` enum in genericVDC.proto)."""

    GENERIC_RESPONSE = 1

    VDSM_REQUEST_HELLO = 2
    VDC_RESPONSE_HELLO = 3

    VDSM_REQUEST_GET_PROPERTY = 4
    VDC_RESPONSE_GET_PROPERTY = 5

    VDSM_REQUEST_SET_PROPERTY = 6
    # VDC_RESPONSE_SET_PROPERTY uses GENERIC_RESPONSE (field 7 in proto)

    VDSM_SEND_PING = 8
    VDC_SEND_PONG = 9

    VDC_SEND_ANNOUNCE_DEVICE = 10
    VDC_SEND_VANISH = 11
    VDC_SEND_PUSH_NOTIFICATION = 12

    VDSM_SEND_REMOVE = 13
    VDSM_SEND_BYE = 14

    VDSM_NOTIFICATION_CALL_SCENE = 15
    VDSM_NOTIFICATION_SAVE_SCENE = 16
    VDSM_NOTIFICATION_UNDO_SCENE = 17
    VDSM_NOTIFICATION_SET_LOCAL_PRIO = 18
    VDSM_NOTIFICATION_CALL_MIN_SCENE = 19
    VDSM_NOTIFICATION_IDENTIFY = 20
    VDSM_NOTIFICATION_SET_CONTROL_VALUE = 21

    VDC_SEND_IDENTIFY = 22
    VDC_SEND_ANNOUNCE_VDC = 23

    VDSM_NOTIFICATION_DIM_CHANNEL = 24
    VDSM_NOTIFICATION_SET_OUTPUT_CHANNEL_VALUE = 25

    VDSM_REQUEST_GENERIC_REQUEST = 26


@unique
class ResultCode(IntEnum):
    """Result codes returned in ``GenericResponse`` messages."""

    ERR_OK = 0
    ERR_MESSAGE_UNKNOWN = 1
    ERR_INCOMPATIBLE_API = 2
    ERR_SERVICE_NOT_AVAILABLE = 3
    ERR_INSUFFICIENT_STORAGE = 4
    ERR_FORBIDDEN = 5
    ERR_NOT_IMPLEMENTED = 6
    ERR_NO_CONTENT_FOR_ARRAY = 7
    ERR_INVALID_VALUE_TYPE = 8
    ERR_MISSING_SUBMESSAGE = 9
    ERR_MISSING_DATA = 10
    ERR_NOT_FOUND = 11
    ERR_NOT_AUTHORIZED = 12


@unique
class ErrorType(IntEnum):
    """Error category sent alongside ``GenericResponse``."""

    FAILED = 0
    OVERLOADED = 1
    DISCONNECTED = 2
    UNIMPLEMENTED = 3


# ---------------------------------------------------------------------------
#  Addressable entity type
# ---------------------------------------------------------------------------


@unique
class EntityType(IntEnum):
    """Type of addressable entity in the vDC host."""

    VDSD = 0
    VDC = 1
    VDC_HOST = 2
    VDSM = 3


# ---------------------------------------------------------------------------
#  Primary group (device colour) and application class (output profile)
# ---------------------------------------------------------------------------


@unique
class ColorGroup(IntEnum):
    """digitalSTROM primary group ID (``primaryGroup`` of a vdSD).

    Identifies the colour / functional category of the device as a whole.
    This value is sent in the ``primaryGroup`` field of the vdSD announcement.

    For primaryGroup **only values 1–9 are valid**.  The extended
    Blue sub-types 10 (Ventilation), 11 (Window), and 12 (Recirculation) exist
    partly for groups[] (only values <64 are supported) and defaultGroup and active Group (full colorClass see below).
    Use ``BLUE = 3`` for all climate sub-types
    (heating, cooling, ventilation, window openers, fan-coil units).

    **Do NOT use for output fields** (``Output.default_group``,
    ``Output.active_group``, ``Output.groups``) — those require
    :class:`ColorClass` values (dS Application Group IDs), which are a
    different integer set.

    **Do NOT use for input group fields** — button, binary-input, and sensor
    inputs each have their own enum (:class:`ButtonGroup`,
    :class:`BinaryInputGroup`, :class:`SensorGroup`).

    ``RED = 6`` and ``GREEN = 7`` are deprecated in the dSS firmware.
    Both outdoor and indoor shades use ``GREY = 2``.
    """

    YELLOW = 1  # gelb/Licht — Lights / Dimmers
    GREY = 2  # grau/Schatten — Shades (outdoor and indoor)
    BLUE = 3  # blau/Klima — All climate: heating, cooling, ventilation, windows, FCU
    CYAN = 4  # cyan/Audio — Audio
    MAGENTA = 5  # magenta/Video — Video
    RED = 6  # rot/Sicherheit — Security (deprecated)
    GREEN = 7  # grün/Zugang — Access control (deprecated)
    BLACK = 8  # schwarz/variabel — Joker / configurable
    WHITE = 9  # weiß/Einzelgerät — Single device / appliance


@unique
class ColorClass(IntEnum):
    """dS Application Group ID for output ``defaultGroup``, ``activeGroup``, and ``groups``.

    These are the official digitalSTROM Application Group IDs (ds-basics.pdf
    Table 2) used to identify the specific application profile of an output.
    Placed in ``outputDescription.defaultGroup``, ``outputSettings.activeGroup``,
    and ``outputSettings.groups``.

    **Range constraints:**

    * ``groups``: only values 1–63 are valid; global app groups (≥ 64) cannot
      appear in the group membership bitfield.
    * ``activeGroup``: if the value is < 64, it must also appear in ``groups``.
      Values ≥ 64 (global app groups) are exempt from this requirement.
    * ``defaultGroup``: informational; stored by dSS but not used at runtime.

    Typical mapping — ``primaryGroup`` (ColorGroup) sets the device colour;
    ``activeGroup`` / ``defaultGroup`` (ColorClass) sets the specific
    application sub-type within that colour:

    +---------------+---------+------------------------------+--------------+
    | ColorGroup    | pg value| ColorClass (activeGroup)     | Device type  |
    +===============+=========+==============================+==============+
    | YELLOW (1)    |    1    | LIGHTS (1)                   | Lights       |
    | GREY (2)      |    2    | BLINDS (2)                   | Shades       |
    | GREY (2)      |    2    | AWNINGS (65) (outside)       | AWNING       |
    | BLUE (3)      |    3    | HEATING (3)                  | Heating      |
    | BLUE (3)      |    3    | COOLING (9)                  | Cooling      |
    | BLUE (3)      |    3    | VENTILATION (10)             | Ventilation  |
    | BLUE (3)      |    3    | WINDOW (11)                  | Windows      |
    | BLUE (3)      |    3    | RECIRCULATION (12)           | Fan-coil     |
    | BLUE (3)      |    3    | TEMPERATURE_CONTROL (48)     | Temp control |
    | BLUE (3)      |    3    | APARTMENT_VENTILATION (64)   | Apt. vent.   |
    | BLUE (3)      |    3    | APARTEMENT_RECICULATION (69) | Apt. recirc. |
    | CYAN (4)      |    4    | AUDIO (4)                    | Audio        |
    | MAGENTA (5)   |    5    | VIDEO (5)                    | Video        |
    | RED (6)       |    6    | SECURITY (6)  [deprecated]   | Alarms       |
    | GREEN (7)     |    7    | ACCESS (7)    [deprecated]   | Door/access  |
    | BLACK (8)     |    8    | JOKER (8)                    | Joker        |
    | WHITE (9)     |    9    | NONE (0)                     | Appliance    |
    +---------------+---------+------------------------------+--------------+
    """

    NONE = 0  # No specific application (WHITE single devices)
    LIGHTS = 1  # Room lights → primary channel: brightness
    BLINDS = 2  # Shades, curtains, blinds, awnings → shade position
    HEATING = 3  # Heating → primary channel: heatingPower
    AUDIO = 4  # Audio / music → primary channel: audioVolume
    VIDEO = 5  # Video / TV → primary channel: audioVolume
    SECURITY = 6  # Security / alarms [deprecated ColorGroup RED]
    ACCESS = 7  # Access control / door bells [deprecated ColorGroup GREEN]
    JOKER = 8  # Joker / configurable (BLACK)
    COOLING = 9  # Cooling → primary channel: coolingCapacity
    VENTILATION = 10  # Room ventilation → primary channel: airFlowIntensity
    WINDOW = 11  # Window openers
    RECIRCULATION = 12  # Recirculation / fan-coil units → airFlowIntensity
    TEMPERATURE_CONTROL = 48  # Single-room temperature control (valid in groups)
    APARTMENT_VENTILATION = (
        64  # Apartment-wide ventilation system (NOT valid in groups)
    )
    AWNINGS = 65  # Awnings global app group (NOT valid in groups)
    APARTMENT_RECIRCULATION = 69  # Apartment-wide recirculation (NOT valid in groups)


# ---------------------------------------------------------------------------
#  Scene numbers  (ds-basics Appendix B)
# ---------------------------------------------------------------------------


@unique
class SceneNumber(IntEnum):
    """All defined digitalSTROM scene command indices (0 – 127).

    Scenes 0–63 are group-related; scenes 64–127 are group-independent.

    Scene commands operate on different layers depending on addressing:

    * **Apartment** (zone_id=0, group=0): system-wide states such as
      Absent/Present, Panic, Fire, weather alarms.  See `ApartmentScene`.
    * **Zone** (zone_id>0, group=0): zone states such as Deep Off, Standby,
      Zone Active, presence.  See `ZoneScene`.
    * **Zone+Group** (zone_id>0, group>0): group-related commands – presets,
      area scenes, stepping, temperature control, ventilation stages.
      Semantic interpretation depends on the group; see `LightScene`,
      `ShadeScene`, `AwningScene`, `AudioScene`, `TemperatureControlScene`,
      `VentilationScene`.
    * **Device** (single device): device-local operations such as Minimum,
      Maximum, Stop, DeviceOn/Off.  See `DeviceScene`.
    """

    # --- Presets 0–4 ---
    PRESET_0 = 0  # Off
    PRESET_1 = 5  # On
    PRESET_2 = 17
    PRESET_3 = 18
    PRESET_4 = 19

    # --- Area 1 ---
    AREA_1_OFF = 1
    AREA_1_ON = 6
    AREA_1_DEC = 42
    AREA_1_INC = 43
    AREA_1_STOP = 52

    # --- Area 2 ---
    AREA_2_OFF = 2
    AREA_2_ON = 7
    AREA_2_DEC = 44
    AREA_2_INC = 45
    AREA_2_STOP = 53

    # --- Area 3 ---
    AREA_3_OFF = 3
    AREA_3_ON = 8
    AREA_3_DEC = 46
    AREA_3_INC = 47
    AREA_3_STOP = 54

    # --- Area 4 ---
    AREA_4_OFF = 4
    AREA_4_ON = 9
    AREA_4_DEC = 48
    AREA_4_INC = 49
    AREA_4_STOP = 55

    # --- Stepping ---
    AREA_STEPPING_CONTINUE = 10
    DECREMENT = 11
    INCREMENT = 12

    # --- Special ---
    MINIMUM = 13
    MAXIMUM = 14
    STOP = 15

    # --- Presets 10–14 ---
    PRESET_10 = 32
    PRESET_11 = 33
    PRESET_12 = 20
    PRESET_13 = 21
    PRESET_14 = 22

    # --- Presets 20–24 ---
    PRESET_20 = 34
    PRESET_21 = 35
    PRESET_22 = 23
    PRESET_23 = 24
    PRESET_24 = 25

    # --- Presets 30–34 ---
    PRESET_30 = 36
    PRESET_31 = 37
    PRESET_32 = 26
    PRESET_33 = 27
    PRESET_34 = 28

    # --- Presets 40–44 ---
    PRESET_40 = 38
    PRESET_41 = 39
    PRESET_42 = 29
    PRESET_43 = 30
    PRESET_44 = 31

    # --- Device / local ---
    AUTO_OFF = 40
    IMPULSE = 41
    DEVICE_OFF = 50
    DEVICE_ON = 51
    SUN_PROTECTION = 56

    # --- Group-independent scenes (64–127) ---
    AUTO_STANDBY = 64
    PANIC = 65
    STANDBY = 67
    DEEP_OFF = 68
    SLEEPING = 69
    WAKEUP = 70
    PRESENT = 71
    ABSENT = 72
    DOOR_BELL = 73
    ALARM_1 = 74
    ZONE_ACTIVE = 75
    FIRE = 76
    ALARM_2 = 83
    ALARM_3 = 84
    ALARM_4 = 85
    WIND = 86
    NO_WIND = 87
    RAIN = 88
    NO_RAIN = 89
    HAIL = 90
    NO_HAIL = 91
    POLLUTION = 92
    BURGLARY = 93


# ---------------------------------------------------------------------------
#  Scene scope / addressing layer
# ---------------------------------------------------------------------------


@unique
class SceneScope(IntEnum):
    """Addressing scope at which a scene command is dispatched.

    The digitalSTROM system dispatches scene commands at different layers.
    The scope is determined by the ``zone_id`` and ``group`` parameters
    in the call-scene notification:

    * ``APARTMENT`` – zone_id=0, group=0: broadcast to every device in the
      installation.
    * ``ZONE`` – zone_id>0, group=0: broadcast to every device in the zone,
      regardless of group membership.
    * ``GROUP`` – zone_id>0, group>0 (or zone_id=0, group>0 for clusters):
      multicast to all devices of the addressed group (preferred method).
    * ``DEVICE`` – addressed to a single device (unicast).
    """

    APARTMENT = 0
    ZONE = 1
    GROUP = 2
    DEVICE = 3


# ---------------------------------------------------------------------------
#  Apartment-level scenes (zone_id=0, group=0)
# ---------------------------------------------------------------------------


@unique
class ApartmentScene(IntEnum):
    """Scene commands with apartment-wide scope.

    These are dispatched with ``zone_id=0, group=0`` and represent system-wide
    states and signals.  All values are in the group-independent range 64–127,
    except for the apartment-mode/ventilation-level shortcuts that reuse
    group-related IDs interpreted at apartment scope.

    NOTE: Some known apartment states (sleeping/holiday, frost, day/night,
    smoke, gas, malfunction, service-required) do not have documented scene
    IDs and are typically implemented via state-change events or binary
    input events instead.
    """

    # --- Access ---
    PRESENT = 71  # residents came home (resets ABSENT)
    ABSENT = 72  # residents left home

    # --- Security ---
    PANIC = 65  # undo via undo-scene
    ALARM_1 = 74  # undo via undo-scene
    FIRE = 76  # undo via undo-scene
    ALARM_2 = 83  # undo via undo-scene
    ALARM_3 = 84  # undo via undo-scene
    ALARM_4 = 85  # undo via undo-scene
    POLLUTION = 92  # undo via undo-scene
    BURGLARY = 93  # undo via undo-scene

    # --- Weather ---
    WIND = 86  # reset by NO_WIND
    NO_WIND = 87
    RAIN = 88  # reset by NO_RAIN
    NO_RAIN = 89
    HAIL = 90  # reset by NO_HAIL (must be called with force flag)
    NO_HAIL = 91


# ---------------------------------------------------------------------------
#  Zone-level scenes (zone_id>0, group=0)
# ---------------------------------------------------------------------------


@unique
class ZoneScene(IntEnum):
    """Scene commands with zone scope (broadcast to all groups in a zone).

    Dispatched with a specific ``zone_id`` and ``group=0``.  These control
    the overall zone activity state and are group-independent.

    NOTE: Zone-level presence detection (scene 71/72) is unusual and
    typically only occurs when a presence sensor is configured as a zone
    device.  Motion, open-window, and open-door states are normally
    implemented via binary-input events rather than scene commands.
    """

    AUTO_STANDBY = 64  # zone auto-inactive
    STANDBY = 67  # zone inactive, user may return soon
    DEEP_OFF = 68  # zone inactive for longer time
    SLEEPING = 69
    WAKEUP = 70
    PRESENT = 71  # zone presence detected
    ABSENT = 72  # zone presence cleared
    DOOR_BELL = 73  # signal only, no state change
    ZONE_ACTIVE = 75  # zone will become active shortly


# ---------------------------------------------------------------------------
#  Group-specific scene interpretations (zone_id>0, group>0)
# ---------------------------------------------------------------------------


@unique
class LightScene(IntEnum):
    """Scene interpretation for the Lights group (group 1 / YELLOW).

    The same scene command IDs (0–9) have group-specific semantics.
    For lights: Off/On.
    """

    OFF = 0
    ON = 5
    AREA_1_OFF = 1
    AREA_1_ON = 6
    AREA_2_OFF = 2
    AREA_2_ON = 7
    AREA_3_OFF = 3
    AREA_3_ON = 8
    AREA_4_OFF = 4
    AREA_4_ON = 9


@unique
class ShadeScene(IntEnum):
    """Scene interpretation for the Shades / Blinds group (group 2 / GREY).

    For shades: Closed/Open instead of Off/On.
    """

    CLOSED = 0
    OPEN = 5
    AREA_1_CLOSED = 1
    AREA_1_OPEN = 6
    AREA_2_CLOSED = 2
    AREA_2_OPEN = 7
    AREA_3_CLOSED = 3
    AREA_3_OPEN = 8
    AREA_4_CLOSED = 4
    AREA_4_OPEN = 9


@unique
class AwningScene(IntEnum):
    """Scene interpretation for the Awning sub-group.

    Awnings use simplified In/Out semantics without area sub-groups.
    """

    IN = 0
    OUT = 5


@unique
class AudioScene(IntEnum):
    """Scene interpretation for the Audio group (group 4 / CYAN).

    For audio: Pause/Playing.  Volume control uses Area 1 DEC/INC
    scene IDs (42/43) at device scope.

    NOTE: Additional states (muted, power-off, standby, stop) do not
    have documented scene IDs.
    """

    PAUSE = 0
    PLAYING = 5


# ---------------------------------------------------------------------------
#  Device-level scenes (single device)
# ---------------------------------------------------------------------------


@unique
class DeviceScene(IntEnum):
    """Scene commands addressed to a single device.

    These are typically triggered by local pushbutton presses or by
    the zone state machine for device-specific operations.
    """

    MINIMUM = 13
    MAXIMUM = 14
    STOP = 15
    AUTO_OFF = 40  # slowly fade down to off
    IMPULSE = 41  # short impulse on output
    DEVICE_OFF = 50  # local pushbutton off
    DEVICE_ON = 51  # local pushbutton on
    SUN_PROTECTION = 56  # shade protection


@unique
class AudioDeviceScene(IntEnum):
    """Device-level scenes specific to audio devices.

    Volume stepping reuses Area 1 DEC/INC scene command IDs but is
    addressed to a single device (not visible in UI but functional).
    """

    VOLUME_DOWN = 42
    VOLUME_UP = 43


@unique
class ClimateDeviceScene(IntEnum):
    """Device-level scenes specific to climate (heating/cooling) devices.

    These overlap with ``TemperatureDeviceScene`` and provide an alias
    with clearer naming for common operations.
    """

    POWER_ON = 29
    POWER_OFF = 30
    VALVE_PROTECTION = 31
    FORCE_VALVE_OPEN = 32
    FORCE_VALVE_CLOSE = 33
    FORCE_FAN_MODE = 40
    FORCE_DRY_MODE = 41
    AUTOMATIC_MODE = 42


# ---------------------------------------------------------------------------
#  Apartment mode scenes  (reuse of group-related IDs at apartment scope)
# ---------------------------------------------------------------------------


@unique
class ApartmentTemperatureMode(IntEnum):
    """Apartment-wide temperature mode scenes.

    When called at apartment scope (zone_id=0, group=0) these group-related
    scene IDs control the global temperature operating mode.
    """

    OFF = 0  # temperature control off
    HEATING = 1  # global heating mode
    COOLING = 10  # global cooling mode
    AUTOMATIC = 42  # automatic heating/cooling


@unique
class ApartmentVentilationLevel(IntEnum):
    """Apartment-wide ventilation level scenes.

    When called at apartment scope (zone_id=0, group=0) these control the
    global ventilation level.  Values match ``VentilationScene``.
    """

    OFF = 0
    LEVEL_1 = 5
    LEVEL_2 = 17
    LEVEL_3 = 18
    LEVEL_4 = 19
    BOOST = 6
    NOISE_REDUCTION = 7
    AUTOMATIC = 8
    AUTO_LOUVER = 9


# ---------------------------------------------------------------------------
#  Zone temperature mode scenes  (zone+group scope)
# ---------------------------------------------------------------------------


@unique
class ZoneTemperatureMode(IntEnum):
    """Temperature mode scenes at zone level.

    These are called with a specific zone_id and the temperature control
    group.  Note that ``OFF`` here is scene 30 (Power Off), unlike
    ``TemperatureControlScene.HEATING_OFF`` which is scene 0.
    """

    OFF = 30  # power off climate device
    HEATING = 1  # heating comfort
    COOLING = 10  # cooling comfort
    AUTOMATIC = 42  # automatic mode


# ---------------------------------------------------------------------------
#  Output channel types  (ds-basics Table 6 / vDC API properties §4.9.4)
# ---------------------------------------------------------------------------


@unique
class OutputChannelType(IntEnum):
    """Standard output channel type identifiers (firmware-verified).

    Values are taken directly from the dSS firmware ChannelType enum
    (modelconst.h, DS_REFLECTED_ENUM sequential from 0).  The firmware
    casts the integer received from the vDC API directly to this enum
    (vdc-connection.cpp: static_cast<ChannelType>(fieldProp.getValueAsInt())),
    so these integer values must match exactly what the firmware expects.

    IDs 0–191 are reserved for standard types.
    IDs 192–239 are available for device-specific (proprietary) channels.
    """

    DEFAULT = 0  # none / catch-all
    BRIGHTNESS = 1
    HUE = 2
    SATURATION = 3
    COLOR_TEMPERATURE = 4  # mired (100–1000)
    CIE_X = 5
    CIE_Y = 6

    # Shade / blind channels (ids 7–11)
    SHADE_POSITION_OUTSIDE = 7  # roller blinds / external blinds, 0–100 %
    SHADE_POSITION_INDOOR = 8  # curtains / indoor blinds, 0–100 %
    SHADE_OPENING_ANGLE_OUTSIDE = 9
    SHADE_OPENING_ANGLE_INDOOR = 10
    TRANSPARENCY = 11

    # HVAC channels (ids 12–21)
    AIR_FLOW_INTENSITY = 12
    AIR_FLOW_DIRECTION = 13
    AIR_FLAP_POSITION = 14
    AIR_LOUVER_POSITION = 15
    HEATING_POWER = 16
    COOLING_CAPACITY = 17

    # Audio (id 18)
    AUDIO_VOLUME = 18

    # Power / general (id 19)
    POWER_STATE = 19

    # HVAC auto-modes (ids 20–21)
    AIR_LOUVER_AUTO = 20
    AIR_FLOW_AUTO = 21

    # Water / heating (ids 22–23)
    WATER_TEMPERATURE = 22
    WATER_FLOW_RATE = 23

    # Generic power (id 24)
    POWER_LEVEL = 24

    # Video (ids 25–26)
    VIDEO_STATION = 25
    VIDEO_INPUT_SOURCE = 26

    # Fan-coil unit (FCU) proprietary range (ids 192–239 reserved)
    FCU_OPERATION_MODE = 192


# ---------------------------------------------------------------------------
#  Output function / mode  (vDC API properties §4.8)
# ---------------------------------------------------------------------------


@unique
class OutputFunction(IntEnum):
    """Describes the functional type of a device's output.

    Sent as the ``function`` field in outputDescription.

    Note: the dSS firmware does **not** read or process the ``function``
    field from the vDC API output description (confirmed: vdc-connection.cpp
    reads only ``activeCoolingMode`` and ``heatingSystemType`` from
    outputSettings; ``function`` is purely informational for API consumers).
    """

    ON_OFF = 0
    DIMMER = 1
    POSITIONAL = 2
    DIMMER_COLOR_TEMP = 3
    FULL_COLOR_DIMMER = 4
    BIPOLAR = 5
    INTERNALLY_CONTROLLED = 6
    CUSTOM = 0x7F  # ActionOutputBehaviour — no standard channels


@unique
class OutputMode(IntEnum):
    """Output mode declared in ``outputSettings/mode`` of the vDC API.

    These four values are defined by the **vDC API protocol specification**.
    The vdSM uses this value to set the dSM device's ``OutputMode`` register,
    which determines how the Smart Home API reports the output (e.g.
    ``gradual`` vs. ``positional``).

    Do **not** confuse with :class:`OutputHardwareMode`, which contains the
    physical hardware dimmer-circuit types from the DS485 bus spec
    (``KM_Switch=16``, ``RMSDimmer=17``, …).  Those values have no meaning
    for VDC devices.

    Correct mapping to :class:`OutputFunction`:

    ============================  ===========
    ``OutputFunction``            ``OutputMode``
    ============================  ===========
    ``ON_OFF``                    ``BINARY``
    ``DIMMER``                    ``GRADUAL``
    ``POSITIONAL``                ``GRADUAL``
    ``DIMMER_COLOR_TEMP``         ``GRADUAL``
    ``FULL_COLOR_DIMMER``         ``GRADUAL``
    ``BIPOLAR``                   ``GRADUAL``
    ``INTERNALLY_CONTROLLED``     ``DISABLED``
    ``CUSTOM``                    ``DISABLED``
    ============================  ===========

    Note: ``POSITIONAL`` outputs use ``GRADUAL`` (2) — the vdSM maps this to
    the gradual dSM OutputMode range (17–24).  There is no VDC API mode value
    that maps to dSM mode 33 (positional shade motor); the positional nature
    of the device is conveyed via ``outputDescription.function=POSITIONAL``
    and the shade channel types in the OPC table.

    :class:`~pydsvdcapi.output.Output` auto-derives the correct value from
    the ``function`` argument when ``mode`` is not passed explicitly.
    """

    DISABLED = 0
    """Output is disabled — no UI controls are shown for this output."""

    BINARY = 1
    """Binary on/off output — configurator shows a toggle only (no slider)."""

    GRADUAL = 2
    """Continuous-range output — configurator shows the full slider in
    "Edit Device Values".  Used for all dimmer, positional, and bipolar outputs."""

    DEFAULT = 127
    """Unspecified sentinel — the vdSM maps this to dSM OutputMode 254 (unknown),
    which the Smart Home API omits entirely.  Do not use; let
    :class:`~pydsvdcapi.output.Output` auto-derive the correct mode from the
    output function instead."""


# ---------------------------------------------------------------------------
#  Output usage  (vDC API properties §4.8.1)
# ---------------------------------------------------------------------------


@unique
class OutputUsage(IntEnum):
    """Describes the usage context of an output."""

    UNDEFINED = 0
    ROOM = 1
    OUTDOORS = 2
    USER = 3


# ---------------------------------------------------------------------------
#  Sensor types  (ds-basics Table 23 / vDC API properties §4.4.1)
# ---------------------------------------------------------------------------


@unique
class SensorType(IntEnum):
    """Physical sensor type identifiers (vDC API numbering)."""

    NONE = 0
    TEMPERATURE = 1
    HUMIDITY = 2
    ILLUMINATION = 3
    SUPPLY_VOLTAGE = 4
    CO_CONCENTRATION = 5
    RADON_ACTIVITY = 6
    GAS_TYPE = 7
    PARTICLES_PM10 = 8
    PARTICLES_PM2_5 = 9
    PARTICLES_PM1 = 10
    ROOM_OPERATING_PANEL = 11
    FAN_SPEED = 12
    WIND_SPEED = 13
    ACTIVE_POWER = 14
    ELECTRIC_CURRENT = 15
    ENERGY_METER = 16
    APPARENT_POWER = 17
    AIR_PRESSURE = 18
    WIND_DIRECTION = 19
    SOUND_PRESSURE_LEVEL = 20
    PRECIPITATION = 21
    CO2_CONCENTRATION = 22
    WIND_GUST_SPEED = 23
    WIND_GUST_DIRECTION = 24
    GENERATED_ACTIVE_POWER = 25
    GENERATED_ENERGY = 26
    WATER_QUANTITY = 27
    WATER_FLOW_RATE = 28
    LENGTH = 29
    MASS = 30
    DURATION = 31
    PERCENT = 32
    PERCENT_SPEED = 33
    FREQUENCY = 34


@unique
class SensorUsage(IntEnum):
    """Usage context of a sensor."""

    UNDEFINED = 0
    ROOM = 1
    OUTDOOR = 2
    USER_INTERACTION = 3
    DEVICE_LEVEL = 4
    DEVICE_LAST_RUN = 5
    DEVICE_AVERAGE = 6


# ---------------------------------------------------------------------------
#  Sensor type/usage validation  (ds-basics Table 23)
# ---------------------------------------------------------------------------

_DEVICE: frozenset[SensorUsage] = frozenset(
    {
        SensorUsage.DEVICE_LEVEL,
        SensorUsage.DEVICE_LAST_RUN,
        SensorUsage.DEVICE_AVERAGE,
    }
)
_ROOM_OUTDOOR_DEVICE: frozenset[SensorUsage] = frozenset(
    {
        SensorUsage.ROOM,
        SensorUsage.OUTDOOR,
        SensorUsage.DEVICE_LEVEL,
        SensorUsage.DEVICE_LAST_RUN,
        SensorUsage.DEVICE_AVERAGE,
    }
)

SENSOR_TYPE_VALID_USAGES: dict[SensorType, frozenset[SensorUsage]] = {
    # Room + outdoor + device-level (ds-basics Table 23: rows for type 1/2/3)
    SensorType.TEMPERATURE: _ROOM_OUTDOOR_DEVICE,
    SensorType.HUMIDITY: _ROOM_OUTDOOR_DEVICE,
    SensorType.ILLUMINATION: _ROOM_OUTDOOR_DEVICE,
    # Room only
    SensorType.CO_CONCENTRATION: frozenset({SensorUsage.ROOM}),
    SensorType.CO2_CONCENTRATION: frozenset({SensorUsage.ROOM}),
    # Outdoor only
    SensorType.AIR_PRESSURE: frozenset({SensorUsage.OUTDOOR}),
    SensorType.WIND_SPEED: frozenset({SensorUsage.OUTDOOR}),
    SensorType.WIND_DIRECTION: frozenset({SensorUsage.OUTDOOR}),
    SensorType.WIND_GUST_SPEED: frozenset({SensorUsage.OUTDOOR}),
    SensorType.WIND_GUST_DIRECTION: frozenset({SensorUsage.OUTDOOR}),
    SensorType.PRECIPITATION: frozenset({SensorUsage.OUTDOOR}),
    # Device-level only
    SensorType.ACTIVE_POWER: _DEVICE,
    SensorType.ELECTRIC_CURRENT: _DEVICE,
    SensorType.ENERGY_METER: _DEVICE,
    SensorType.APPARENT_POWER: _DEVICE,
    SensorType.SOUND_PRESSURE_LEVEL: _DEVICE,
    SensorType.GENERATED_ACTIVE_POWER: _DEVICE,
    SensorType.GENERATED_ENERGY: _DEVICE,
    SensorType.WATER_QUANTITY: _DEVICE,
    SensorType.WATER_FLOW_RATE: _DEVICE,
    SensorType.LENGTH: _DEVICE,
    SensorType.MASS: _DEVICE,
    SensorType.DURATION: _DEVICE,
}


def validate_sensor_type_usage(
    sensor_type: "SensorType",
    sensor_usage: "SensorUsage",
) -> None:
    """Raise ValueError if (sensor_type, sensor_usage) violates ds-basics Table 23.

    Both arguments are mandatory — SensorType.NONE and SensorUsage.UNDEFINED
    are rejected.  Sensor types not listed in SENSOR_TYPE_VALID_USAGES are
    accepted with any explicit (non-UNDEFINED) usage.
    """
    if sensor_type is SensorType.NONE:
        raise ValueError(
            "SensorType.NONE is not a valid sensor type for a deployed sensor."
        )
    if sensor_usage is SensorUsage.UNDEFINED:
        raise ValueError(
            "SensorUsage.UNDEFINED is not a valid usage; specify ROOM, OUTDOOR, "
            "DEVICE_LEVEL, DEVICE_LAST_RUN, or DEVICE_AVERAGE."
        )
    valid = SENSOR_TYPE_VALID_USAGES.get(sensor_type)
    if valid is not None and sensor_usage not in valid:
        valid_names = [u.name for u in sorted(valid, key=int)]
        raise ValueError(
            f"SensorUsage.{sensor_usage.name} is not valid for "
            f"SensorType.{sensor_type.name} (ds-basics Table 23). "
            f"Valid usages: {valid_names}"
        )


# ---------------------------------------------------------------------------
#  Binary input types  (ds-basics Table 20 / vDC API properties §4.3.2)
# ---------------------------------------------------------------------------


@unique
class BinaryInputType(IntEnum):
    """Binary input sensor function / type identifiers.

    Values correspond to the ``sensorFunction`` setting in
    binaryInputDescriptions, and are firmware-verified against
    BinaryInputType enum in modelconst.h (values 0–23 match exactly).

    Important: only ``BinaryInputId=15`` (APP_MODE, i.e. ``GENERIC=0``) is
    interpreted and acted upon by the dSS firmware itself.  All other binary
    input IDs are forwarded to and processed by the dSM hardware bus module.
    (Firmware comment: "APP_MODE = 15, dSS will interpret and react (not the
    dSM). other values are not interpreted by dss" — businterface.cpp.)
    """

    GENERIC = 0
    PRESENCE = 1
    BRIGHTNESS = 2
    PRESENCE_IN_DARKNESS = 3
    TWILIGHT = 4
    MOTION = 5
    MOTION_IN_DARKNESS = 6
    SMOKE = 7
    WIND = 8
    RAIN = 9
    SUN_RADIATION = 10
    THERMOSTAT = 11
    BATTERY_LOW = 12
    WINDOW_OPEN = 13
    DOOR_OPEN = 14
    WINDOW_TILTED = 15
    GARAGE_DOOR_OPEN = 16
    SUN_PROTECTION = 17
    FROST = 18
    HEATING_SYSTEM_ENABLED = 19
    HEATING_CHANGE_OVER = 20
    INITIALIZATION = 21
    MALFUNCTION = 22
    SERVICE = 23


@unique
class BinaryInputUsage(IntEnum):
    """Usage context of a binary input."""

    UNDEFINED = 0
    ROOM_CLIMATE = 1
    OUTDOOR_CLIMATE = 2
    CLIMATE_SETTING = 3


# ---------------------------------------------------------------------------
#  Button input enums  (ds-basics §10 / vDC API properties §4.2)
# ---------------------------------------------------------------------------


@unique
class ButtonClickType(IntEnum):
    """Click event types generated by pushbutton inputs."""

    TIP_1X = 0
    TIP_2X = 1
    TIP_3X = 2
    TIP_4X = 3
    HOLD_START = 4
    HOLD_REPEAT = 5
    HOLD_END = 6
    CLICK_1X = 7
    CLICK_2X = 8
    CLICK_3X = 9
    SHORT_LONG = 10
    LOCAL_OFF = 11
    LOCAL_ON = 12
    SHORT_SHORT_LONG = 13
    LOCAL_STOP = 14
    LOCAL_DIM = 15
    IDLE = 255


@unique
class ButtonType(IntEnum):
    """Physical button type identifiers."""

    UNDEFINED = 0
    SINGLE_PUSHBUTTON = 1
    TWO_WAY_PUSHBUTTON = 2
    FOUR_WAY_NAVIGATION = 3
    FOUR_WAY_WITH_CENTER = 4
    EIGHT_WAY_WITH_CENTER = 5
    ON_OFF_SWITCH = 6


@unique
class ButtonElementID(IntEnum):
    """Element identifier within a multi-contact button."""

    CENTER = 0
    DOWN = 1
    UP = 2
    LEFT = 3
    RIGHT = 4
    UPPER_LEFT = 5
    LOWER_LEFT = 6
    UPPER_RIGHT = 7
    LOWER_RIGHT = 8


@unique
class ButtonFunction(IntEnum):
    """Logical function / operating mode of a button (LTNUM lower 4 bits)."""

    DEVICE = 0
    AREA_1 = 1
    AREA_2 = 2
    AREA_3 = 3
    AREA_4 = 4
    ROOM = 5
    EXTENDED_1 = 6
    EXTENDED_2 = 7
    EXTENDED_3 = 8
    EXTENDED_4 = 9
    EXTENDED_AREA_1 = 10
    EXTENDED_AREA_2 = 11
    EXTENDED_AREA_3 = 12
    EXTENDED_AREA_4 = 13
    APARTMENT = 14
    APP = 15


@unique
class ButtonFunctionJoker(IntEnum):
    """Button function lower 4 bits when group=8 (Joker/Black) — ds-basics Table 55."""

    ALARM = 1  # alarm call
    PANIC = 2  # panic call
    PRESENCE = 3  # leave / come home (presence toggle)
    DOOR_BELL = 5  # door bell call
    APP = 15  # freely assignable app button


def button_function_for_group(
    group: int, value: int
) -> ButtonFunction | ButtonFunctionJoker | int:
    """Return the correct ButtonFunction enum for *group* and raw *value*.

    Group 8 (Joker/Black) uses Table 55; all other groups use Table 54.
    Reserved values that don't appear in the table are returned as a plain int.
    """
    if group == 8:
        try:
            return ButtonFunctionJoker(value)
        except ValueError:
            return value
    try:
        return ButtonFunction(value)
    except ValueError:
        return value


@unique
class ButtonMode(IntEnum):
    """Button input mode (firmware: ButtonInputMode enum, modelconst.h).

    These values are sent as the ``mode`` setting of buttonInputDescriptions
    and are processed by the dSS firmware via
    static_cast<ButtonInputMode>(modeValue).
    """

    STANDARD = 0  # 1-way push button
    TURBO = 1  # 1-way turbo
    SWITCHED = 2  # switched / toggle

    # 2-way paired inputs (down half + up half share one physical button)
    TWO_WAY_DOWN_PAIRED_1 = 5
    TWO_WAY_DOWN_PAIRED_2 = 6
    TWO_WAY_DOWN_PAIRED_3 = 7
    TWO_WAY_DOWN_PAIRED_4 = 8
    TWO_WAY_UP_PAIRED_1 = 9
    TWO_WAY_UP_PAIRED_2 = 10
    TWO_WAY_UP_PAIRED_3 = 11
    TWO_WAY_UP_PAIRED_4 = 12

    TWO_WAY = 13  # 2-way
    ONE_WAY = 14  # 1-way (explicit)

    # AKM (Aktor-Kontakt-Modul) modes
    AKM_STANDARD = 16
    AKM_INVERTED = 17
    AKM_ON_RISING_EDGE = 18
    AKM_ON_FALLING_EDGE = 19
    AKM_OFF_RISING_EDGE = 20
    AKM_OFF_FALLING_EDGE = 21
    AKM_RISING_EDGE = 22
    AKM_FALLING_EDGE = 23

    HEATING_PUSHBUTTON = 65  # 1-way heating push button
    DEACTIVATED = 0xFF  # deactivated


@unique
class SensorGroup(IntEnum):
    """Target group for a sensor input (``sensorSettings/group``).

    Determines which colour group this sensor reading belongs to.
    Note: Joker/Black uses 0 in this field (not 8).
    """

    JOKER = 0  # schwarz/Joker — generic / no group
    LIGHT = 1  # gelb/Licht — lighting
    SHADOW = 2  # grau/Schatten — shading / blinds
    CLIMATE = 3  # blau/Klima — heating / climate
    AUDIO = 4  # cyan/Audio — audio
    VIDEO = 5  # magenta/Video — video
    SECURITY = 6  # rot/Sicherheit — security
    ACCESS = 7  # grün/Zugang — access control


@unique
class BinaryInputGroup(IntEnum):
    """Target group for a binary input (``binaryInputSettings/group``).

    Determines which colour group this binary input belongs to.
    Note: Joker/Black uses 8 in this field.
    """

    LIGHT = 1  # gelb/Licht — lighting
    SHADOW = 2  # grau/Schatten — shading / blinds
    HEATING = 3  # blau/Klima — heating / climate
    AUDIO = 4  # cyan/Audio — audio
    VIDEO = 5  # magenta/Video — video
    SECURITY = 6  # rot/Sicherheit — security (deprecated - displayed as "reserved")
    ACCESS = 7  # grün/Zugang — access control (deprecated - displayed as "reserved")
    JOKER = 8  # schwarz/Joker — generic / configurable
    VENTILATION = 10  # blau/Klima - room ventilatio / climate (added manually to match UI component)
    RECIRCULATION = (
        12  # Recirculation / fan-coil units (added manually to match UI component)
    )


@unique
class ButtonGroup(IntEnum):
    """Target group for a button input (``buttonInputSettings/group``).

    Determines which colour group this button controls.
    """

    LIGHT = 1  # gelb/hell — lighting
    SHADOW = 2  # grau/Schatten — shading / blinds
    HEATING = 3  # blau/Heizung — heating / climate
    AUDIO = 4  # cyan/Audio — audio
    VIDEO = 5  # magenta/Video — video
    SECURITY = 6  # rot/Sicherheit — security (deprecated - displayed as "reserved")
    ACCESS = 7  # grün/Zugang — access control (deprecated - displayed as "reserved")
    JOKER = 8  # schwarz/variabel — joker / configurable
    COOLING = 9  # blau/Kühlung — cooling (not visible in UI Component)
    VENTILATION = 10  # blau/Lüftung — ventilation
    WINDOW = 11  # blau/Fenster — window openers
    RECIRCULATION = (
        12  # Recirculation / fan-coil units (added manually to match UI component)
    )
    TEMPERATURE = 48  # Raumtemperaturregelung — room temperature control


@unique
class ActionMode(IntEnum):
    """Action mode for button direct scene calls (§4.2.3).

    Determines how a directly-called scene is applied when a button
    emits an ``actionId`` instead of a ``clickType``.
    """

    NORMAL = 0
    FORCE = 1
    UNDO = 2


# ---------------------------------------------------------------------------
#  Button input error  (vDC API properties §4.2.3)
# ---------------------------------------------------------------------------


@unique
class InputError(IntEnum):
    """Error status of an input (button, binary, sensor)."""

    OK = 0
    OPEN_CIRCUIT = 1
    SHORT_CIRCUIT = 2
    BUS_CONNECTION = 4
    LOW_BATTERY = 5
    OTHER_ERROR = 6


# ---------------------------------------------------------------------------
#  Output error  (vDC API properties §4.8.3)
# ---------------------------------------------------------------------------


@unique
class OutputError(IntEnum):
    """Error status of an output."""

    OK = 0
    LAMP_BROKEN = 1  # open circuit
    SHORT_CIRCUIT = 2
    OVERLOAD = 3
    BUS_CONNECTION = 4
    LOW_BATTERY = 5
    OTHER_ERROR = 6


# ---------------------------------------------------------------------------
#  Scene effect  (vDC API properties §4.10)
# ---------------------------------------------------------------------------


@unique
class SceneEffect(IntEnum):
    """Transition effect when a scene is invoked."""

    NONE = 0  # immediate
    SMOOTH = 1  # normal transition
    SLOW = 2  # slow transition
    VERY_SLOW = 3  # very slow transition
    ALERT = 4  # blink / alerting


# ---------------------------------------------------------------------------
#  Heating system  (vDC API properties §4.8.2)
# ---------------------------------------------------------------------------


@unique
class HeatingSystemCapability(IntEnum):
    """How the ``heatingLevel`` control value is applied."""

    HEATING_ONLY = 1
    COOLING_ONLY = 2
    HEATING_AND_COOLING = 3


@unique
class HeatingSystemType(IntEnum):
    """Kind of heating/cooling actuator attached."""

    UNDEFINED = 0
    FLOOR_HEATING = 1
    RADIATOR = 2
    WALL_HEATING = 3
    CONVECTOR_PASSIVE = 4
    CONVECTOR_ACTIVE = 5
    FLOOR_HEATING_LOW_ENERGY = 6


# ---------------------------------------------------------------------------
#  Power state channel values  (vDC API properties §4.9.4)
# ---------------------------------------------------------------------------


@unique
class PowerState(IntEnum):
    """Discrete values for the ``powerState`` output channel."""

    OFF = 0
    ON = 1
    FORCED_OFF = 2
    STANDBY = 3


# ---------------------------------------------------------------------------
#  Air flow direction channel values  (vDC API properties §4.9.4)
# ---------------------------------------------------------------------------


@unique
class AirFlowDirection(IntEnum):
    """Discrete values for the ``airFlowDirection`` output channel."""

    BOTH_UNDEFINED = 0
    SUPPLY_IN = 1
    EXHAUST_OUT = 2


# ---------------------------------------------------------------------------
#  Output hardware mode  (ds-basics Table 52)
# ---------------------------------------------------------------------------


@unique
class OutputHardwareMode(IntEnum):
    """Physical hardware dimmer-circuit type for DS485 bus devices (reference only).

    These values describe **how the hardware circuit physically works** —
    RMS-based dimmer, phase-cut, relay, positioning motor, etc.  They are
    read by the dSS from the DS485 bus registers of physical hardware devices.

    **Not used for VDC devices.**  The firmware never reads or applies these
    values from the vDC API.  VDC output capability is declared through
    :class:`OutputMode` (the simple 0/1/2 vDC API values) instead.

    Provided for reference when reading dSS device diagnostics or comparing
    against physical hardware specifications.
    """

    DISABLED = 0
    SWITCHED = 16
    RMS_DIMMER = 17
    RMS_DIMMER_CURVE = 18
    PHASE_CONTROL_DIMMER = 19
    PHASE_CONTROL_DIMMER_CURVE = 20
    REVERSE_PHASE_DIMMER = 21
    REVERSE_PHASE_DIMMER_CURVE = 22
    PWM = 23
    PWM_CURVE = 24
    POSITIONING_CONTROL = 33
    RELAY_SWITCHED = 39
    RELAY_WIPED = 40
    RELAY_SAVING = 41
    POSITIONING_UNCALIBRATED = 42


# ---------------------------------------------------------------------------
#  Temperature control scenes  (ds-basics Table 47)
# ---------------------------------------------------------------------------


@unique
class TemperatureControlScene(IntEnum):
    """Scene commands specific to the temperature control application."""

    HEATING_OFF = 0
    HEATING_COMFORT = 1
    HEATING_ECONOMY = 2
    HEATING_NOT_USED = 3
    HEATING_NIGHT = 4
    HEATING_HOLIDAY = 5
    PASSIVE_COOLING_ACTIVE = 6
    PASSIVE_COOLING_INACTIVE = 7
    COOLING_OFF = 9
    COOLING_COMFORT = 10
    COOLING_ECONOMY = 11
    COOLING_NOT_USED = 12
    COOLING_NIGHT = 13
    COOLING_HOLIDAY = 14


# ---------------------------------------------------------------------------
#  Temperature device control scenes  (ds-basics Table 48)
# ---------------------------------------------------------------------------


@unique
class TemperatureDeviceScene(IntEnum):
    """Device-level control scenes for climate devices."""

    POWER_ON = 29
    POWER_OFF = 30
    VALVE_PROTECTION = 31
    FORCE_VALVE_OPEN = 32
    FORCE_VALVE_CLOSE = 33
    FORCE_FAN_MODE = 40
    FORCE_DRY_MODE = 41
    AUTOMATIC_MODE = 42


# ---------------------------------------------------------------------------
#  Ventilation control scenes  (ds-basics Table 49)
# ---------------------------------------------------------------------------


@unique
class VentilationScene(IntEnum):
    """Scene commands specific to ventilation / recirculation."""

    OFF = 0
    STAGE_1 = 5
    STAGE_2 = 17
    STAGE_3 = 18
    STAGE_4 = 19
    BOOST = 6
    NOISE_REDUCTION = 7
    AUTOMATIC_AIR_FLOW = 8
    AUTO_LOUVER_POSITION = 9


# ---------------------------------------------------------------------------
#  Device lifecycle state
# ---------------------------------------------------------------------------


@unique
class DeviceLifecycleState(str, Enum):
    """Lifecycle state of a virtual device (vdSD).

    The library maps these states to the vdSM wire protocol automatically:

    * ``ACTIVE`` — device is operational; responds to ping with pong and
      reports ``active=true`` in common properties.
    * ``INACTIVE``, ``MAINTENANCE``, ``ERROR`` — device is temporarily
      unavailable; ping responses are suppressed and ``active=false`` is
      pushed to dSS on transition.
    * ``REMOVED`` — device has been decommissioned; ``vanish`` is sent to
      dSS and ping responses are suppressed.  Setting ``REMOVED`` is
      one-way: there is no meaningful return from this state.
    """

    def __str__(self) -> str:
        return self.value

    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"
    ERROR = "error"
    REMOVED = "removed"
