# pyright: reportPrivateUsage=false
import asyncio
import json

import httpx
import pytest

from polymarket._internal.environment import get_environment_config
from polymarket._internal.eoa.rpc import JsonRpcCallError, JsonRpcClient
from polymarket._internal.wallet import (
    derive_beacon_deposit_wallet_address,
    derive_current_deposit_wallet_address,
    derive_uups_deposit_wallet_address,
    get_deposit_wallet_factory_beacon,
    is_beacon_deposit_wallet_factory,
)
from polymarket.clients._transport import AsyncTransport
from polymarket.environments import PRODUCTION

_FACTORY = get_environment_config(PRODUCTION).wallet_derivation.deposit_wallet_factory
_BEACON = get_environment_config(PRODUCTION).wallet_derivation.deposit_wallet_beacon
_SIGNER = "0x0000000000000000000000000000000000000001"
_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
_FACTORY_BEACON_SELECTOR = "0x49493a4d"


def _rpc(handler: httpx.MockTransport) -> JsonRpcClient:
    transport = AsyncTransport(
        base_url="https://rpc.test",
        client=httpx.AsyncClient(base_url="https://rpc.test", transport=handler),
    )
    return JsonRpcClient(transport)


def _capturing_handler(
    response: dict[str, object],
    captured: list[dict[str, object]] | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        if captured is not None:
            captured.append(body)
        envelope = {"jsonrpc": "2.0", "id": body["id"], **response}
        return httpx.Response(200, json=envelope, request=request)

    return httpx.MockTransport(handler)


def test_get_factory_beacon_parses_address_from_return_data() -> None:
    captured: list[dict[str, object]] = []
    handler = _capturing_handler({"result": "0x" + _BEACON[2:].rjust(64, "0").lower()}, captured)

    async def run() -> str:
        rpc = _rpc(handler)
        try:
            return await get_deposit_wallet_factory_beacon(rpc, _FACTORY)
        finally:
            await rpc.close()

    result = asyncio.run(run())
    assert result.lower() == _BEACON.lower()
    assert captured[0]["method"] == "eth_call"
    params = captured[0]["params"]
    assert isinstance(params, list)
    assert params[0] == {"to": _FACTORY, "data": _FACTORY_BEACON_SELECTOR}


def test_get_factory_beacon_returns_zero_address_on_short_return_data() -> None:
    handler = _capturing_handler({"result": "0x"})

    async def run() -> str:
        rpc = _rpc(handler)
        try:
            return await get_deposit_wallet_factory_beacon(rpc, _FACTORY)
        finally:
            await rpc.close()

    assert asyncio.run(run()) == _ZERO_ADDRESS


def test_get_factory_beacon_returns_zero_address_on_contract_revert() -> None:
    handler = _capturing_handler({"error": {"code": 3, "message": "execution reverted"}})

    async def run() -> str:
        rpc = _rpc(handler)
        try:
            return await get_deposit_wallet_factory_beacon(rpc, _FACTORY)
        finally:
            await rpc.close()

    assert asyncio.run(run()) == _ZERO_ADDRESS


def test_get_factory_beacon_returns_zero_address_when_revert_message_nested_in_data() -> None:
    handler = _capturing_handler(
        {
            "error": {
                "code": -32_603,
                "message": "VM Exception while processing transaction",
                "data": {"message": "execution reverted"},
            }
        }
    )

    async def run() -> str:
        rpc = _rpc(handler)
        try:
            return await get_deposit_wallet_factory_beacon(rpc, _FACTORY)
        finally:
            await rpc.close()

    assert asyncio.run(run()) == _ZERO_ADDRESS


def test_get_factory_beacon_propagates_generic_rpc_failures() -> None:
    handler = _capturing_handler({"error": {"code": -32_603, "message": "upstream unavailable"}})

    async def run() -> str:
        rpc = _rpc(handler)
        try:
            return await get_deposit_wallet_factory_beacon(rpc, _FACTORY)
        finally:
            await rpc.close()

    with pytest.raises(JsonRpcCallError, match="upstream unavailable"):
        asyncio.run(run())


def test_is_beacon_deposit_wallet_factory_returns_true_for_beacon_address() -> None:
    handler = _capturing_handler({"result": "0x" + _BEACON[2:].rjust(64, "0").lower()})

    async def run() -> bool:
        rpc = _rpc(handler)
        try:
            return await is_beacon_deposit_wallet_factory(rpc, _FACTORY)
        finally:
            await rpc.close()

    assert asyncio.run(run()) is True


def test_is_beacon_deposit_wallet_factory_returns_false_when_factory_reverts() -> None:
    handler = _capturing_handler({"error": {"code": 3, "message": "execution reverted"}})

    async def run() -> bool:
        rpc = _rpc(handler)
        try:
            return await is_beacon_deposit_wallet_factory(rpc, _FACTORY)
        finally:
            await rpc.close()

    assert asyncio.run(run()) is False


def test_derive_current_picks_beacon_when_factory_exposes_beacon() -> None:
    handler = _capturing_handler({"result": "0x" + _BEACON[2:].rjust(64, "0").lower()})

    async def run() -> str:
        rpc = _rpc(handler)
        try:
            return await derive_current_deposit_wallet_address(
                rpc, _SIGNER, get_environment_config(PRODUCTION).wallet_derivation
            )
        finally:
            await rpc.close()

    result = asyncio.run(run())
    assert (
        result.lower()
        == derive_beacon_deposit_wallet_address(
            _SIGNER, get_environment_config(PRODUCTION).wallet_derivation
        ).lower()
    )


def test_derive_current_picks_uups_when_factory_reverts() -> None:
    handler = _capturing_handler({"error": {"code": 3, "message": "execution reverted"}})

    async def run() -> str:
        rpc = _rpc(handler)
        try:
            return await derive_current_deposit_wallet_address(
                rpc, _SIGNER, get_environment_config(PRODUCTION).wallet_derivation
            )
        finally:
            await rpc.close()

    result = asyncio.run(run())
    assert (
        result.lower()
        == derive_uups_deposit_wallet_address(
            _SIGNER, get_environment_config(PRODUCTION).wallet_derivation
        ).lower()
    )
