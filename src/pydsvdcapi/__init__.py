# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2024–2026 Arne Speck
"""pydsvdcapi - Python library for the DSvDC API."""

__version__ = "0.9.0"

__all__ = [
    # Version
    "__version__",
    # Enums
    "ActionMode",
    "AirFlowDirection",
    "ApartmentScene",
    "ApartmentTemperatureMode",
    "ApartmentVentilationLevel",
    "AudioDeviceScene",
    "AudioScene",
    "AwningScene",
    "BinaryInputGroup",
    "BinaryInputType",
    "BinaryInputUsage",
    "ButtonClickType",
    "ButtonElementID",
    "ButtonFunction",
    "ButtonFunctionJoker",
    "ButtonGroup",
    "ButtonMode",
    "ButtonType",
    "button_function_for_group",
    "ClimateDeviceScene",
    "ColorClass",
    "ColorGroup",
    "DeviceLifecycleState",
    "DeviceScene",
    "EntityType",
    "ErrorType",
    "HeatingSystemCapability",
    "HeatingSystemType",
    "InputError",
    "LightScene",
    "MessageType",
    "OutputChannelType",
    "OutputError",
    "OutputFunction",
    "OutputHardwareMode",
    "OutputMode",
    "OutputUsage",
    "PowerState",
    "ResultCode",
    "SceneEffect",
    "SceneNumber",
    "SceneScope",
    "SensorGroup",
    "SensorType",
    "SensorUsage",
    "ShadeScene",
    "TemperatureControlScene",
    "TemperatureDeviceScene",
    "VentilationScene",
    "ZoneScene",
    "ZoneTemperatureMode",
    # DsUid
    "DSUID_BYTES",
    "DsUid",
    "DsUidNamespace",
    "DsUidType",
    # Connection
    "MAX_MESSAGE_LENGTH",
    "VdcConnection",
    # Persistence
    "PropertyStore",
    # Session
    "SUPPORTED_API_VERSION",
    "MAX_SUPPORTED_API_VERSION",
    "HelloCallback",
    "MessageCallback",
    "SessionState",
    "VdcSession",
    # VdcHost
    "AUTO_SAVE_DELAY",
    "AuthenticateCallback",
    "DEFAULT_VDC_PORT",
    "ENTITY_TYPE_VDC_HOST",
    "FirmwareUpgradeCallback",
    "IdentifyCallback",
    "PairCallback",
    "RemoveCallback",
    "SetConfigurationCallback",
    "VdcHost",
    # Vdc
    "ENTITY_TYPE_VDC",
    "Vdc",
    "VdcCapabilities",
    # Vdsd / Device
    "ControlValueCallback",
    "ENTITY_TYPE_VDSD",
    "Device",
    "DeviceIdentifyCallback",
    "InvokeActionCallback",
    "Vdsd",
    # Actions
    "ActionParameter",
    "CustomAction",
    "DeviceActionDescription",
    "DynamicAction",
    "StandardAction",
    # Inputs
    "BinaryInput",
    "BinaryInputSettingsChangedCallback",
    "BUTTON_TYPE_ELEMENTS",
    "ButtonInput",
    "ButtonInputSettingsChangedCallback",
    "ClickDetector",
    "SensorInput",
    "SensorInputSettingsChangedCallback",
    "create_button_group",
    "get_required_elements",
    # Events / States / Properties
    "DeviceEvent",
    "DeviceState",
    "PROPERTY_TYPE_ENUMERATION",
    "PROPERTY_TYPE_NUMERIC",
    "PROPERTY_TYPE_STRING",
    "VALID_PROPERTY_TYPES",
    "DeviceProperty",
    # Output
    "DimChannelCallback",
    "OutputSettingsChangedCallback",
    "FUNCTION_CHANNELS",
    "Output",
    "CHANNEL_SPECS",
    "ChannelSpec",
    "OutputChannel",
    "get_channel_spec",
    # Property handling
    "NO_VALUE",
    "build_get_property_response",
    "dict_to_elements",
    "elements_to_dict",
    "expand_setproperty_wildcards",
    "match_query",
    # Device template
    "AnnouncementNotReadyError",
    "DeviceTemplate",
    "TemplateNotConfiguredError",
    # Converters (add-on)
    "apply_converter",
    "compile_converter",
]

from pydsvdcapi.actions import (  # noqa: F401
    ActionParameter,
    CustomAction,
    DeviceActionDescription,
    DynamicAction,
    StandardAction,
)
from pydsvdcapi.addons.converter import (  # noqa: F401
    apply_converter,
    compile_converter,
)
from pydsvdcapi.binary_input import (  # noqa: F401
    BinaryInput,
    BinaryInputSettingsChangedCallback,
)
from pydsvdcapi.button_input import (  # noqa: F401
    BUTTON_TYPE_ELEMENTS,
    ButtonInput,
    ButtonInputSettingsChangedCallback,
    ClickDetector,
    create_button_group,
    get_required_elements,
)
from pydsvdcapi.connection import (  # noqa: F401
    MAX_MESSAGE_LENGTH,
    VdcConnection,
)
from pydsvdcapi.device_event import DeviceEvent  # noqa: F401
from pydsvdcapi.device_property import (  # noqa: F401
    PROPERTY_TYPE_ENUMERATION,
    PROPERTY_TYPE_NUMERIC,
    PROPERTY_TYPE_STRING,
    VALID_PROPERTY_TYPES,
    DeviceProperty,
)
from pydsvdcapi.device_state import DeviceState  # noqa: F401
from pydsvdcapi.device_template import (  # noqa: F401
    AnnouncementNotReadyError,
    DeviceTemplate,
    TemplateNotConfiguredError,
)
from pydsvdcapi.dsuid import (  # noqa: F401
    DSUID_BYTES,
    DsUid,
    DsUidNamespace,
    DsUidType,
)
from pydsvdcapi.enums import (  # noqa: F401 – re-export for convenience
    ActionMode,
    AirFlowDirection,
    ApartmentScene,
    ApartmentTemperatureMode,
    ApartmentVentilationLevel,
    AudioDeviceScene,
    AudioScene,
    AwningScene,
    BinaryInputGroup,
    BinaryInputType,
    BinaryInputUsage,
    ButtonClickType,
    ButtonElementID,
    ButtonFunction,
    ButtonFunctionJoker,
    ButtonGroup,
    ButtonMode,
    ButtonType,
    ClimateDeviceScene,
    ColorClass,
    ColorGroup,
    DeviceLifecycleState,
    DeviceScene,
    EntityType,
    ErrorType,
    HeatingSystemCapability,
    HeatingSystemType,
    InputError,
    LightScene,
    MessageType,
    OutputChannelType,
    OutputError,
    OutputFunction,
    OutputHardwareMode,
    OutputMode,
    OutputUsage,
    PowerState,
    ResultCode,
    SceneEffect,
    SceneNumber,
    SceneScope,
    SensorGroup,
    SensorType,
    SensorUsage,
    ShadeScene,
    TemperatureControlScene,
    TemperatureDeviceScene,
    VentilationScene,
    ZoneScene,
    ZoneTemperatureMode,
    button_function_for_group,
)
from pydsvdcapi.output import (  # noqa: F401
    FUNCTION_CHANNELS,
    DimChannelCallback,
    Output,
    OutputSettingsChangedCallback,
)
from pydsvdcapi.output_channel import (  # noqa: F401
    CHANNEL_SPECS,
    ChannelSpec,
    OutputChannel,
    get_channel_spec,
)
from pydsvdcapi.persistence import PropertyStore  # noqa: F401
from pydsvdcapi.property_handling import (  # noqa: F401
    NO_VALUE,
    build_get_property_response,
    dict_to_elements,
    elements_to_dict,
    expand_setproperty_wildcards,
    match_query,
)
from pydsvdcapi.sensor_input import (  # noqa: F401
    SensorInput,
    SensorInputSettingsChangedCallback,
)
from pydsvdcapi.session import (  # noqa: F401
    MAX_SUPPORTED_API_VERSION,
    SUPPORTED_API_VERSION,
    HelloCallback,
    MessageCallback,
    SessionState,
    VdcSession,
)
from pydsvdcapi.vdc import (  # noqa: F401
    ENTITY_TYPE_VDC,
    Vdc,
    VdcCapabilities,
)
from pydsvdcapi.vdc_host import (  # noqa: F401
    AUTO_SAVE_DELAY,
    DEFAULT_VDC_PORT,
    ENTITY_TYPE_VDC_HOST,
    AuthenticateCallback,
    FirmwareUpgradeCallback,
    IdentifyCallback,
    PairCallback,
    RemoveCallback,
    SetConfigurationCallback,
    VdcHost,
)
from pydsvdcapi.vdsd import (  # noqa: F401,F811
    ENTITY_TYPE_VDSD,
    ControlValueCallback,
    Device,
    InvokeActionCallback,
    Vdsd,
)
from pydsvdcapi.vdsd import (  # noqa: F401
    IdentifyCallback as DeviceIdentifyCallback,
)
