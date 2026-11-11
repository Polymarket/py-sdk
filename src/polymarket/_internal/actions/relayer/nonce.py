from __future__ import annotations

from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.models.clob.relayer import RelayerExecuteParams, RelayerTransactionType


async def fetch_execute_params(
    relayer: AsyncTransport,
    *,
    address: str,
    type: RelayerTransactionType,
) -> RelayerExecuteParams:
    data = await relayer.get_json(
        "/v1/wallets/execute-params",
        params={"address": address, "type": type.value},
    )
    return RelayerExecuteParams.parse_response(data)


def fetch_execute_params_sync(
    relayer: SyncTransport,
    *,
    address: str,
    type: RelayerTransactionType,
) -> RelayerExecuteParams:
    data = relayer.get_json(
        "/v1/wallets/execute-params",
        params={"address": address, "type": type.value},
    )
    return RelayerExecuteParams.parse_response(data)


__all__ = [
    "fetch_execute_params",
    "fetch_execute_params_sync",
]
