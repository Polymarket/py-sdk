from polymarket.errors import UserInputError
from polymarket.models.clob.order_heartbeats import LegacyOrderHeartbeat, OrderHeartbeat


def build_send_order_heartbeat_request(*, heartbeat_id: str = "") -> tuple[str, dict[str, str]]:
    if type(heartbeat_id) is not str:
        raise UserInputError(
            "heartbeat_id must be a string; use an empty string for the first send."
        )
    return "/v1/heartbeats", {"heartbeat_id": heartbeat_id}


def build_send_legacy_order_heartbeat_request() -> str:
    return "/heartbeats"


def parse_order_heartbeat(data: object) -> OrderHeartbeat:
    return OrderHeartbeat.parse_response(data)


def parse_legacy_order_heartbeat(data: object) -> LegacyOrderHeartbeat:
    return LegacyOrderHeartbeat.parse_response(data)
