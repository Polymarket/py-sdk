from polymarket.errors import UserInputError
from polymarket.models.clob.order_heartbeats import OrderHeartbeat


def build_send_order_heartbeat_request(*, heartbeat_id: str = "") -> tuple[str, dict[str, str]]:
    if type(heartbeat_id) is not str:
        raise UserInputError(
            "heartbeat_id must be a string; use an empty string for the first send."
        )
    return "/v1/heartbeats", {"heartbeat_id": heartbeat_id}


def parse_order_heartbeat(data: object) -> OrderHeartbeat:
    return OrderHeartbeat.parse_response(data)
