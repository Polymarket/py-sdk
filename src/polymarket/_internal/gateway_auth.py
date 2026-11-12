"""Shared request construction for bearer authentication (no session ownership)."""

import base64
import binascii
import hashlib
import hmac
import json
import math
import time
from typing import Any, cast

from eth_account.signers.local import LocalAccount
from eth_utils.address import to_checksum_address

from polymarket.auth import BearerCredentials
from polymarket.errors import SigningError, UnexpectedResponseError, UserInputError
from polymarket.models import ApiKeyCreds


def token_claims(credentials: BearerCredentials) -> dict[str, Any]:
    # Unverified claims are scheduling/consistency hints only. The server validates JWTs.
    try:
        parts = credentials.access_token.split(".")
        if len(parts) != 3:
            raise ValueError
        payload = parts[1]
        value = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if not isinstance(value, dict):
            raise ValueError
        claims = cast(dict[str, Any], value)
        expiry = claims.get("exp")
        if isinstance(expiry, bool) or not isinstance(expiry, int | float):
            raise ValueError
        if not math.isfinite(expiry):
            raise ValueError
        return claims
    except (ValueError, TypeError, binascii.Error, UnicodeError):
        raise UserInputError("Access Token must be a JWT with a finite exp claim") from None


def _token_string(value: object) -> str:
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        raise UserInputError("Bearer credentials require non-empty token strings")
    return value


def parse_credentials(value: object) -> BearerCredentials | ApiKeyCreds:
    if isinstance(value, BearerCredentials | ApiKeyCreds):
        return value
    if isinstance(value, dict):
        data = cast(dict[str, object], value)
        if set(data) == {"access_token", "refresh_token"}:
            return BearerCredentials(
                access_token=_token_string(data["access_token"]),
                refresh_token=_token_string(data["refresh_token"]),
            )
        if set(data) == {"accessToken", "refreshToken"}:
            return BearerCredentials(
                access_token=_token_string(data["accessToken"]),
                refresh_token=_token_string(data["refreshToken"]),
            )
        if set(data) in (
            {"key", "secret", "passphrase"},
            {"apiKey", "secret", "passphrase"},
        ) and all(isinstance(v, str) and v for v in data.values()):
            return ApiKeyCreds.model_validate(data)
    raise UserInputError("credentials must contain a bearer token pair or legacy L2 credentials")


def parse_tokens(value: object) -> BearerCredentials:
    try:
        if not isinstance(value, dict):
            raise ValueError
        data = cast(dict[str, object], value)
        result = BearerCredentials(
            access_token=_token_string(data["accessToken"]),
            refresh_token=_token_string(data["refreshToken"]),
        )
        if data.get("tokenType") != "Bearer" or token_claims(result)["exp"] <= time.time():
            raise ValueError
        return result
    except (KeyError, ValueError, UserInputError):
        raise UnexpectedResponseError(
            "Authentication returned an invalid bearer token pair"
        ) from None


def build_challenge_request(
    *, signer: str, wallet: str | None = None, verification_token: object = None, nonce: object = 0
) -> dict[str, object]:
    try:
        body: dict[str, object] = {"signer": to_checksum_address(signer)}
        if wallet is not None:
            body["wallet"] = to_checksum_address(wallet)
    except (ValueError, TypeError):
        raise UserInputError("signer and wallet must be valid EVM addresses") from None
    if isinstance(nonce, bool) or not isinstance(nonce, int) or not 0 <= nonce <= 2**32 - 1:
        raise UserInputError("nonce must be an integer from 0 to 4294967295")
    if nonce:
        body["nonce"] = nonce
    if verification_token is not None:
        if not isinstance(verification_token, str) or not 1 <= len(verification_token) <= 2048:
            raise UserInputError("verification_token must contain 1 to 2048 characters")
        body["verification_token"] = verification_token
    return body


def build_login_request(signer: LocalAccount, challenge: object) -> dict[str, object]:
    if not isinstance(challenge, dict):
        raise UnexpectedResponseError("Authentication returned an invalid challenge")
    data = cast(dict[str, Any], challenge)
    if not isinstance(data.get("challengeId"), str) or not isinstance(data.get("typedData"), dict):
        raise UnexpectedResponseError("Authentication returned an invalid challenge")
    try:
        signature = signer.sign_typed_data(full_message=data["typedData"]).signature.hex()
    except Exception:
        raise SigningError("Could not sign the authentication challenge") from None
    return {
        "ownership": {
            "challenge_id": data["challengeId"],
            "signature": "0x" + signature.removeprefix("0x"),
        }
    }


def build_migration_request(
    *,
    credentials: ApiKeyCreds,
    signer: str,
    wallet: str | None = None,
    verification_token: str | None = None,
) -> dict[str, object]:
    body = build_challenge_request(
        signer=signer, wallet=wallet, verification_token=verification_token
    )
    timestamp = str(int(time.time()))
    try:
        secret = base64.b64decode(
            credentials.secret + "=" * (-len(credentials.secret) % 4), altchars=b"-_", validate=True
        )
        if not secret:
            raise ValueError
    except (ValueError, binascii.Error):
        raise UserInputError("Legacy L2 secret must be valid base64") from None
    body.update(
        timestamp=timestamp,
        clob_api_key=credentials.key,
        clob_passphrase=credentials.passphrase,
        clob_signature=base64.urlsafe_b64encode(
            hmac.new(secret, (timestamp + "GET/auth/api-keys").encode(), hashlib.sha256).digest()
        ).decode(),
    )
    return body


def owner_api_key(credentials: BearerCredentials | ApiKeyCreds) -> str:
    if isinstance(credentials, ApiKeyCreds):
        return credentials.key
    value = token_claims(credentials).get("clob_api_key")
    if not isinstance(value, str) or not value:
        raise UserInputError("This session has no trading API key identifier; log in again")
    return value


def login_sync(
    transport: Any,
    *,
    signer: LocalAccount,
    wallet: str | None = None,
    verification_token: str | None = None,
    nonce: int = 0,
) -> BearerCredentials:
    challenge = transport.post_json(
        "/v1/auth/challenge",
        json=build_challenge_request(
            signer=signer.address, wallet=wallet, verification_token=verification_token, nonce=nonce
        ),
    )
    return parse_tokens(
        transport.post_json("/v1/auth/login", json=build_login_request(signer, challenge))
    )


async def login_async(
    transport: Any,
    *,
    signer: LocalAccount,
    wallet: str | None = None,
    verification_token: str | None = None,
    nonce: int = 0,
) -> BearerCredentials:
    challenge = await transport.post_json(
        "/v1/auth/challenge",
        json=build_challenge_request(
            signer=signer.address, wallet=wallet, verification_token=verification_token, nonce=nonce
        ),
    )
    return parse_tokens(
        await transport.post_json("/v1/auth/login", json=build_login_request(signer, challenge))
    )
