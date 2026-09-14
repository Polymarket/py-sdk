from dataclasses import dataclass
from typing import Literal

from polymarket.models.clob.orders import MarketOrderType, OrderType, SignedOrder, TickSize
from polymarket.models.types import ClobAssetId, OrderSide
from polymarket.types import EvmAddress, HexString

BYTES32_ZERO: HexString = HexString(
    "0x0000000000000000000000000000000000000000000000000000000000000000"
)


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderDraft:
    chain_id: int
    exchange_address: EvmAddress
    expiration: int
    funder_address: EvmAddress
    offered_amount: int
    order_type: OrderType
    side: OrderSide
    signer: EvmAddress
    requested_amount: int
    asset_id: ClobAssetId
    builder_code: HexString | None = None

    @property
    def token_id(self) -> ClobAssetId:
        """Deprecated alias for :attr:`asset_id`."""

        return self.asset_id


@dataclass(frozen=True, slots=True, kw_only=True)
class UnsignedOrder:
    chain_id: int
    builder: HexString
    exchange_address: EvmAddress
    expiration: int
    maker: EvmAddress
    maker_amount: int
    metadata: HexString
    order_type: OrderType
    salt: int
    side: OrderSide
    signature_type: int
    signer: EvmAddress
    taker_amount: int
    timestamp: int
    token_id: ClobAssetId
    protocol_version: Literal["2", "3"] = "2"


__all__ = [
    "BYTES32_ZERO",
    "MarketOrderType",
    "OrderDraft",
    "OrderType",
    "SignedOrder",
    "TickSize",
    "UnsignedOrder",
]
