from __future__ import annotations

from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.models.clob.relayer import (
    RelayerDeployedResponse,
    RelayerTransactionType,
)


async def fetch_deployed(
    relayer: AsyncTransport,
    *,
    address: str,
    type: RelayerTransactionType | None = None,
) -> bool:
    params: dict[str, str | None] = {"address": address}
    if type is not None:
        params["type"] = type.value
    data = await relayer.get_json("/v1/wallets/deployed", params=params)
    return RelayerDeployedResponse.parse_response(data).deployed


def fetch_deployed_sync(
    relayer: SyncTransport,
    *,
    address: str,
    type: RelayerTransactionType | None = None,
) -> bool:
    params: dict[str, str | None] = {"address": address}
    if type is not None:
        params["type"] = type.value
    data = relayer.get_json("/v1/wallets/deployed", params=params)
    return RelayerDeployedResponse.parse_response(data).deployed


__all__ = ["fetch_deployed", "fetch_deployed_sync"]
