from collections.abc import Iterable as _Iterable
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers

DESCRIPTOR: _descriptor.FileDescriptor

class vdsm_RequestHello(_message.Message):
    __slots__ = ("dSUID", "api_version")
    DSUID_FIELD_NUMBER: _ClassVar[int]
    API_VERSION_FIELD_NUMBER: _ClassVar[int]
    dSUID: str
    api_version: int
    def __init__(
        self, dSUID: str | None = ..., api_version: int | None = ...
    ) -> None: ...

class vdc_ResponseHello(_message.Message):
    __slots__ = ("dSUID",)
    DSUID_FIELD_NUMBER: _ClassVar[int]
    dSUID: str
    def __init__(self, dSUID: str | None = ...) -> None: ...

class vdc_SendAnnounceDevice(_message.Message):
    __slots__ = ("dSUID", "vdc_dSUID")
    DSUID_FIELD_NUMBER: _ClassVar[int]
    VDC_DSUID_FIELD_NUMBER: _ClassVar[int]
    dSUID: str
    vdc_dSUID: str
    def __init__(
        self, dSUID: str | None = ..., vdc_dSUID: str | None = ...
    ) -> None: ...

class vdc_SendAnnounceVdc(_message.Message):
    __slots__ = ("dSUID",)
    DSUID_FIELD_NUMBER: _ClassVar[int]
    dSUID: str
    def __init__(self, dSUID: str | None = ...) -> None: ...

class vdc_SendVanish(_message.Message):
    __slots__ = ("dSUID",)
    DSUID_FIELD_NUMBER: _ClassVar[int]
    dSUID: str
    def __init__(self, dSUID: str | None = ...) -> None: ...

class vdc_SendIdentify(_message.Message):
    __slots__ = ("dSUID",)
    DSUID_FIELD_NUMBER: _ClassVar[int]
    dSUID: str
    def __init__(self, dSUID: str | None = ...) -> None: ...

class vdsm_SendBye(_message.Message):
    __slots__ = ("dSUID",)
    DSUID_FIELD_NUMBER: _ClassVar[int]
    dSUID: str
    def __init__(self, dSUID: str | None = ...) -> None: ...

class vdsm_SendRemove(_message.Message):
    __slots__ = ("dSUID",)
    DSUID_FIELD_NUMBER: _ClassVar[int]
    dSUID: str
    def __init__(self, dSUID: str | None = ...) -> None: ...

class PropertyValue(_message.Message):
    __slots__ = ("v_bool", "v_uint64", "v_int64", "v_double", "v_string", "v_bytes")
    V_BOOL_FIELD_NUMBER: _ClassVar[int]
    V_UINT64_FIELD_NUMBER: _ClassVar[int]
    V_INT64_FIELD_NUMBER: _ClassVar[int]
    V_DOUBLE_FIELD_NUMBER: _ClassVar[int]
    V_STRING_FIELD_NUMBER: _ClassVar[int]
    V_BYTES_FIELD_NUMBER: _ClassVar[int]
    v_bool: bool
    v_uint64: int
    v_int64: int
    v_double: float
    v_string: str
    v_bytes: bytes
    def __init__(
        self,
        v_bool: bool = ...,
        v_uint64: int | None = ...,
        v_int64: int | None = ...,
        v_double: float | None = ...,
        v_string: str | None = ...,
        v_bytes: bytes | None = ...,
    ) -> None: ...

class PropertyElement(_message.Message):
    __slots__ = ("name", "value", "elements")
    NAME_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    ELEMENTS_FIELD_NUMBER: _ClassVar[int]
    name: str
    value: PropertyValue
    elements: _containers.RepeatedCompositeFieldContainer[PropertyElement]
    def __init__(
        self,
        name: str | None = ...,
        value: PropertyValue | _Mapping | None = ...,
        elements: _Iterable[PropertyElement | _Mapping] | None = ...,
    ) -> None: ...

class vdsm_RequestGetProperty(_message.Message):
    __slots__ = ("dSUID", "query")
    DSUID_FIELD_NUMBER: _ClassVar[int]
    QUERY_FIELD_NUMBER: _ClassVar[int]
    dSUID: str
    query: _containers.RepeatedCompositeFieldContainer[PropertyElement]
    def __init__(
        self,
        dSUID: str | None = ...,
        query: _Iterable[PropertyElement | _Mapping] | None = ...,
    ) -> None: ...

class vdc_ResponseGetProperty(_message.Message):
    __slots__ = ("properties",)
    PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    properties: _containers.RepeatedCompositeFieldContainer[PropertyElement]
    def __init__(
        self, properties: _Iterable[PropertyElement | _Mapping] | None = ...
    ) -> None: ...

class vdsm_RequestSetProperty(_message.Message):
    __slots__ = ("dSUID", "properties")
    DSUID_FIELD_NUMBER: _ClassVar[int]
    PROPERTIES_FIELD_NUMBER: _ClassVar[int]
    dSUID: str
    properties: _containers.RepeatedCompositeFieldContainer[PropertyElement]
    def __init__(
        self,
        dSUID: str | None = ...,
        properties: _Iterable[PropertyElement | _Mapping] | None = ...,
    ) -> None: ...

class vdsm_RequestGenericRequest(_message.Message):
    __slots__ = ("dSUID", "methodname", "params")
    DSUID_FIELD_NUMBER: _ClassVar[int]
    METHODNAME_FIELD_NUMBER: _ClassVar[int]
    PARAMS_FIELD_NUMBER: _ClassVar[int]
    dSUID: str
    methodname: str
    params: _containers.RepeatedCompositeFieldContainer[PropertyElement]
    def __init__(
        self,
        dSUID: str | None = ...,
        methodname: str | None = ...,
        params: _Iterable[PropertyElement | _Mapping] | None = ...,
    ) -> None: ...

class vdsm_SendPing(_message.Message):
    __slots__ = ("dSUID",)
    DSUID_FIELD_NUMBER: _ClassVar[int]
    dSUID: str
    def __init__(self, dSUID: str | None = ...) -> None: ...

class vdc_SendPong(_message.Message):
    __slots__ = ("dSUID",)
    DSUID_FIELD_NUMBER: _ClassVar[int]
    dSUID: str
    def __init__(self, dSUID: str | None = ...) -> None: ...

class vdc_SendPushNotification(_message.Message):
    __slots__ = ("dSUID", "changedproperties", "deviceevents")
    DSUID_FIELD_NUMBER: _ClassVar[int]
    CHANGEDPROPERTIES_FIELD_NUMBER: _ClassVar[int]
    DEVICEEVENTS_FIELD_NUMBER: _ClassVar[int]
    dSUID: str
    changedproperties: _containers.RepeatedCompositeFieldContainer[PropertyElement]
    deviceevents: _containers.RepeatedCompositeFieldContainer[PropertyElement]
    def __init__(
        self,
        dSUID: str | None = ...,
        changedproperties: _Iterable[PropertyElement | _Mapping] | None = ...,
        deviceevents: _Iterable[PropertyElement | _Mapping] | None = ...,
    ) -> None: ...

class vdsm_NotificationCallScene(_message.Message):
    __slots__ = ("dSUID", "scene", "force", "group", "zone_id")
    DSUID_FIELD_NUMBER: _ClassVar[int]
    SCENE_FIELD_NUMBER: _ClassVar[int]
    FORCE_FIELD_NUMBER: _ClassVar[int]
    GROUP_FIELD_NUMBER: _ClassVar[int]
    ZONE_ID_FIELD_NUMBER: _ClassVar[int]
    dSUID: _containers.RepeatedScalarFieldContainer[str]
    scene: int
    force: bool
    group: int
    zone_id: int
    def __init__(
        self,
        dSUID: _Iterable[str] | None = ...,
        scene: int | None = ...,
        force: bool = ...,
        group: int | None = ...,
        zone_id: int | None = ...,
    ) -> None: ...

class vdsm_NotificationSaveScene(_message.Message):
    __slots__ = ("dSUID", "scene", "group", "zone_id")
    DSUID_FIELD_NUMBER: _ClassVar[int]
    SCENE_FIELD_NUMBER: _ClassVar[int]
    GROUP_FIELD_NUMBER: _ClassVar[int]
    ZONE_ID_FIELD_NUMBER: _ClassVar[int]
    dSUID: _containers.RepeatedScalarFieldContainer[str]
    scene: int
    group: int
    zone_id: int
    def __init__(
        self,
        dSUID: _Iterable[str] | None = ...,
        scene: int | None = ...,
        group: int | None = ...,
        zone_id: int | None = ...,
    ) -> None: ...

class vdsm_NotificationUndoScene(_message.Message):
    __slots__ = ("dSUID", "scene", "group", "zone_id")
    DSUID_FIELD_NUMBER: _ClassVar[int]
    SCENE_FIELD_NUMBER: _ClassVar[int]
    GROUP_FIELD_NUMBER: _ClassVar[int]
    ZONE_ID_FIELD_NUMBER: _ClassVar[int]
    dSUID: _containers.RepeatedScalarFieldContainer[str]
    scene: int
    group: int
    zone_id: int
    def __init__(
        self,
        dSUID: _Iterable[str] | None = ...,
        scene: int | None = ...,
        group: int | None = ...,
        zone_id: int | None = ...,
    ) -> None: ...

class vdsm_NotificationSetLocalPrio(_message.Message):
    __slots__ = ("dSUID", "scene", "group", "zone_id")
    DSUID_FIELD_NUMBER: _ClassVar[int]
    SCENE_FIELD_NUMBER: _ClassVar[int]
    GROUP_FIELD_NUMBER: _ClassVar[int]
    ZONE_ID_FIELD_NUMBER: _ClassVar[int]
    dSUID: _containers.RepeatedScalarFieldContainer[str]
    scene: int
    group: int
    zone_id: int
    def __init__(
        self,
        dSUID: _Iterable[str] | None = ...,
        scene: int | None = ...,
        group: int | None = ...,
        zone_id: int | None = ...,
    ) -> None: ...

class vdsm_NotificationCallMinScene(_message.Message):
    __slots__ = ("dSUID", "scene", "group", "zone_id")
    DSUID_FIELD_NUMBER: _ClassVar[int]
    SCENE_FIELD_NUMBER: _ClassVar[int]
    GROUP_FIELD_NUMBER: _ClassVar[int]
    ZONE_ID_FIELD_NUMBER: _ClassVar[int]
    dSUID: _containers.RepeatedScalarFieldContainer[str]
    scene: int
    group: int
    zone_id: int
    def __init__(
        self,
        dSUID: _Iterable[str] | None = ...,
        scene: int | None = ...,
        group: int | None = ...,
        zone_id: int | None = ...,
    ) -> None: ...

class vdsm_NotificationIdentify(_message.Message):
    __slots__ = ("dSUID", "group", "zone_id")
    DSUID_FIELD_NUMBER: _ClassVar[int]
    GROUP_FIELD_NUMBER: _ClassVar[int]
    ZONE_ID_FIELD_NUMBER: _ClassVar[int]
    dSUID: _containers.RepeatedScalarFieldContainer[str]
    group: int
    zone_id: int
    def __init__(
        self,
        dSUID: _Iterable[str] | None = ...,
        group: int | None = ...,
        zone_id: int | None = ...,
    ) -> None: ...

class vdsm_NotificationSetControlValue(_message.Message):
    __slots__ = ("dSUID", "name", "value", "group", "zone_id")
    DSUID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    GROUP_FIELD_NUMBER: _ClassVar[int]
    ZONE_ID_FIELD_NUMBER: _ClassVar[int]
    dSUID: _containers.RepeatedScalarFieldContainer[str]
    name: str
    value: float
    group: int
    zone_id: int
    def __init__(
        self,
        dSUID: _Iterable[str] | None = ...,
        name: str | None = ...,
        value: float | None = ...,
        group: int | None = ...,
        zone_id: int | None = ...,
    ) -> None: ...

class vdsm_NotificationDimChannel(_message.Message):
    __slots__ = ("dSUID", "channel", "mode", "area", "group", "zone_id", "channelId")
    DSUID_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    MODE_FIELD_NUMBER: _ClassVar[int]
    AREA_FIELD_NUMBER: _ClassVar[int]
    GROUP_FIELD_NUMBER: _ClassVar[int]
    ZONE_ID_FIELD_NUMBER: _ClassVar[int]
    CHANNELID_FIELD_NUMBER: _ClassVar[int]
    dSUID: _containers.RepeatedScalarFieldContainer[str]
    channel: int
    mode: int
    area: int
    group: int
    zone_id: int
    channelId: str
    def __init__(
        self,
        dSUID: _Iterable[str] | None = ...,
        channel: int | None = ...,
        mode: int | None = ...,
        area: int | None = ...,
        group: int | None = ...,
        zone_id: int | None = ...,
        channelId: str | None = ...,
    ) -> None: ...

class vdsm_NotificationSetOutputChannelValue(_message.Message):
    __slots__ = ("dSUID", "apply_now", "channel", "value", "channelId")
    DSUID_FIELD_NUMBER: _ClassVar[int]
    APPLY_NOW_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    VALUE_FIELD_NUMBER: _ClassVar[int]
    CHANNELID_FIELD_NUMBER: _ClassVar[int]
    dSUID: _containers.RepeatedScalarFieldContainer[str]
    apply_now: bool
    channel: int
    value: float
    channelId: str
    def __init__(
        self,
        dSUID: _Iterable[str] | None = ...,
        apply_now: bool = ...,
        channel: int | None = ...,
        value: float | None = ...,
        channelId: str | None = ...,
    ) -> None: ...
