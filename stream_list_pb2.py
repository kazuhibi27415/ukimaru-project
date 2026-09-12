# Minimal Protocol Buffer definitions required by this project.
# Wire-compatible subset of YouTube's official stream_list.proto.
# The project bundles this file so grpcio-tools/protoc is not required on Windows.

from google.protobuf import descriptor_pb2 as _descriptor_pb2
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder

_sym_db = _symbol_database.Default()

_fdp = _descriptor_pb2.FileDescriptorProto()
_fdp.name = "stream_list.proto"
_fdp.package = "youtube.api.v3"
_fdp.syntax = "proto2"


def _message(name):
    m = _fdp.message_type.add()
    m.name = name
    return m


def _field(message, name, number, field_type, label=1, type_name=None):
    f = message.field.add()
    f.name = name
    f.number = number
    f.label = label  # 1 optional, 3 repeated
    f.type = field_type
    if type_name:
        f.type_name = type_name
    return f


# Field types: uint64=4, string=9, message=11, uint32=13, enum=14
_request = _message("LiveChatMessageListRequest")
_field(_request, "live_chat_id", 1, 9)
_field(_request, "max_results", 98, 13)
_field(_request, "page_token", 99, 9)
_field(_request, "part", 100, 9, 3)

_response = _message("LiveChatMessageListResponse")
_field(_response, "offline_at", 2, 9)
_field(_response, "next_page_token", 100602, 9)
_field(
    _response,
    "items",
    1007,
    11,
    3,
    ".youtube.api.v3.LiveChatMessage",
)

_message_item = _message("LiveChatMessage")
_field(_message_item, "id", 101, 9)
_field(
    _message_item,
    "snippet",
    2,
    11,
    1,
    ".youtube.api.v3.LiveChatMessageSnippet",
)
_field(
    _message_item,
    "author_details",
    3,
    11,
    1,
    ".youtube.api.v3.LiveChatMessageAuthorDetails",
)

_author = _message("LiveChatMessageAuthorDetails")
_field(_author, "display_name", 103, 9)

_snippet = _message("LiveChatMessageSnippet")
_type_wrapper = _snippet.nested_type.add()
_type_wrapper.name = "TypeWrapper"
_type_enum = _type_wrapper.enum_type.add()
_type_enum.name = "Type"
for _name, _number in (
    ("INVALID_TYPE", 0),
    ("SUPER_CHAT_EVENT", 15),
    ("SUPER_STICKER_EVENT", 16),
):
    _value = _type_enum.value.add()
    _value.name = _name
    _value.number = _number

_field(
    _snippet,
    "type",
    1,
    14,
    1,
    ".youtube.api.v3.LiveChatMessageSnippet.TypeWrapper.Type",
)
_field(_snippet, "published_at", 4, 9)
_field(
    _snippet,
    "super_chat_details",
    27,
    11,
    1,
    ".youtube.api.v3.LiveChatSuperChatDetails",
)

_super_chat = _message("LiveChatSuperChatDetails")
_field(_super_chat, "amount_micros", 1, 4)
_field(_super_chat, "currency", 2, 9)
_field(_super_chat, "amount_display_string", 3, 9)
_field(_super_chat, "user_comment", 4, 9)
_field(_super_chat, "tier", 5, 13)

_service = _fdp.service.add()
_service.name = "V3DataLiveChatMessageService"
_method = _service.method.add()
_method.name = "StreamList"
_method.input_type = ".youtube.api.v3.LiveChatMessageListRequest"
_method.output_type = ".youtube.api.v3.LiveChatMessageListResponse"
_method.server_streaming = True

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(_fdp.SerializeToString())
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, __name__, globals())
