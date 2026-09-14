from dataclasses import dataclass
from typing import Literal, TypeAlias

from polymarket.models.types import ClobAssetId, OrderSide
from polymarket.types import EvmAddress, HexString

OrderType: TypeAlias = Literal["GTC", "GTD", "FAK", "FOK"]
MarketOrderType: TypeAlias = Literal["FAK", "FOK"]
TickSize: TypeAlias = Literal["0.1", "0.01", "0.005", "0.0025", "0.001", "0.0001"]


@dataclass(frozen=True, slots=True, kw_only=True)
class SignedOrder:
    builder: HexString
    expiration: int
    maker: EvmAddress
    maker_amount: int
    metadata: HexString
    order_type: OrderType
    salt: int
    side: OrderSide
    signature: HexString
    signature_type: int
    signer: EvmAddress
    taker_amount: int
    timestamp: int
    token_id: ClobAssetId
    post_only: bool = False


__all__ = ["MarketOrderType", "OrderType", "SignedOrder", "TickSize"]
