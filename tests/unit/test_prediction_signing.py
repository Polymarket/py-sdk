import json

import pytest

from polymarket._internal.hmac import build_hmac_signature
from polymarket._internal.prediction_signing import build_api_key_headers
from polymarket.auth import BuilderApiKey, RelayerApiKey

BUILDER = BuilderApiKey(key="builder-key", secret="c2VjcmV0", passphrase="passphrase")
RELAYER = RelayerApiKey(key="relayer-key", address="0x00000000000000000000000000000000000000aa")


def _signed_by_builder(
    headers: dict[str, str], *, method: str, path: str, body: str | None
) -> bool:
    expected = build_hmac_signature(
        secret=BUILDER.secret,
        timestamp=int(headers["POLY_BUILDER_TIMESTAMP"]),
        method=method,
        path=path,
        body=body,
    )
    return headers["POLY_BUILDER_SIGNATURE"] == expected


@pytest.mark.parametrize(
    ("method", "path", "signed_method", "signed_path"),
    [
        ("POST", "/v1/orders", "POST", "/order"),
        ("DELETE", "/v1/orders/by-wallet", "DELETE", "/cancel-wallet-orders"),
        ("GET", "/v1/me/orders/0xabc%2F1", "GET", "/data/order/0xabc%2F1"),
        # The refresh is sent as a POST but authorized as the original read.
        ("POST", "/v1/me/balance-allowances/refresh", "GET", "/balance-allowance/update"),
        (
            "POST",
            "/v1/combos/builder/requests/rfq-1/accept",
            "POST",
            "/v1/builder/rfq/requests/rfq-1/accept",
        ),
    ],
)
def test_builder_key_signs_the_canonical_operation(
    method: str, path: str, signed_method: str, signed_path: str
) -> None:
    body = '{"orderID":"1"}'

    headers = build_api_key_headers(BUILDER, method=method, path=path, body=body)

    assert headers["POLY_BUILDER_API_KEY"] == "builder-key"
    assert _signed_by_builder(headers, method=signed_method, path=signed_path, body=body)


@pytest.mark.parametrize(
    ("api_key", "method", "path"),
    [
        (BUILDER, "GET", "/v1/markets"),
        (BUILDER, "GET", "/v1/positions"),
        (BUILDER, "GET", "/v1/comments"),
        (BUILDER, "POST", "/v1/auth/login"),
        # Builder RFQ status reads authenticate with the session only.
        (BUILDER, "GET", "/v1/combos/builder/requests/rfq-1"),
        # Relayer keys authorize wallet operations only.
        (RELAYER, "POST", "/v1/orders"),
        (RELAYER, "POST", "/v1/combos/builder/requests"),
    ],
)
def test_key_adds_nothing_outside_its_credential_family(
    api_key: BuilderApiKey | RelayerApiKey, method: str, path: str
) -> None:
    assert build_api_key_headers(api_key, method=method, path=path, body=None) == {}


def test_relayer_key_authorizes_wallet_operations() -> None:
    headers = build_api_key_headers(
        RELAYER, method="POST", path="/v1/wallets/transactions", body="{}"
    )

    assert headers == {
        "RELAYER_API_KEY": "relayer-key",
        "RELAYER_API_KEY_ADDRESS": str(RELAYER.address),
    }


def test_collateral_return_submission_is_authorized_over_its_envelope() -> None:
    envelope = {"from": "0x1", "data": "0x2", "nonce": "3"}
    body = json.dumps({"plan_hash": "0xhash", "envelope": envelope}, separators=(",", ":"))

    headers = build_api_key_headers(
        BUILDER, method="POST", path="/v1/wallets/collateral-return/submit", body=body
    )

    assert _signed_by_builder(
        headers,
        method="POST",
        path="/submit",
        body='{"from":"0x1","data":"0x2","nonce":"3"}',
    )
