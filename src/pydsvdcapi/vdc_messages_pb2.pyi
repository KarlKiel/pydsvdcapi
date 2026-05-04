from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar

import vdcapi_pb2 as _vdcapi_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper

DESCRIPTOR: _descriptor.FileDescriptor

class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    GENERIC_RESPONSE: _ClassVar[Type]
    VDSM_REQUEST_HELLO: _ClassVar[Type]
    VDC_RESPONSE_HELLO: _ClassVar[Type]
    VDSM_REQUEST_GET_PROPERTY: _ClassVar[Type]
    VDC_RESPONSE_GET_PROPERTY: _ClassVar[Type]
    VDSM_REQUEST_SET_PROPERTY: _ClassVar[Type]
    VDSM_REQUEST_GENERIC_REQUEST: _ClassVar[Type]
    VDSM_SEND_PING: _ClassVar[Type]
    VDC_SEND_PONG: _ClassVar[Type]
    VDC_SEND_ANNOUNCE_DEVICE: _ClassVar[Type]
    VDC_SEND_VANISH: _ClassVar[Type]
    VDC_SEND_PUSH_NOTIFICATION: _ClassVar[Type]
    VDSM_SEND_REMOVE: _ClassVar[Type]
    VDSM_SEND_BYE: _ClassVar[Type]
    VDC_SEND_ANNOUNCE_VDC: _ClassVar[Type]
    VDSM_NOTIFICATION_CALL_SCENE: _ClassVar[Type]
    VDSM_NOTIFICATION_SAVE_SCENE: _ClassVar[Type]
    VDSM_NOTIFICATION_UNDO_SCENE: _ClassVar[Type]
    VDSM_NOTIFICATION_SET_LOCAL_PRIO: _ClassVar[Type]
    VDSM_NOTIFICATION_CALL_MIN_SCENE: _ClassVar[Type]
    VDSM_NOTIFICATION_IDENTIFY: _ClassVar[Type]
    VDSM_NOTIFICATION_SET_CONTROL_VALUE: _ClassVar[Type]
    VDSM_NOTIFICATION_DIM_CHANNEL: _ClassVar[Type]
    VDSM_NOTIFICATION_SET_OUTPUT_CHANNEL_VALUE: _ClassVar[Type]
    VDC_SEND_IDENTIFY: _ClassVar[Type]

class ResultCode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ERR_OK: _ClassVar[ResultCode]
    ERR_MESSAGE_UNKNOWN: _ClassVar[ResultCode]
    ERR_INCOMPATIBLE_API: _ClassVar[ResultCode]
    ERR_SERVICE_NOT_AVAILABLE: _ClassVar[ResultCode]
    ERR_INSUFFICIENT_STORAGE: _ClassVar[ResultCode]
    ERR_FORBIDDEN: _ClassVar[ResultCode]
    ERR_NOT_IMPLEMENTED: _ClassVar[ResultCode]
    ERR_NO_CONTENT_FOR_ARRAY: _ClassVar[ResultCode]
    ERR_INVALID_VALUE_TYPE: _ClassVar[ResultCode]
    ERR_MISSING_SUBMESSAGE: _ClassVar[ResultCode]
    ERR_MISSING_DATA: _ClassVar[ResultCode]
    ERR_NOT_FOUND: _ClassVar[ResultCode]
    ERR_NOT_AUTHORIZED: _ClassVar[ResultCode]

class ErrorType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ERROR_TYPE_FAILED: _ClassVar[ErrorType]
    ERROR_TYPE_OVERLOADED: _ClassVar[ErrorType]
    ERROR_TYPE_DISCONNECTED: _ClassVar[ErrorType]
    ERROR_TYPE_UNIMPLEMENTED: _ClassVar[ErrorType]

GENERIC_RESPONSE: Type
VDSM_REQUEST_HELLO: Type
VDC_RESPONSE_HELLO: Type
VDSM_REQUEST_GET_PROPERTY: Type
VDC_RESPONSE_GET_PROPERTY: Type
VDSM_REQUEST_SET_PROPERTY: Type
VDSM_REQUEST_GENERIC_REQUEST: Type
VDSM_SEND_PING: Type
VDC_SEND_PONG: Type
VDC_SEND_ANNOUNCE_DEVICE: Type
VDC_SEND_VANISH: Type
VDC_SEND_PUSH_NOTIFICATION: Type
VDSM_SEND_REMOVE: Type
VDSM_SEND_BYE: Type
VDC_SEND_ANNOUNCE_VDC: Type
VDSM_NOTIFICATION_CALL_SCENE: Type
VDSM_NOTIFICATION_SAVE_SCENE: Type
VDSM_NOTIFICATION_UNDO_SCENE: Type
VDSM_NOTIFICATION_SET_LOCAL_PRIO: Type
VDSM_NOTIFICATION_CALL_MIN_SCENE: Type
VDSM_NOTIFICATION_IDENTIFY: Type
VDSM_NOTIFICATION_SET_CONTROL_VALUE: Type
VDSM_NOTIFICATION_DIM_CHANNEL: Type
VDSM_NOTIFICATION_SET_OUTPUT_CHANNEL_VALUE: Type
VDC_SEND_IDENTIFY: Type
ERR_OK: ResultCode
ERR_MESSAGE_UNKNOWN: ResultCode
ERR_INCOMPATIBLE_API: ResultCode
ERR_SERVICE_NOT_AVAILABLE: ResultCode
ERR_INSUFFICIENT_STORAGE: ResultCode
ERR_FORBIDDEN: ResultCode
ERR_NOT_IMPLEMENTED: ResultCode
ERR_NO_CONTENT_FOR_ARRAY: ResultCode
ERR_INVALID_VALUE_TYPE: ResultCode
ERR_MISSING_SUBMESSAGE: ResultCode
ERR_MISSING_DATA: ResultCode
ERR_NOT_FOUND: ResultCode
ERR_NOT_AUTHORIZED: ResultCode
ERROR_TYPE_FAILED: ErrorType
ERROR_TYPE_OVERLOADED: ErrorType
ERROR_TYPE_DISCONNECTED: ErrorType
ERROR_TYPE_UNIMPLEMENTED: ErrorType

class Message(_message.Message):
    __slots__ = (
        "type",
        "message_id",
        "generic_response",
        "vdsm_request_hello",
        "vdc_response_hello",
        "vdsm_request_get_property",
        "vdc_response_get_property",
        "vdsm_request_set_property",
        "vdsm_request_generic_request",
        "vdsm_send_ping",
        "vdc_send_pong",
        "vdc_send_announce_device",
        "vdc_send_vanish",
        "vdc_send_push_notification",
        "vdsm_send_remove",
        "vdsm_send_bye",
        "vdc_send_announce_vdc",
        "vdsm_send_call_scene",
        "vdsm_send_save_scene",
        "vdsm_send_undo_scene",
        "vdsm_send_set_local_prio",
        "vdsm_send_call_min_scene",
        "vdsm_send_identify",
        "vdsm_send_set_control_value",
        "vdsm_send_dim_channel",
        "vdsm_send_output_channel_value",
        "vdc_send_identify",
    )
    TYPE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    GENERIC_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    VDSM_REQUEST_HELLO_FIELD_NUMBER: _ClassVar[int]
    VDC_RESPONSE_HELLO_FIELD_NUMBER: _ClassVar[int]
    VDSM_REQUEST_GET_PROPERTY_FIELD_NUMBER: _ClassVar[int]
    VDC_RESPONSE_GET_PROPERTY_FIELD_NUMBER: _ClassVar[int]
    VDSM_REQUEST_SET_PROPERTY_FIELD_NUMBER: _ClassVar[int]
    VDSM_REQUEST_GENERIC_REQUEST_FIELD_NUMBER: _ClassVar[int]
    VDSM_SEND_PING_FIELD_NUMBER: _ClassVar[int]
    VDC_SEND_PONG_FIELD_NUMBER: _ClassVar[int]
    VDC_SEND_ANNOUNCE_DEVICE_FIELD_NUMBER: _ClassVar[int]
    VDC_SEND_VANISH_FIELD_NUMBER: _ClassVar[int]
    VDC_SEND_PUSH_NOTIFICATION_FIELD_NUMBER: _ClassVar[int]
    VDSM_SEND_REMOVE_FIELD_NUMBER: _ClassVar[int]
    VDSM_SEND_BYE_FIELD_NUMBER: _ClassVar[int]
    VDC_SEND_ANNOUNCE_VDC_FIELD_NUMBER: _ClassVar[int]
    VDSM_SEND_CALL_SCENE_FIELD_NUMBER: _ClassVar[int]
    VDSM_SEND_SAVE_SCENE_FIELD_NUMBER: _ClassVar[int]
    VDSM_SEND_UNDO_SCENE_FIELD_NUMBER: _ClassVar[int]
    VDSM_SEND_SET_LOCAL_PRIO_FIELD_NUMBER: _ClassVar[int]
    VDSM_SEND_CALL_MIN_SCENE_FIELD_NUMBER: _ClassVar[int]
    VDSM_SEND_IDENTIFY_FIELD_NUMBER: _ClassVar[int]
    VDSM_SEND_SET_CONTROL_VALUE_FIELD_NUMBER: _ClassVar[int]
    VDSM_SEND_DIM_CHANNEL_FIELD_NUMBER: _ClassVar[int]
    VDSM_SEND_OUTPUT_CHANNEL_VALUE_FIELD_NUMBER: _ClassVar[int]
    VDC_SEND_IDENTIFY_FIELD_NUMBER: _ClassVar[int]
    type: Type
    message_id: int
    generic_response: GenericResponse
    vdsm_request_hello: _vdcapi_pb2.vdsm_RequestHello
    vdc_response_hello: _vdcapi_pb2.vdc_ResponseHello
    vdsm_request_get_property: _vdcapi_pb2.vdsm_RequestGetProperty
    vdc_response_get_property: _vdcapi_pb2.vdc_ResponseGetProperty
    vdsm_request_set_property: _vdcapi_pb2.vdsm_RequestSetProperty
    vdsm_request_generic_request: _vdcapi_pb2.vdsm_RequestGenericRequest
    vdsm_send_ping: _vdcapi_pb2.vdsm_SendPing
    vdc_send_pong: _vdcapi_pb2.vdc_SendPong
    vdc_send_announce_device: _vdcapi_pb2.vdc_SendAnnounceDevice
    vdc_send_vanish: _vdcapi_pb2.vdc_SendVanish
    vdc_send_push_notification: _vdcapi_pb2.vdc_SendPushNotification
    vdsm_send_remove: _vdcapi_pb2.vdsm_SendRemove
    vdsm_send_bye: _vdcapi_pb2.vdsm_SendBye
    vdc_send_announce_vdc: _vdcapi_pb2.vdc_SendAnnounceVdc
    vdsm_send_call_scene: _vdcapi_pb2.vdsm_NotificationCallScene
    vdsm_send_save_scene: _vdcapi_pb2.vdsm_NotificationSaveScene
    vdsm_send_undo_scene: _vdcapi_pb2.vdsm_NotificationUndoScene
    vdsm_send_set_local_prio: _vdcapi_pb2.vdsm_NotificationSetLocalPrio
    vdsm_send_call_min_scene: _vdcapi_pb2.vdsm_NotificationCallMinScene
    vdsm_send_identify: _vdcapi_pb2.vdsm_NotificationIdentify
    vdsm_send_set_control_value: _vdcapi_pb2.vdsm_NotificationSetControlValue
    vdsm_send_dim_channel: _vdcapi_pb2.vdsm_NotificationDimChannel
    vdsm_send_output_channel_value: _vdcapi_pb2.vdsm_NotificationSetOutputChannelValue
    vdc_send_identify: _vdcapi_pb2.vdc_SendIdentify
    def __init__(
        self,
        type: Type | str | None = ...,
        message_id: int | None = ...,
        generic_response: GenericResponse | _Mapping | None = ...,
        vdsm_request_hello: _vdcapi_pb2.vdsm_RequestHello | _Mapping | None = ...,
        vdc_response_hello: _vdcapi_pb2.vdc_ResponseHello | _Mapping | None = ...,
        vdsm_request_get_property: _vdcapi_pb2.vdsm_RequestGetProperty
        | _Mapping
        | None = ...,
        vdc_response_get_property: _vdcapi_pb2.vdc_ResponseGetProperty
        | _Mapping
        | None = ...,
        vdsm_request_set_property: _vdcapi_pb2.vdsm_RequestSetProperty
        | _Mapping
        | None = ...,
        vdsm_request_generic_request: _vdcapi_pb2.vdsm_RequestGenericRequest
        | _Mapping
        | None = ...,
        vdsm_send_ping: _vdcapi_pb2.vdsm_SendPing | _Mapping | None = ...,
        vdc_send_pong: _vdcapi_pb2.vdc_SendPong | _Mapping | None = ...,
        vdc_send_announce_device: _vdcapi_pb2.vdc_SendAnnounceDevice
        | _Mapping
        | None = ...,
        vdc_send_vanish: _vdcapi_pb2.vdc_SendVanish | _Mapping | None = ...,
        vdc_send_push_notification: _vdcapi_pb2.vdc_SendPushNotification
        | _Mapping
        | None = ...,
        vdsm_send_remove: _vdcapi_pb2.vdsm_SendRemove | _Mapping | None = ...,
        vdsm_send_bye: _vdcapi_pb2.vdsm_SendBye | _Mapping | None = ...,
        vdc_send_announce_vdc: _vdcapi_pb2.vdc_SendAnnounceVdc | _Mapping | None = ...,
        vdsm_send_call_scene: _vdcapi_pb2.vdsm_NotificationCallScene
        | _Mapping
        | None = ...,
        vdsm_send_save_scene: _vdcapi_pb2.vdsm_NotificationSaveScene
        | _Mapping
        | None = ...,
        vdsm_send_undo_scene: _vdcapi_pb2.vdsm_NotificationUndoScene
        | _Mapping
        | None = ...,
        vdsm_send_set_local_prio: _vdcapi_pb2.vdsm_NotificationSetLocalPrio
        | _Mapping
        | None = ...,
        vdsm_send_call_min_scene: _vdcapi_pb2.vdsm_NotificationCallMinScene
        | _Mapping
        | None = ...,
        vdsm_send_identify: _vdcapi_pb2.vdsm_NotificationIdentify
        | _Mapping
        | None = ...,
        vdsm_send_set_control_value: _vdcapi_pb2.vdsm_NotificationSetControlValue
        | _Mapping
        | None = ...,
        vdsm_send_dim_channel: _vdcapi_pb2.vdsm_NotificationDimChannel
        | _Mapping
        | None = ...,
        vdsm_send_output_channel_value: _vdcapi_pb2.vdsm_NotificationSetOutputChannelValue
        | _Mapping
        | None = ...,
        vdc_send_identify: _vdcapi_pb2.vdc_SendIdentify | _Mapping | None = ...,
    ) -> None: ...

class GenericResponse(_message.Message):
    __slots__ = ("code", "description", "errorType", "userMessageToBeTranslated")
    CODE_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    ERRORTYPE_FIELD_NUMBER: _ClassVar[int]
    USERMESSAGETOBETRANSLATED_FIELD_NUMBER: _ClassVar[int]
    code: ResultCode
    description: str
    errorType: ErrorType
    userMessageToBeTranslated: str
    def __init__(
        self,
        code: ResultCode | str | None = ...,
        description: str | None = ...,
        errorType: ErrorType | str | None = ...,
        userMessageToBeTranslated: str | None = ...,
    ) -> None: ...
