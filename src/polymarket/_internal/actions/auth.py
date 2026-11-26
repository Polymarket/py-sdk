from typing import cast

from pydantic import TypeAdapter, ValidationError

from polymarket._internal.actions.relayer.auth import build_builder_key_headers
from polymarket._internal.l1_auth import ApiKeyAuthSignature
from polymarket.auth import BuilderApiKey
from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.errors import RequestRejectedError, UnexpectedResponseError
from polymarket.models.clob import ApiKeyCreds, BuilderApiKeyInfo, RateLimitTier

_RATE_LIMIT_TIER_PATH = "/v1/user/rate-limit-tier"

_BUILDER_API_KEY_PATH = "/auth/builder-api-key"

_ApiKeysListAdapter = TypeAdapter(tuple[str, ...])
_BuilderApiKeyInfoListAdapter = TypeAdapter(tuple[BuilderApiKeyInfo, ...])


def build_l1_auth_headers(signature: ApiKeyAuthSignature) -> dict[str, str]:
    return {
        "POLY_ADDRESS": signature.address,
        "POLY_NONCE": str(signature.nonce),
        "POLY_SIGNATURE": signature.signature,
        "POLY_TIMESTAMP": str(signature.timestamp),
    }


def parse_api_key_creds(data: object) -> ApiKeyCreds:
    return ApiKeyCreds.parse_response(data)


def parse_api_keys_response(data: object) -> tuple[str, ...]:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("api keys response did not match expected shape")
    api_keys = cast(dict[str, object], data).get("apiKeys")
    try:
        return _ApiKeysListAdapter.validate_python(api_keys)
    except ValidationError as error:
        raise UnexpectedResponseError("api keys response did not match expected shape") from error


def parse_builder_api_key_creds(data: object) -> BuilderApiKey:
    if not isinstance(data, dict):
        raise UnexpectedResponseError("builder api key response did not match expected shape")
    fields = cast(dict[str, object], data)
    key = fields.get("key")
    secret = fields.get("secret")
    passphrase = fields.get("passphrase")
    if not (isinstance(key, str) and isinstance(secret, str) and isinstance(passphrase, str)):
        raise UnexpectedResponseError("builder api key response did not match expected shape")
    return BuilderApiKey(key=key, secret=secret, passphrase=passphrase)


def parse_builder_api_keys_response(data: object) -> tuple[BuilderApiKeyInfo, ...]:
    if not isinstance(data, list):
        raise UnexpectedResponseError("builder api keys response did not match expected shape")
    normalized = [
        {"key": item} if isinstance(item, str) else item for item in cast(list[object], data)
    ]
    try:
        return _BuilderApiKeyInfoListAdapter.validate_python(normalized)
    except ValidationError as error:
        raise UnexpectedResponseError(
            "builder api keys response did not match expected shape"
        ) from error


async def create_api_key(clob: AsyncTransport, signature: ApiKeyAuthSignature) -> ApiKeyCreds:
    payload = await clob.post_json("/auth/api-key", headers=build_l1_auth_headers(signature))
    return parse_api_key_creds(payload)


async def derive_api_key(clob: AsyncTransport, signature: ApiKeyAuthSignature) -> ApiKeyCreds:
    payload = await clob.get_json("/auth/derive-api-key", headers=build_l1_auth_headers(signature))
    return parse_api_key_creds(payload)


async def create_or_derive_api_key(
    clob: AsyncTransport, signature: ApiKeyAuthSignature
) -> ApiKeyCreds:
    try:
        return await create_api_key(clob, signature)
    except RequestRejectedError as error:
        if error.status != 400:
            raise
    return await derive_api_key(clob, signature)


async def fetch_api_keys(secure_clob: AsyncTransport) -> tuple[str, ...]:
    payload = await secure_clob.get_json("/auth/api-keys")
    return parse_api_keys_response(payload)


async def get_rate_limit_tier(secure_clob: AsyncTransport) -> RateLimitTier:
    payload = await secure_clob.get_json(_RATE_LIMIT_TIER_PATH)
    return RateLimitTier.parse_response(payload)


async def delete_api_key(secure_clob: AsyncTransport) -> None:
    payload = await secure_clob.delete_json("/auth/api-key")
    if payload != "OK":
        raise UnexpectedResponseError(
            f"delete api key response did not match expected shape: {payload!r}"
        )


async def create_builder_api_key(secure_clob: AsyncTransport) -> BuilderApiKey:
    payload = await secure_clob.post_json(_BUILDER_API_KEY_PATH)
    return parse_builder_api_key_creds(payload)


async def fetch_builder_api_keys(secure_clob: AsyncTransport) -> tuple[BuilderApiKeyInfo, ...]:
    payload = await secure_clob.get_json(_BUILDER_API_KEY_PATH)
    return parse_builder_api_keys_response(payload)


async def revoke_builder_api_key(clob: AsyncTransport, builder_key: BuilderApiKey) -> None:
    headers = build_builder_key_headers(
        creds=builder_key, method="DELETE", path=_BUILDER_API_KEY_PATH
    )
    payload = await clob.delete_json(_BUILDER_API_KEY_PATH, headers=headers)
    if payload != "OK":
        raise UnexpectedResponseError(
            f"revoke builder api key response did not match expected shape: {payload!r}"
        )


def create_api_key_sync(clob: SyncTransport, signature: ApiKeyAuthSignature) -> ApiKeyCreds:
    payload = clob.post_json("/auth/api-key", headers=build_l1_auth_headers(signature))
    return parse_api_key_creds(payload)


def derive_api_key_sync(clob: SyncTransport, signature: ApiKeyAuthSignature) -> ApiKeyCreds:
    payload = clob.get_json("/auth/derive-api-key", headers=build_l1_auth_headers(signature))
    return parse_api_key_creds(payload)


def create_or_derive_api_key_sync(
    clob: SyncTransport, signature: ApiKeyAuthSignature
) -> ApiKeyCreds:
    try:
        return create_api_key_sync(clob, signature)
    except RequestRejectedError as error:
        if error.status != 400:
            raise
    return derive_api_key_sync(clob, signature)


def fetch_api_keys_sync(secure_clob: SyncTransport) -> tuple[str, ...]:
    payload = secure_clob.get_json("/auth/api-keys")
    return parse_api_keys_response(payload)


def get_rate_limit_tier_sync(secure_clob: SyncTransport) -> RateLimitTier:
    payload = secure_clob.get_json(_RATE_LIMIT_TIER_PATH)
    return RateLimitTier.parse_response(payload)


def delete_api_key_sync(secure_clob: SyncTransport) -> None:
    payload = secure_clob.delete_json("/auth/api-key")
    if payload != "OK":
        raise UnexpectedResponseError(
            f"delete api key response did not match expected shape: {payload!r}"
        )


def create_builder_api_key_sync(secure_clob: SyncTransport) -> BuilderApiKey:
    payload = secure_clob.post_json(_BUILDER_API_KEY_PATH)
    return parse_builder_api_key_creds(payload)


def fetch_builder_api_keys_sync(secure_clob: SyncTransport) -> tuple[BuilderApiKeyInfo, ...]:
    payload = secure_clob.get_json(_BUILDER_API_KEY_PATH)
    return parse_builder_api_keys_response(payload)


def revoke_builder_api_key_sync(clob: SyncTransport, builder_key: BuilderApiKey) -> None:
    headers = build_builder_key_headers(
        creds=builder_key, method="DELETE", path=_BUILDER_API_KEY_PATH
    )
    payload = clob.delete_json(_BUILDER_API_KEY_PATH, headers=headers)
    if payload != "OK":
        raise UnexpectedResponseError(
            f"revoke builder api key response did not match expected shape: {payload!r}"
        )


__all__ = [
    "get_rate_limit_tier",
    "get_rate_limit_tier_sync",
    "build_l1_auth_headers",
    "create_api_key",
    "create_api_key_sync",
    "create_builder_api_key",
    "create_builder_api_key_sync",
    "create_or_derive_api_key",
    "create_or_derive_api_key_sync",
    "delete_api_key",
    "delete_api_key_sync",
    "derive_api_key",
    "derive_api_key_sync",
    "fetch_api_keys",
    "fetch_api_keys_sync",
    "fetch_builder_api_keys",
    "fetch_builder_api_keys_sync",
    "parse_api_key_creds",
    "parse_api_keys_response",
    "parse_builder_api_key_creds",
    "parse_builder_api_keys_response",
    "revoke_builder_api_key",
    "revoke_builder_api_key_sync",
]
