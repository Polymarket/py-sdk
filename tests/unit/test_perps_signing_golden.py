"""Golden signing vectors generated from the TypeScript SDK Perps implementation.

Each vector pins the msgpack encoding, the EIP-712 ``Op.data`` hash, and the
final signature so the Python implementation stays byte-compatible with the
backend's verification path.
"""

from typing import Any

import pytest
from eth_account import Account

from polymarket._internal.actions.perps.signing import (
    build_perps_create_proxy_typed_data,
    build_perps_op_typed_data,
    build_perps_withdraw_typed_data,
    compact_signable_value,
    hash_perps_op,
    sign_owner_typed_data,
    sign_perps_op_with_key,
)

_PRIVATE_KEY = "0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
_CHAIN_ID = 137

_OP_VECTORS: list[dict[str, Any]] = [
    {
        "name": "createOrders single GTC",
        "op": ["createOrders", [[1, True, "0.5", "10", "gtc", False, None, None, None]]],
        "salt": 12345,
        "timestamp": 1751500000000,
        "data": "0x8004f264b573f0d5edd3377ef127f251a2b11e0b9463c5fb5f1be3b42c94336a",
        "signature": (
            "0xdd933bdada3c14c01dbe48fc02d470f423f0e0ef0897052602c964e20f82c709"
            "7c1ea1033e1e939a0633db606781f3b7160603337ab6201755cb191e99bc2d9b1c"
        ),
    },
    {
        "name": "createOrders IOC no price with coid",
        "op": [
            "createOrders",
            [
                [
                    42,
                    False,
                    None,
                    "2.5",
                    "ioc",
                    False,
                    None,
                    "aabbccddeeff00112233445566778899",
                    None,
                ]
            ],
        ],
        "salt": 4294967295,
        "timestamp": 1751500000001,
        "data": "0x3b358621af8f4d297ea0c78b9d40aa9d33b84de0f9a619726f8f9e2f305c0157",
        "signature": (
            "0x1b728cc550e2691bab29ccf183990ab53786fe86b28a5659560f6c7e92faa8f6"
            "0535f2a0731265f0bdb9bf9c3649ada69857dfe33c887ff9b3fc2794d605adde1b"
        ),
    },
    {
        "name": "createOrders grouped with tpsl triggers",
        "op": [
            "createOrders",
            [
                [7, True, "100", "3", "gtc", False, None, None, None],
                [7, False, None, "3", None, False, True, None, [True, "200", "tp"]],
                [7, False, "50", "3", None, False, True, None, [None, "49", "sl"]],
            ],
            "order",
        ],
        "salt": 1,
        "timestamp": 1751500000002,
        "data": "0x34b31ff82aa6d39bd6ee54a7781287d6e6dffcc0cc7dcc981f70e381c7d8a641",
        "signature": (
            "0xfa7438604c02142ed9a0e3612a38d3b0b49eb21141515ac9a30be03b9f4422ea"
            "5b598c70b2e733f6564eb322ac6ec5293c656c86426f389e9c5454e33d086cb21b"
        ),
    },
    {
        "name": "cancelOrders",
        "op": ["cancelOrders", [11, 22, 33]],
        "salt": 999,
        "timestamp": 1751500000003,
        "data": "0x13f4659952efbcd144324c0a1c50cb75069635b2bbf28d3cc1e51b6e176a7617",
        "signature": (
            "0xb97be11bcffaca178b29ecc42cabc732d0f436fad42a42e3a63f32131b347be5"
            "11d452b14a81bdefc7cfda84bf83c94afedfb16fd8df16883cf6e261e411dfe91c"
        ),
    },
    {
        "name": "cancelOrdersCOID",
        "op": ["cancelOrdersCOID", ["aabbccddeeff00112233445566778899"]],
        "salt": 1000,
        "timestamp": 1751500000004,
        "data": "0xdf8f1749d1b75392360c1117dcf2e0f251b0197b4db21c37a4e7d2451bc7cc95",
        "signature": (
            "0xf3b23b2357864efb2cd1ac128a9b6601c85a7894d9be000243f253a37f778c39"
            "525d0359d95e01350d5bfca6ebf4b84bb5735acfbcb8c8fb90978bb9f371d58a1c"
        ),
    },
    {
        "name": "updateLeverage",
        "op": ["updateLeverage", [3, 20, True]],
        "salt": 7,
        "timestamp": 1751500000005,
        "data": "0x1daa002ce2f4e42ab0ef2d3c489b2386cccac2cbb861bdd7695761d4d93dd410",
        "signature": (
            "0x5b81c182f89acc819488f30daa7a6fdb7563b0f65b2b404e9ece8a72d8077c3f"
            "6bf328900ed6594d56605e564fa1e4469c8be670ac86015ab160bd78a97ea2bd1b"
        ),
    },
    {
        "name": "autoCancel arm",
        "op": ["autoCancel", [1767000045000]],
        "salt": 12345,
        "timestamp": 1751500000000,
        "data": "0x8d16f1dbf6be71cea6ad70c5b09f028dd1b451cebb2c7dd20c82dbf1022440ba",
        "signature": (
            "0x9019fb6edfc125e19635ac74d50efc1c863bc26e4d395ee76a8e26d7df001144"
            "24d5a338540f9b7ecb46fb3825ad662da852856257829c3664ce84d02bfcdda81c"
        ),
    },
    {
        "name": "autoCancel clear",
        "op": ["autoCancel", [0]],
        "salt": 12345,
        "timestamp": 1751500000000,
        "data": "0x569d0f5365d9bb75e7f2218717986828ea553b937a4c901528c70fa173fa539e",
        "signature": (
            "0x188bebb866e6f11dd439ea12e2869eb9308fb6a9c6c9da09ece8a74467d7c4ac"
            "582c4a9929094af1d994467e40c81143de007b6b1499286b265512fdde82b29a1c"
        ),
    },
    {
        "name": "updateMargin",
        "op": ["updateMargin", [3, "-25.000000000000000001"]],
        "salt": 8,
        "timestamp": 1751500000006,
        "data": "0x1bceee4cd50ae288f5ae7e993deeea51fe9dd41b5eff27840455ed72e72d4f4c",
        "signature": (
            "0xfd6ec2ee47423b3f87adfc64eadd9764180e05102efadb112403016a446d072d"
            "497ec201b2df1e7944f465c9c734d3698b80dbe51a42eb8167a7a54e4249dfc81b"
        ),
    },
    {
        "name": "deleteProxy",
        "op": ["deleteProxy", ["0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc"]],
        "salt": 55,
        "timestamp": 1751500000006,
        "data": "0x7274223decc60adbbe3ba91ceade2e6cd7901ab7ba506d07fb2d0dbef83e30d4",
        "signature": (
            "0x2f6400725b8af890a69b8c47fe9d2b100d15714a73a13a92b15187909d1c1080"
            "51dc906b8ec65cfc4d161c579df7b2cb9c6f7efea30dc238cfd7526fd3b797c01c"
        ),
    },
]


@pytest.mark.parametrize("vector", _OP_VECTORS, ids=lambda vector: vector["name"])
def test_perps_op_signing_matches_typescript_vectors(vector: dict[str, Any]) -> None:
    assert hash_perps_op(vector["op"]) == vector["data"]
    signature = sign_perps_op_with_key(
        _PRIVATE_KEY,
        chain_id=_CHAIN_ID,
        op=vector["op"],
        salt=vector["salt"],
        timestamp_ms=vector["timestamp"],
    )
    assert signature == vector["signature"]


def test_compact_signable_value_drops_none_entries_recursively() -> None:
    assert compact_signable_value(
        ["createOrders", [[1, True, None, "10", "gtc", False, None, None, None]]]
    ) == ["createOrders", [[1, True, "10", "gtc", False]]]


def test_op_typed_data_payload_shape() -> None:
    payload = build_perps_op_typed_data(
        chain_id=_CHAIN_ID, op=["cancelOrders", [1]], salt=2, timestamp_ms=3
    )
    assert payload["primaryType"] == "Op"
    assert payload["domain"] == {"name": "Polymarket", "version": "1", "chainId": _CHAIN_ID}
    assert payload["message"]["salt"] == 2
    assert payload["message"]["ts"] == 3


def test_create_proxy_signature_matches_typescript_vector() -> None:
    signer = Account.from_key(_PRIVATE_KEY)
    signature = sign_owner_typed_data(
        signer,
        build_perps_create_proxy_typed_data(
            chain_id=_CHAIN_ID,
            proxy="0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc",
            expires_at_ms=1752000000000,
            salt=4242,
            timestamp_ms=1751500000007,
        ),
        what="Perps proxy credentials request",
    )
    assert signature == (
        "0x64e2d5aef2aeb5e58072ebb63f8419ba0f89d1de34635a007ef648db9e6ac6f3"
        "01997797def6e6a5b118f09fb1da0e3f58a55c34a871968e13227ae40eabf9341c"
    )


def test_withdraw_signature_matches_typescript_vector() -> None:
    signer = Account.from_key(_PRIVATE_KEY)
    signature = sign_owner_typed_data(
        signer,
        build_perps_withdraw_typed_data(
            chain_id=_CHAIN_ID,
            deposit_contract="0xDCa4af75705dbB50f62437045afF9921947917d2",
            account="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
            token="0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB",
            amount=10_000_000,
            to="0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc",
            salt=77,
            timestamp_s=1751500000,
        ),
        what="Perps withdrawal request",
    )
    assert signature == (
        "0x75b6d0d9572921ed71d2a13fd3585dbd34326d9b503edaca08e3bf72dcd7bb43"
        "7fe67378df001fc9e4352063a87d9e0a690599bf0ed6849ec00660e6f28cfa1c1b"
    )
