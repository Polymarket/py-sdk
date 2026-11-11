"""Request construction and response parsing for session authentication."""

from __future__ import annotations

import base64
import binascii
import json
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_utils.address import is_hex_address, to_checksum_address

from polymarket._internal.hmac import build_hmac_signature
from polymarket.auth import BearerCredentials, PlatformApiKey
from polymarket.clients._transport import (
    AsyncTransport,
    HeaderResolver,
    SyncHeaderResolver,
    SyncTransport,
)
from polymarket.errors import SigningError, UnexpectedResponseError, UserInputError
from polymarket.models.clob import ApiKeyCreds
from polymarket.types import EvmAddress

AUTH_PATH_PREFIX = "/v1/auth/"
CHALLENGE_PATH = "/v1/auth/challenge"
LOGIN_PATH = "/v1/auth/login"
MIGRATE_PATH = "/v1/auth/migrate"
REFRESH_PATH = "/v1/auth/refresh"
UPGRADE_PATH = "/v1/auth/upgrade"
LOGOUT_PATH = "/v1/auth/logout"

# Saved L2 credentials prove ownership with an HMAC over this canonical request.
# The migration does not dispatch a request to this path.
_MIGRATION_PROOF_METHOD = "GET"
_MIGRATION_PROOF_PATH = "/auth/api-keys"

_CLOB_AUTH_ATTESTATION = "This message attests that I control the given wallet"
_EIP712_DOMAIN_FIELDS = (
    {"name": "name", "type": "string"},
    {"name": "version", "type": "string"},
    {"name": "chainId", "type": "uint256"},
)
_CLOB_AUTH_FIELDS = (
    {"name": "address", "type": "address"},
    {"name": "timestamp", "type": "string"},
    {"name": "nonce", "type": "uint256"},
    {"name": "message", "type": "string"},
)
_MAX_NONCE = 2**32 - 1
_MAX_VERIFICATION_TOKEN_LENGTH = 2048
# Session renewal and logout use session credentials only.
_SESSION_ONLY_PATHS = frozenset({REFRESH_PATH, LOGOUT_PATH})


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    """A token pair and the access token's lifetime in seconds when it was issued."""

    access_token: str
    refresh_token: str
    expires_in: int

    @property
    def credentials(self) -> BearerCredentials:
        return BearerCredentials(access_token=self.access_token, refresh_token=self.refresh_token)


@dataclass(frozen=True, slots=True)
class AccessTokenGrant:
    """A new access token for an existing session; the refresh token does not change."""

    access_token: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    """Unverified access-token claims, used only for scheduling and identity continuity."""

    exp: int
    sub: EvmAddress
    client_id: str | None
    wallet: EvmAddress | None
    signature_type: int | None
    clob_api_key: str | None


@dataclass(frozen=True, slots=True)
class OwnershipChallenge:
    """A validated ownership challenge, ready to sign."""

    challenge_id: str
    chain_id: int
    address: str
    typed_data: Mapping[str, Any]


def signer_from_private_key(private_key: str) -> LocalAccount:
    if not private_key:
        raise UserInputError("private_key is required")
    try:
        return cast(LocalAccount, Account.from_key(private_key))
    except (ValueError, TypeError) as error:
        raise UserInputError(f"Invalid private_key: {error}") from error


def checksum_wallet(wallet: str) -> EvmAddress:
    try:
        return EvmAddress(to_checksum_address(wallet))
    except (ValueError, TypeError) as error:
        raise UserInputError(f"Invalid wallet address: {error}") from error


def checksum_signer(signer: str) -> EvmAddress:
    try:
        return EvmAddress(to_checksum_address(signer))
    except (ValueError, TypeError) as error:
        raise UserInputError(f"Invalid signer address: {error}") from error


def build_challenge_request(
    *, signer: str, wallet: str | None, nonce: int, verification_token: str | None = None
) -> dict[str, object]:
    if not _is_int(nonce) or not 0 <= nonce <= _MAX_NONCE:
        raise UserInputError(f"nonce must be an integer between 0 and {_MAX_NONCE}")
    body: dict[str, object] = {"signer": signer}
    if wallet is not None:
        body["wallet"] = wallet
    if nonce != 0:
        body["nonce"] = nonce
    if verification_token is not None:
        if (
            not isinstance(verification_token, str)  # pyright: ignore[reportUnnecessaryIsInstance]
            or not 0 < len(verification_token) <= _MAX_VERIFICATION_TOKEN_LENGTH
        ):
            raise UserInputError(
                f"verification_token must be 1 to {_MAX_VERIFICATION_TOKEN_LENGTH} characters"
            )
        body["verification_token"] = verification_token
    return body


def build_platform_api_key_headers(
    platform_api_key: PlatformApiKey | None, *, path: str
) -> dict[str, str]:
    """Headers that attribute a request to the application's Platform API Key."""
    if platform_api_key is None or path in _SESSION_ONLY_PATHS:
        return {}
    return {"X-API-Key": platform_api_key.key}


def make_platform_header_resolver_sync(platform_api_key: PlatformApiKey) -> SyncHeaderResolver:
    def resolver(method: str, path: str, body: str | None) -> dict[str, str]:
        return build_platform_api_key_headers(platform_api_key, path=path)

    return resolver


def make_platform_header_resolver(platform_api_key: PlatformApiKey) -> HeaderResolver:
    async def resolver(method: str, path: str, body: str | None) -> dict[str, str]:
        return build_platform_api_key_headers(platform_api_key, path=path)

    return resolver


def parse_ownership_challenge(data: object) -> OwnershipChallenge:
    """Validate that ``data`` is the ``ClobAuth`` ownership attestation and nothing else.

    Unknown domain, type and message fields are rejected rather than ignored,
    because ignoring them would sign a payload other than the one validated.
    """
    invalid = UnexpectedResponseError(
        "The ownership challenge is not a valid ClobAuth attestation."
    )
    root = _as_object(data, invalid)
    challenge_id = root.get("challengeId")
    expires_at = root.get("expiresAt")
    typed_data = _as_object(root.get("typedData"), invalid)
    if not isinstance(challenge_id, str) or not _is_uuid(challenge_id):
        raise invalid
    if not isinstance(expires_at, str) or not _is_iso_datetime(expires_at):
        raise invalid

    domain = _as_object(typed_data.get("domain"), invalid)
    types = _as_object(typed_data.get("types"), invalid)
    message = _as_object(typed_data.get("message"), invalid)
    chain_id = domain.get("chainId")
    if (
        set(domain) != {"name", "version", "chainId"}
        or domain.get("name") != "ClobAuthDomain"
        or domain.get("version") != "1"
        or not _is_positive_int(chain_id)
        or set(types) != {"EIP712Domain", "ClobAuth"}
        or not _fields_match(types.get("EIP712Domain"), _EIP712_DOMAIN_FIELDS)
        or not _fields_match(types.get("ClobAuth"), _CLOB_AUTH_FIELDS)
        or typed_data.get("primaryType") != "ClobAuth"
        or set(message) != {"address", "timestamp", "nonce", "message"}
        or message.get("message") != _CLOB_AUTH_ATTESTATION
    ):
        raise invalid
    address = message.get("address")
    timestamp = message.get("timestamp")
    nonce = message.get("nonce")
    if (
        not isinstance(address, str)
        or not is_hex_address(address)
        or not _is_decimal_string(timestamp)
        or not _is_decimal_string(nonce)
    ):
        raise invalid

    return OwnershipChallenge(
        challenge_id=challenge_id,
        chain_id=cast(int, chain_id),
        address=address,
        typed_data={
            "domain": {"name": "ClobAuthDomain", "version": "1", "chainId": chain_id},
            "types": {
                "EIP712Domain": [dict(field) for field in _EIP712_DOMAIN_FIELDS],
                "ClobAuth": [dict(field) for field in _CLOB_AUTH_FIELDS],
            },
            "primaryType": "ClobAuth",
            "message": {
                "address": address,
                "timestamp": timestamp,
                "nonce": int(cast(str, nonce)),
                "message": _CLOB_AUTH_ATTESTATION,
            },
        },
    )


def sign_ownership_challenge(
    signer: LocalAccount, challenge: OwnershipChallenge, *, chain_id: int
) -> str:
    """Sign ``challenge`` after checking it attests this signer on this network."""
    if challenge.chain_id != chain_id or challenge.address.lower() != signer.address.lower():
        raise UnexpectedResponseError(
            "The ownership challenge does not match the signer and network."
        )
    try:
        signed = signer.sign_typed_data(full_message=dict(challenge.typed_data))
    except Exception as error:
        raise SigningError("Could not sign the ownership challenge.") from error
    return "0x" + signed.signature.hex()


def build_login_request(*, challenge_id: str, signature: str) -> dict[str, object]:
    return {"ownership": {"challenge_id": challenge_id, "signature": signature}}


def build_migrate_request(
    *, credentials: ApiKeyCreds, signer: str, wallet: str | None, timestamp: int
) -> dict[str, object]:
    """Build the exchange of saved L2 credentials; the L2 secret never leaves the SDK."""
    try:
        proof = build_hmac_signature(
            secret=credentials.secret,
            timestamp=timestamp,
            method=_MIGRATION_PROOF_METHOD,
            path=_MIGRATION_PROOF_PATH,
        )
    except SigningError as error:
        raise SigningError("Could not prove ownership of the saved credentials.") from error
    body: dict[str, object] = {
        "signer": signer,
        "timestamp": str(timestamp),
        "clob_api_key": credentials.key,
        "clob_passphrase": credentials.passphrase,
        "clob_signature": proof,
    }
    if wallet is not None:
        body["wallet"] = wallet
    return body


def build_refresh_request(credentials: BearerCredentials) -> dict[str, object]:
    return {"refresh_token": credentials.refresh_token}


def build_upgrade_request(wallet: str) -> dict[str, object]:
    return {"wallet": wallet}


def build_bearer_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def parse_issued_tokens(data: object) -> IssuedTokens:
    invalid = UnexpectedResponseError("The session token response is malformed.")
    payload = _as_object(data, invalid)
    access_token = payload.get("accessToken")
    refresh_token = payload.get("refreshToken")
    expires_in = payload.get("expiresIn")
    refresh_expires_in = payload.get("refreshExpiresIn")
    if (
        not _is_nonempty_str(access_token)
        or not _is_nonempty_str(refresh_token)
        or payload.get("tokenType") != "Bearer"
        or not _is_positive_int(expires_in)
        or not (_is_int(refresh_expires_in) and cast(int, refresh_expires_in) >= 0)
    ):
        raise invalid
    return IssuedTokens(
        access_token=cast(str, access_token),
        refresh_token=cast(str, refresh_token),
        expires_in=cast(int, expires_in),
    )


def parse_access_token_grant(data: object) -> AccessTokenGrant:
    invalid = UnexpectedResponseError("The session upgrade response is malformed.")
    payload = _as_object(data, invalid)
    access_token = payload.get("accessToken")
    expires_in = payload.get("expiresIn")
    if (
        not _is_nonempty_str(access_token)
        or payload.get("tokenType") != "Bearer"
        or not _is_positive_int(expires_in)
    ):
        raise invalid
    return AccessTokenGrant(access_token=cast(str, access_token), expires_in=cast(int, expires_in))


def parse_access_token_claims(access_token: str) -> AccessTokenClaims:
    """Decode claims from an access token supplied by the caller."""
    claims = _decode_claims(access_token)
    if claims is None:
        raise UserInputError("The access token has invalid session metadata.")
    return claims


def parse_issued_claims(access_token: str) -> AccessTokenClaims:
    """Decode claims from an access token issued by the server."""
    claims = _decode_claims(access_token)
    if claims is None:
        raise UnexpectedResponseError(
            "The server issued an access token with invalid session metadata."
        )
    return claims


def same_session_identity(a: AccessTokenClaims, b: AccessTokenClaims) -> bool:
    return (
        a.sub.lower() == b.sub.lower()
        and a.client_id == b.client_id
        and _lower(a.wallet) == _lower(b.wallet)
        and a.signature_type == b.signature_type
        and a.clob_api_key == b.clob_api_key
    )


def trading_identity(claims: AccessTokenClaims) -> str:
    """Return the order owner for a session."""
    if not claims.clob_api_key:
        raise UserInputError("This session has no trading identity. Sign in again to place orders.")
    return claims.clob_api_key


def issued_for(tokens: IssuedTokens, *, signer: str, wallet: str | None) -> bool:
    """Whether a login or migration issued a session for the requested signer and wallet.

    Without a requested wallet, only the signer is checked.
    """
    claims = _decode_claims(tokens.access_token)
    if claims is None or claims.sub.lower() != signer.lower():
        return False
    return wallet is None or (claims.wallet is not None and claims.wallet.lower() == wallet.lower())


def issue_login_session_sync(
    auth: SyncTransport,
    *,
    signer: LocalAccount,
    chain_id: int,
    wallet: str | None,
    nonce: int,
) -> IssuedTokens:
    """Sign the server's ownership challenge for ``signer`` and open a session."""
    challenge = parse_ownership_challenge(
        auth.post_json(
            CHALLENGE_PATH,
            json=build_challenge_request(signer=signer.address, wallet=wallet, nonce=nonce),
        )
    )
    signature = sign_ownership_challenge(signer, challenge, chain_id=chain_id)
    return parse_issued_tokens(
        auth.post_json(
            LOGIN_PATH,
            json=build_login_request(challenge_id=challenge.challenge_id, signature=signature),
        )
    )


async def issue_login_session(
    auth: AsyncTransport,
    *,
    signer: LocalAccount,
    chain_id: int,
    wallet: str | None,
    nonce: int,
) -> IssuedTokens:
    """Sign the server's ownership challenge for ``signer`` and open a session."""
    challenge = parse_ownership_challenge(
        await auth.post_json(
            CHALLENGE_PATH,
            json=build_challenge_request(signer=signer.address, wallet=wallet, nonce=nonce),
        )
    )
    signature = sign_ownership_challenge(signer, challenge, chain_id=chain_id)
    return parse_issued_tokens(
        await auth.post_json(
            LOGIN_PATH,
            json=build_login_request(challenge_id=challenge.challenge_id, signature=signature),
        )
    )


def issue_migrated_session_sync(
    auth: SyncTransport, *, credentials: ApiKeyCreds, signer: str, wallet: str | None
) -> IssuedTokens:
    """Exchange saved L2 credentials for a session without a wallet signature."""
    body = build_migrate_request(
        credentials=credentials, signer=signer, wallet=wallet, timestamp=int(time.time())
    )
    return parse_issued_tokens(auth.post_json(MIGRATE_PATH, json=body))


async def issue_migrated_session(
    auth: AsyncTransport, *, credentials: ApiKeyCreds, signer: str, wallet: str | None
) -> IssuedTokens:
    """Exchange saved L2 credentials for a session without a wallet signature."""
    body = build_migrate_request(
        credentials=credentials, signer=signer, wallet=wallet, timestamp=int(time.time())
    )
    return parse_issued_tokens(await auth.post_json(MIGRATE_PATH, json=body))


def refresh_session_sync(auth: SyncTransport, credentials: BearerCredentials) -> IssuedTokens:
    return parse_issued_tokens(
        auth.post_json(
            REFRESH_PATH,
            json=build_refresh_request(credentials),
            headers=build_bearer_headers(credentials.access_token),
        )
    )


async def refresh_session(auth: AsyncTransport, credentials: BearerCredentials) -> IssuedTokens:
    return parse_issued_tokens(
        await auth.post_json(
            REFRESH_PATH,
            json=build_refresh_request(credentials),
            headers=build_bearer_headers(credentials.access_token),
        )
    )


def upgrade_session_sync(
    auth: SyncTransport, *, access_token: str, wallet: str
) -> AccessTokenGrant:
    return parse_access_token_grant(
        auth.post_json(
            UPGRADE_PATH,
            json=build_upgrade_request(wallet),
            headers=build_bearer_headers(access_token),
        )
    )


async def upgrade_session(
    auth: AsyncTransport, *, access_token: str, wallet: str
) -> AccessTokenGrant:
    return parse_access_token_grant(
        await auth.post_json(
            UPGRADE_PATH,
            json=build_upgrade_request(wallet),
            headers=build_bearer_headers(access_token),
        )
    )


def revoke_session_sync(auth: SyncTransport, access_token: str) -> None:
    auth.post(LOGOUT_PATH, headers=build_bearer_headers(access_token))


async def revoke_session(auth: AsyncTransport, access_token: str) -> None:
    await auth.post(LOGOUT_PATH, headers=build_bearer_headers(access_token))


def request_platform_challenge_sync(
    auth: SyncTransport,
    *,
    signer: str,
    wallet: str | None,
    nonce: int,
    verification_token: str | None,
) -> dict[str, Any]:
    """Request an ownership challenge and return it exactly as issued."""
    body = build_challenge_request(
        signer=signer, wallet=wallet, nonce=nonce, verification_token=verification_token
    )
    challenge = auth.post_json(CHALLENGE_PATH, json=body)
    parse_ownership_challenge(challenge)
    return cast(dict[str, Any], challenge)


async def request_platform_challenge(
    auth: AsyncTransport,
    *,
    signer: str,
    wallet: str | None,
    nonce: int,
    verification_token: str | None,
) -> dict[str, Any]:
    """Request an ownership challenge and return it exactly as issued."""
    body = build_challenge_request(
        signer=signer, wallet=wallet, nonce=nonce, verification_token=verification_token
    )
    challenge = await auth.post_json(CHALLENGE_PATH, json=body)
    parse_ownership_challenge(challenge)
    return cast(dict[str, Any], challenge)


def _decode_claims(access_token: str) -> AccessTokenClaims | None:
    parts = access_token.split(".")
    if len(parts) < 2:
        return None
    segment = parts[1]
    try:
        raw = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
        payload = json.loads(raw)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    claims = cast(dict[str, object], payload)
    exp = claims.get("exp")
    sub = _parse_address(claims.get("sub"))
    wallet_claim = claims.get("wallet")
    wallet = _parse_address(wallet_claim)
    client_id = claims.get("client_id")
    signature_type = claims.get("signature_type")
    clob_api_key = claims.get("clob_api_key")
    if (
        not _is_positive_int(exp)
        or sub is None
        or (wallet_claim is not None and wallet is None)
        or (client_id is not None and not isinstance(client_id, str))
        or (
            signature_type is not None
            and not (_is_int(signature_type) and 0 <= cast(int, signature_type) <= 3)
        )
        or (clob_api_key is not None and not isinstance(clob_api_key, str))
    ):
        return None
    return AccessTokenClaims(
        exp=cast(int, exp),
        sub=sub,
        client_id=client_id,
        wallet=wallet,
        signature_type=cast(int | None, signature_type),
        clob_api_key=clob_api_key,
    )


def _parse_address(value: object) -> EvmAddress | None:
    if not isinstance(value, str) or not is_hex_address(value):
        return None
    return EvmAddress(to_checksum_address(value))


def _as_object(value: object, error: Exception) -> dict[str, object]:
    if not isinstance(value, dict):
        raise error
    return cast(dict[str, object], value)


def _fields_match(value: object, expected: tuple[dict[str, str], ...]) -> bool:
    return isinstance(value, list) and value == [dict(field) for field in expected]


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_positive_int(value: object) -> bool:
    return _is_int(value) and cast(int, value) > 0


def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and value != ""


def _is_decimal_string(value: object) -> bool:
    return isinstance(value, str) and value.isascii() and value.isdigit()


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _is_iso_datetime(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _lower(value: str | None) -> str | None:
    return None if value is None else value.lower()


__all__ = [
    "AUTH_PATH_PREFIX",
    "CHALLENGE_PATH",
    "LOGIN_PATH",
    "LOGOUT_PATH",
    "MIGRATE_PATH",
    "REFRESH_PATH",
    "UPGRADE_PATH",
    "_MIGRATION_PROOF_PATH",
    "AccessTokenClaims",
    "AccessTokenGrant",
    "IssuedTokens",
    "OwnershipChallenge",
    "build_bearer_headers",
    "build_challenge_request",
    "build_login_request",
    "build_migrate_request",
    "build_platform_api_key_headers",
    "build_refresh_request",
    "build_upgrade_request",
    "checksum_wallet",
    "issue_login_session",
    "issue_login_session_sync",
    "issue_migrated_session",
    "issue_migrated_session_sync",
    "issued_for",
    "make_platform_header_resolver",
    "make_platform_header_resolver_sync",
    "parse_access_token_claims",
    "parse_access_token_grant",
    "parse_issued_claims",
    "parse_issued_tokens",
    "parse_ownership_challenge",
    "refresh_session",
    "refresh_session_sync",
    "request_platform_challenge",
    "request_platform_challenge_sync",
    "revoke_session",
    "revoke_session_sync",
    "same_session_identity",
    "sign_ownership_challenge",
    "signer_from_private_key",
    "trading_identity",
    "upgrade_session",
    "upgrade_session_sync",
]
