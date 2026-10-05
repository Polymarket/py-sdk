import secrets
import time

from polymarket._internal.actions.orders.types import BYTES32_ZERO, OrderDraft, UnsignedOrder
from polymarket._internal.protocol import is_v2_position_id
from polymarket._internal.wallet import WalletType, signature_type_for
from polymarket.models.clob.orders import SignedOrder
from polymarket.types import EvmAddress, HexString

_POLY_1271_SIGNATURE_TYPE = 3
_SALT_BITS = 53


def create_unsigned_order(
    draft: OrderDraft,
    *,
    wallet: EvmAddress,
    wallet_type: WalletType,
) -> UnsignedOrder:
    signature_type = signature_type_for(wallet_type)
    signer = wallet if signature_type == _POLY_1271_SIGNATURE_TYPE else draft.signer
    return UnsignedOrder(
        builder=draft.builder_code or BYTES32_ZERO,
        chain_id=draft.chain_id,
        exchange_address=draft.exchange_address,
        expiration=draft.expiration,
        maker=draft.funder_address,
        maker_amount=draft.offered_amount,
        metadata=BYTES32_ZERO,
        order_type=draft.order_type,
        salt=_generate_salt(),
        side=draft.side,
        signature_type=signature_type,
        signer=signer,
        taker_amount=draft.requested_amount,
        timestamp=_current_timestamp_ms(),
        token_id=draft.asset_id,
        protocol_version="3" if is_v2_position_id(draft.asset_id) else "2",
    )


def create_signed_order(
    order: UnsignedOrder,
    signature: HexString,
    *,
    post_only: bool = False,
) -> SignedOrder:
    return SignedOrder(
        builder=order.builder,
        expiration=order.expiration,
        maker=order.maker,
        maker_amount=order.maker_amount,
        metadata=order.metadata,
        order_type=order.order_type,
        salt=order.salt,
        side=order.side,
        signature=signature,
        signature_type=order.signature_type,
        signer=order.signer,
        taker_amount=order.taker_amount,
        timestamp=order.timestamp,
        token_id=order.token_id,
        post_only=post_only,
    )


def _generate_salt() -> int:
    return secrets.randbits(_SALT_BITS)


def _current_timestamp_ms() -> int:
    return int(time.time() * 1000)


__all__ = ["create_signed_order", "create_unsigned_order"]
