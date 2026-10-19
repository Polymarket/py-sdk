"""Synthetic, unfunded authentication fixtures shared by protocol tests."""

import base64
import json
import time
from typing import Any

from eth_account import Account

from polymarket import BearerCredentials
from polymarket.models import ApiKeyCreds

GATEWAY = "https://api.defi.polymarket.com"
PRIVATE_KEY = "0x" + "01" * 32  # synthetic, unfunded test signer
SIGNER = Account.from_key(PRIVATE_KEY)
LEGACY = ApiKeyCreds(
    key="synthetic-key", secret="c3ludGhldGljLXNlY3JldA==", passphrase="synthetic-passphrase"
)
CHALLENGE: dict[str, Any] = {
    "challengeId": "00000000-0000-4000-8000-000000000001",
    "expiresAt": "2099-01-01T00:00:00Z",
    "typedData": {
        "types": {
            "EIP712Domain": [{"name": "name", "type": "string"}],
            "Challenge": [{"name": "signer", "type": "address"}],
        },
        "primaryType": "Challenge",
        "domain": {"name": "Synthetic authentication"},
        "message": {"signer": SIGNER.address},
    },
}


def credentials(
    *,
    expiry: float | None = None,
    refresh: str = "synthetic-refresh",
    tag: str = "one",
    **claims: object,
) -> BearerCredentials:
    payload = {
        "exp": expiry if expiry is not None else time.time() + 3600,
        "sub": SIGNER.address.lower(),
        "wallet": SIGNER.address.lower(),
        "signature_type": 0,
        "client_id": "synthetic-client",
        "clob_api_key": "synthetic-key",
        "jti": tag,
        **claims,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return BearerCredentials(
        access_token="eyJhbGciOiJSUzI1NiJ9." + encoded + ".synthetic-signature",
        refresh_token=refresh,
    )


def response(pair: BearerCredentials) -> dict[str, object]:
    return {
        "accessToken": pair.access_token,
        "refreshToken": pair.refresh_token,
        "tokenType": "Bearer",
        "expiresIn": 3600,
        "refreshExpiresIn": 86400,
    }
