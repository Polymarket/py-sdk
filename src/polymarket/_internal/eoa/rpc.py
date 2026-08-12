from __future__ import annotations

import asyncio
import json as _json
from collections.abc import Sequence
from typing import Any, TypeAlias, cast

from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.errors import RequestRejectedError, UnexpectedResponseError, UserInputError

_JSON_RPC_REVERT_CODES = frozenset({3, -32_000, -32_003, -32_015, -32_603})
_JSON_RPC_REVERT_TOKENS = ("execution reverted", "revert", "invalid opcode")
EthCallBatchRequest: TypeAlias = tuple[str, str]


class JsonRpcCallError(RequestRejectedError):
    def __init__(self, method: str, code: int, message: str, data: object) -> None:
        super().__init__(f"JSON-RPC {method} failed: {message}", status=200)
        self.method = method
        self.code = code
        self.message = message
        self.data = data


def is_json_rpc_contract_revert(error: object) -> bool:
    if not isinstance(error, JsonRpcCallError):
        return False
    if error.code not in _JSON_RPC_REVERT_CODES:
        return False
    haystack = f"{error.message} {_stringify_error_data(error.data)}".lower()
    return any(token in haystack for token in _JSON_RPC_REVERT_TOKENS)


def _stringify_error_data(data: object) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    try:
        return _json.dumps(data)
    except (TypeError, ValueError):
        return ""


class JsonRpcClient:
    def __init__(self, transport: AsyncTransport) -> None:
        self._transport = transport
        self._id = 0
        self._verified_chain_id: int | None = None

    async def close(self) -> None:
        await self._transport.close()

    async def verify_chain_id(self, expected: int) -> None:
        if self._verified_chain_id is not None:
            if self._verified_chain_id != expected:
                raise UserInputError(
                    f"RPC chain id {self._verified_chain_id} does not match "
                    f"environment chain id {expected}. Configure the client for the correct chain."
                )
            return
        actual = await self.eth_chain_id()
        if actual != expected:
            raise UserInputError(
                f"RPC chain id {actual} does not match environment chain id {expected}. "
                "Configure the client for the correct chain."
            )
        self._verified_chain_id = actual

    async def _call(self, method: str, params: list[Any]) -> Any:
        envelope = self._build_envelope(method, params)
        raw = await self._transport.post_json("", json=envelope)
        return _parse_rpc_response(method, raw)

    def _build_envelope(self, method: str, params: list[Any]) -> dict[str, Any]:
        self._id += 1
        return {
            "jsonrpc": "2.0",
            "id": self._id,
            "method": method,
            "params": params,
        }

    async def eth_chain_id(self) -> int:
        result = await self._call("eth_chainId", [])
        return _hex_to_int(result, "eth_chainId")

    async def eth_call(self, *, to: str, data: str, block: str = "latest") -> str:
        result = await self._call("eth_call", [{"to": to, "data": data}, block])
        return _parse_eth_call_result(result)

    async def eth_call_batch(
        self, requests: Sequence[EthCallBatchRequest], *, block: str = "latest"
    ) -> list[str]:
        if not requests:
            return []
        return await self._eth_call_batch_with_split(requests, block=block)

    async def _eth_call_batch_with_split(
        self, requests: Sequence[EthCallBatchRequest], *, block: str
    ) -> list[str]:
        if len(requests) == 1:
            to, data = requests[0]
            return [await self.eth_call(to=to, data=data, block=block)]

        try:
            return await self._post_eth_call_batch(requests, block=block)
        except RequestRejectedError as error:
            if error.status < 500:
                raise

            midpoint = (len(requests) + 1) // 2
            left, right = await asyncio.gather(
                self._eth_call_batch_with_split(requests[:midpoint], block=block),
                self._eth_call_batch_with_split(requests[midpoint:], block=block),
            )
            return [*left, *right]

    async def _post_eth_call_batch(
        self, requests: Sequence[EthCallBatchRequest], *, block: str
    ) -> list[str]:
        envelopes = [
            self._build_envelope("eth_call", [{"to": to, "data": data}, block])
            for to, data in requests
        ]
        raw = await self._transport.post_json("", json=envelopes)
        return _parse_eth_call_batch_response(raw, envelopes)

    async def eth_get_transaction_count(self, address: str, block: str = "pending") -> int:
        result = await self._call("eth_getTransactionCount", [address, block])
        return _hex_to_int(result, "eth_getTransactionCount")

    async def eth_gas_price(self) -> int:
        result = await self._call("eth_gasPrice", [])
        return _hex_to_int(result, "eth_gasPrice")

    async def eth_estimate_gas(self, tx: dict[str, Any]) -> int:
        result = await self._call("eth_estimateGas", [tx])
        return _hex_to_int(result, "eth_estimateGas")

    async def eth_send_raw_transaction(self, signed_hex: str) -> str:
        result = await self._call("eth_sendRawTransaction", [signed_hex])
        if not isinstance(result, str):
            raise UnexpectedResponseError("eth_sendRawTransaction did not return a hex string")
        return result

    async def eth_get_transaction_receipt(self, tx_hash: str) -> dict[str, Any] | None:
        result = await self._call("eth_getTransactionReceipt", [tx_hash])
        if result is None:
            return None
        if not isinstance(result, dict):
            raise UnexpectedResponseError("eth_getTransactionReceipt did not return an object")
        return cast(dict[str, Any], result)


class SyncJsonRpcClient:
    def __init__(self, transport: SyncTransport) -> None:
        self._transport = transport
        self._id = 0
        self._verified_chain_id: int | None = None

    def close(self) -> None:
        self._transport.close()

    def verify_chain_id(self, expected: int) -> None:
        if self._verified_chain_id is not None:
            if self._verified_chain_id != expected:
                raise UserInputError(
                    f"RPC chain id {self._verified_chain_id} does not match "
                    f"environment chain id {expected}. Configure the client for the correct chain."
                )
            return
        actual = self.eth_chain_id()
        if actual != expected:
            raise UserInputError(
                f"RPC chain id {actual} does not match environment chain id {expected}. "
                "Configure the client for the correct chain."
            )
        self._verified_chain_id = actual

    def _call(self, method: str, params: list[Any]) -> Any:
        envelope = self._build_envelope(method, params)
        raw = self._transport.post_json("", json=envelope)
        return _parse_rpc_response(method, raw)

    def _build_envelope(self, method: str, params: list[Any]) -> dict[str, Any]:
        self._id += 1
        return {
            "jsonrpc": "2.0",
            "id": self._id,
            "method": method,
            "params": params,
        }

    def eth_chain_id(self) -> int:
        result = self._call("eth_chainId", [])
        return _hex_to_int(result, "eth_chainId")

    def eth_call(self, *, to: str, data: str, block: str = "latest") -> str:
        result = self._call("eth_call", [{"to": to, "data": data}, block])
        return _parse_eth_call_result(result)

    def eth_call_batch(
        self, requests: Sequence[EthCallBatchRequest], *, block: str = "latest"
    ) -> list[str]:
        if not requests:
            return []
        return self._eth_call_batch_with_split(requests, block=block)

    def _eth_call_batch_with_split(
        self, requests: Sequence[EthCallBatchRequest], *, block: str
    ) -> list[str]:
        if len(requests) == 1:
            to, data = requests[0]
            return [self.eth_call(to=to, data=data, block=block)]

        try:
            return self._post_eth_call_batch(requests, block=block)
        except RequestRejectedError as error:
            if error.status < 500:
                raise

            midpoint = (len(requests) + 1) // 2
            left = self._eth_call_batch_with_split(requests[:midpoint], block=block)
            right = self._eth_call_batch_with_split(requests[midpoint:], block=block)
            return [*left, *right]

    def _post_eth_call_batch(
        self, requests: Sequence[EthCallBatchRequest], *, block: str
    ) -> list[str]:
        envelopes = [
            self._build_envelope("eth_call", [{"to": to, "data": data}, block])
            for to, data in requests
        ]
        raw = self._transport.post_json("", json=envelopes)
        return _parse_eth_call_batch_response(raw, envelopes)

    def eth_get_transaction_count(self, address: str, block: str = "pending") -> int:
        result = self._call("eth_getTransactionCount", [address, block])
        return _hex_to_int(result, "eth_getTransactionCount")

    def eth_gas_price(self) -> int:
        result = self._call("eth_gasPrice", [])
        return _hex_to_int(result, "eth_gasPrice")

    def eth_estimate_gas(self, tx: dict[str, Any]) -> int:
        result = self._call("eth_estimateGas", [tx])
        return _hex_to_int(result, "eth_estimateGas")

    def eth_send_raw_transaction(self, signed_hex: str) -> str:
        result = self._call("eth_sendRawTransaction", [signed_hex])
        if not isinstance(result, str):
            raise UnexpectedResponseError("eth_sendRawTransaction did not return a hex string")
        return result

    def eth_get_transaction_receipt(self, tx_hash: str) -> dict[str, Any] | None:
        result = self._call("eth_getTransactionReceipt", [tx_hash])
        if result is None:
            return None
        if not isinstance(result, dict):
            raise UnexpectedResponseError("eth_getTransactionReceipt did not return an object")
        return cast(dict[str, Any], result)


def _extract_error_fields(err: object) -> tuple[int, str, object]:
    if isinstance(err, dict):
        err_dict = cast(dict[str, object], err)
        raw_code = err_dict.get("code")
        code = raw_code if isinstance(raw_code, int) and not isinstance(raw_code, bool) else 0
        raw_message = err_dict.get("message")
        message = raw_message if isinstance(raw_message, str) else repr(err_dict)
        return code, message, err_dict.get("data")
    return 0, str(err), None


def _parse_rpc_response(method: str, raw: object) -> Any:
    if not isinstance(raw, dict):
        raise UnexpectedResponseError(f"JSON-RPC {method} returned a non-object response")
    response = cast(dict[str, Any], raw)
    if "error" in response:
        err: Any = response["error"]
        code, message, data = _extract_error_fields(err)
        raise JsonRpcCallError(method=method, code=code, message=message, data=data)
    return response.get("result")


def _parse_eth_call_batch_response(raw: object, envelopes: Sequence[dict[str, Any]]) -> list[str]:
    if not isinstance(raw, list):
        raise UnexpectedResponseError("JSON-RPC eth_call batch returned a non-array response")

    responses_by_id: dict[int, dict[str, Any]] = {}
    for item in cast(list[object], raw):
        if not isinstance(item, dict):
            raise UnexpectedResponseError("JSON-RPC eth_call batch returned a non-object item")
        response = cast(dict[str, Any], item)
        raw_id = response.get("id")
        if not isinstance(raw_id, int) or isinstance(raw_id, bool):
            raise UnexpectedResponseError(
                "JSON-RPC eth_call batch response is missing a numeric id"
            )
        if raw_id in responses_by_id:
            raise UnexpectedResponseError("JSON-RPC eth_call batch returned a duplicate id")
        responses_by_id[raw_id] = response

    results: list[str] = []
    for envelope in envelopes:
        raw_id = envelope["id"]
        if not isinstance(raw_id, int) or isinstance(raw_id, bool):
            raise RuntimeError("JSON-RPC request id must be an integer")
        response = responses_by_id.get(raw_id)
        if response is None:
            raise UnexpectedResponseError("JSON-RPC eth_call batch response is missing an id")
        results.append(_parse_eth_call_result(_parse_rpc_response("eth_call", response)))
    return results


def _parse_eth_call_result(result: Any) -> str:
    if not isinstance(result, str) or not _is_rpc_hex_string(result):
        raise UnexpectedResponseError("eth_call did not return a hex string")
    return result


def _is_rpc_hex_string(value: str) -> bool:
    if not value.startswith("0x"):
        return False
    rest = value[2:]
    return all(c in "0123456789abcdefABCDEF" for c in rest)


def _hex_to_int(value: Any, method: str) -> int:
    if not isinstance(value, str):
        raise UnexpectedResponseError(f"{method} did not return a hex string")
    try:
        return int(value, 16)
    except ValueError as error:
        raise UnexpectedResponseError(f"{method} returned malformed hex: {error}") from error


__all__ = [
    "EthCallBatchRequest",
    "JsonRpcCallError",
    "JsonRpcClient",
    "SyncJsonRpcClient",
    "is_json_rpc_contract_revert",
]
