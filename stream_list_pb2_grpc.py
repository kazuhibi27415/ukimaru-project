import grpc
import stream_list_pb2 as stream__list__pb2


class V3DataLiveChatMessageServiceStub:
    def __init__(self, channel: grpc.Channel):
        self.StreamList = channel.unary_stream(
            "/youtube.api.v3.V3DataLiveChatMessageService/StreamList",
            request_serializer=stream__list__pb2.LiveChatMessageListRequest.SerializeToString,
            response_deserializer=stream__list__pb2.LiveChatMessageListResponse.FromString,
        )
