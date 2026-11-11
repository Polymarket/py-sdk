from __future__ import annotations

import time

from polymarket._internal.hmac import build_hmac_signature
from polymarket.auth import BuilderApiKey


# Single source of truth for builder-key (POLY_BUILDER_*) auth-header construction, so the HMAC
# signing never drifts between copies. Keep all builder-key header building here.
def build_builder_key_headers(
    *, creds: BuilderApiKey, method: str, path: str, body: str | None = None
) -> dict[str, str]:
    """Build the ``POLY_BUILDER_*`` headers that authenticate a request as a builder key.

    Signs ``timestamp + method + path (+ body)`` with the builder key's secret.
    """
    timestamp = int(time.time())
    signature = build_hmac_signature(
        secret=creds.secret,
        timestamp=timestamp,
        method=method,
        path=path,
        body=body,
    )
    return {
        "POLY_BUILDER_API_KEY": creds.key,
        "POLY_BUILDER_PASSPHRASE": creds.passphrase,
        "POLY_BUILDER_SIGNATURE": signature,
        "POLY_BUILDER_TIMESTAMP": str(timestamp),
    }


__all__ = ["build_builder_key_headers"]
