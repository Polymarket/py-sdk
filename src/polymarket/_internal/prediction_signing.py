"""API-key headers for authenticated operations.

An API key adds headers only to the operations of its credential family:

- builder keys sign trading operations and builder RFQ writes;
- keys that support gasless transactions sign wallet operations;
- discovery, portfolio, and session requests carry no API-key headers.

The signature covers the operation's canonical method, path, and exact body,
which can differ from the request that is sent. The request itself is unchanged.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal, assert_never

from polymarket._internal.actions.relayer.auth import build_builder_key_headers
from polymarket.auth import ApiKey, BuilderApiKey, RelayerApiKey

_Family = Literal["trading", "builder-rfq", "wallet"]

_COLLATERAL_RETURN_SUBMIT_PATH = "/v1/collateral-return/submit"
# A collateral-return submission is authorized over the wallet envelope it carries.
_COLLATERAL_RETURN_ENVELOPE_PATH = "/submit"


@dataclass(frozen=True, slots=True)
class SignedOperation:
    method: str
    path: str
    body: str | None


@dataclass(frozen=True, slots=True)
class _Route:
    method: str
    pattern: re.Pattern[str]
    signing_method: str
    signing_path: str
    family: _Family


def _route(
    method: str,
    path: str,
    signing_path: str,
    family: _Family,
    *,
    signing_method: str | None = None,
) -> _Route:
    pattern = re.compile("^" + re.sub(r"\{[^}]+\}", "([^/]+)", path) + "$")
    return _Route(
        method=method,
        pattern=pattern,
        signing_method=signing_method or method,
        signing_path=signing_path,
        family=family,
    )


_ROUTES: tuple[_Route, ...] = (
    _route("GET", "/v1/me/trading-status", "/auth/ban-status/closed-only", "trading"),
    _route("GET", "/v1/me/orders", "/data/orders", "trading"),
    _route("GET", "/v1/me/wallet-orders", "/data/wallet-open-orders", "trading"),
    _route("GET", "/v1/me/orders/{order_id}", "/data/order/{order_id}", "trading"),
    _route("GET", "/v1/me/trades", "/data/trades", "trading"),
    _route("GET", "/v1/me/notifications", "/notifications", "trading"),
    _route("DELETE", "/v1/me/notifications", "/notifications", "trading"),
    _route("GET", "/v1/me/balance-allowances", "/balance-allowance", "trading"),
    _route(
        "POST",
        "/v1/me/balance-allowances/refresh",
        "/balance-allowance/update",
        "trading",
        signing_method="GET",
    ),
    _route("GET", "/v1/me/session-signers", "/v1/user/session-signers", "trading"),
    _route("GET", "/v1/orders/scoring", "/order-scoring", "trading"),
    _route("POST", "/v1/orders/scoring", "/orders-scoring", "trading"),
    _route("GET", "/v1/rewards/user", "/rewards/user", "trading"),
    _route("GET", "/v1/rewards/user/total", "/rewards/user/total", "trading"),
    _route("GET", "/v1/rewards/user/markets", "/rewards/user/markets", "trading"),
    _route("GET", "/v1/rewards/user/percentages", "/rewards/user/percentages", "trading"),
    _route("GET", "/v1/builders/trades", "/builder/trades", "trading"),
    _route("GET", "/v1/pricing/midpoint", "/midpoint", "trading"),
    _route("POST", "/v1/pricing/midpoints", "/midpoints", "trading"),
    _route("GET", "/v1/pricing/tick-size", "/tick-size", "trading"),
    _route("GET", "/v1/trading/neg-risk", "/neg-risk", "trading"),
    _route(
        "GET",
        "/v1/trading/markets/token/{token_id}",
        "/markets-by-token/{token_id}",
        "trading",
    ),
    _route(
        "GET",
        "/v1/trading/markets/{condition_id}",
        "/clob-markets/{condition_id}",
        "trading",
    ),
    _route("GET", "/v1/fees/builder/{code}", "/fees/builder-fees/{code}", "trading"),
    _route("GET", "/v1/pricing/price", "/price", "trading"),
    _route("POST", "/v1/pricing/prices", "/prices", "trading"),
    _route("GET", "/v1/pricing/book", "/book", "trading"),
    _route("POST", "/v1/pricing/books", "/books", "trading"),
    _route("GET", "/v1/pricing/spread", "/spread", "trading"),
    _route("POST", "/v1/pricing/spreads", "/spreads", "trading"),
    _route("GET", "/v1/pricing/last-trade-price", "/last-trade-price", "trading"),
    _route("POST", "/v1/pricing/last-trades-prices", "/last-trades-prices", "trading"),
    _route("GET", "/v1/rewards/markets/current", "/rewards/markets/current", "trading"),
    _route("GET", "/v1/rewards/markets/multi", "/rewards/markets/multi", "trading"),
    _route(
        "GET",
        "/v1/rewards/markets/{condition_id}",
        "/rewards/markets/{condition_id}",
        "trading",
    ),
    _route("GET", "/v1/rebates/current", "/rebates/current", "trading"),
    _route("POST", "/v1/orders", "/order", "trading"),
    _route("POST", "/v1/orders/batch", "/orders", "trading"),
    _route("DELETE", "/v1/orders", "/order", "trading"),
    _route("DELETE", "/v1/orders/batch", "/orders", "trading"),
    _route("DELETE", "/v1/orders/all", "/cancel-all", "trading"),
    _route("DELETE", "/v1/orders/by-market", "/cancel-market-orders", "trading"),
    _route("DELETE", "/v1/orders/by-wallet", "/cancel-wallet-orders", "trading"),
    _route("POST", "/v1/combos/builder/requests", "/v1/builder/rfq/requests", "builder-rfq"),
    _route(
        "POST",
        "/v1/combos/builder/requests/{rfq_id}/accept",
        "/v1/builder/rfq/requests/{rfq_id}/accept",
        "builder-rfq",
    ),
    _route(
        "GET",
        "/v1/combos/builder/requests/{rfq_id}",
        "/v1/builder/rfq/requests/{rfq_id}",
        "builder-rfq",
    ),
    _route(
        "POST",
        "/v1/wallets/session-signers/authorizations",
        "/v1/session-signers/authorizations",
        "wallet",
    ),
    _route(
        "POST",
        "/v1/wallets/session-signers/revocations",
        "/v1/session-signers/revocations",
        "wallet",
    ),
    _route(
        "POST",
        "/v1/wallets/collateral-return/plan",
        "/v1/collateral-return/plan",
        "wallet",
    ),
    _route(
        "POST",
        "/v1/wallets/collateral-return/submit",
        _COLLATERAL_RETURN_SUBMIT_PATH,
        "wallet",
    ),
    _route(
        "GET",
        "/v1/wallets/execute-params",
        "/v1/account/transactions/params",
        "wallet",
    ),
    _route("GET", "/v1/wallets/deployed", "/deployed", "wallet"),
    _route(
        "GET",
        "/v1/wallets/transactions/{transaction_id}",
        "/v1/account/transactions/{transaction_id}",
        "wallet",
    ),
    _route("POST", "/v1/wallets/transactions", "/submit", "wallet"),
)


def build_signed_operation(
    api_key: ApiKey, *, method: str, path: str, body: str | None
) -> SignedOperation | None:
    """Return the operation ``api_key`` signs for a request, or ``None`` when it signs nothing.

    ``path`` is the request path without its query string; queries are never signed.
    Path segments are signed exactly as they are sent, including their encoding.
    """
    for route in _ROUTES:
        if route.method != method:
            continue
        match = route.pattern.match(path)
        if match is None:
            continue
        if not _signs(api_key, route.family, method):
            return None
        signing_path = _fill_path(route.signing_path, match.groups())
        if signing_path == _COLLATERAL_RETURN_SUBMIT_PATH:
            envelope = json.loads(body or "{}").get("envelope")
            return SignedOperation(
                method=route.signing_method,
                path=_COLLATERAL_RETURN_ENVELOPE_PATH,
                body=json.dumps(envelope, separators=(",", ":")),
            )
        return SignedOperation(method=route.signing_method, path=signing_path, body=body)
    return None


def build_api_key_headers(
    api_key: ApiKey, *, method: str, path: str, body: str | None
) -> dict[str, str]:
    """Build the API-key headers for a request, empty when the key does not sign it."""
    operation = build_signed_operation(api_key, method=method, path=path, body=body)
    if operation is None:
        return {}
    if isinstance(api_key, BuilderApiKey):
        return build_builder_key_headers(
            creds=api_key, method=operation.method, path=operation.path, body=operation.body
        )
    if isinstance(api_key, RelayerApiKey):  # pyright: ignore[reportUnnecessaryIsInstance]
        return {"RELAYER_API_KEY": api_key.key, "RELAYER_API_KEY_ADDRESS": str(api_key.address)}
    assert_never(api_key)


def _fill_path(template: str, segments: tuple[str, ...]) -> str:
    remaining = iter(segments)
    return re.sub(r"\{[^}]+\}", lambda _: next(remaining), template)


def _signs(api_key: ApiKey, family: _Family, method: str) -> bool:
    is_builder_key = isinstance(api_key, BuilderApiKey)
    match family:
        case "trading":
            return is_builder_key
        case "builder-rfq":
            return is_builder_key and method != "GET"
        case "wallet":
            # Builder and relayer keys both authorize gasless wallet operations.
            return True
        case _ as unreachable:
            assert_never(unreachable)


__all__ = ["SignedOperation", "build_api_key_headers", "build_signed_operation"]
