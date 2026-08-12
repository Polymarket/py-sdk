# pyright: reportPrivateUsage=false
import asyncio
from typing import Any, cast

import pytest
from eth_account import Account
from eth_account.signers.local import LocalAccount

from polymarket import ApiKeyCreds
from polymarket._internal.environment import PRODUCTION_CONFIG
from polymarket._internal.l1_auth import ApiKeyAuthSignature
from polymarket.clients import async_secure as _module
from polymarket.clients._transport import AsyncTransport
from polymarket.errors import RequestRejectedError

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
PROVIDED = ApiKeyCreds(key="provided-key", passphrase="p", secret="dGVzdA==")
FRESH = ApiKeyCreds(key="fresh-key", passphrase="p2", secret="ZnJlc2g=")


def _signer() -> LocalAccount:
    return cast(LocalAccount, Account.from_key(PRIVATE_KEY))


def _clob() -> AsyncTransport:
    return AsyncTransport(base_url="https://clob.test")


def test_bootstrap_returns_provided_credentials_when_validation_disabled() -> None:
    async def run() -> ApiKeyCreds:
        return await _module._bootstrap_credentials(
            config=PRODUCTION_CONFIG,
            signer=_signer(),
            clob=_clob(),
            provided=PROVIDED,
            nonce=0,
            validate=False,
            logger=None,
        )

    assert asyncio.run(run()) is PROVIDED


def test_bootstrap_returns_provided_when_validation_confirms_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def mock_active(**_kwargs: Any) -> bool:
        return True

    async def explode(*_args: Any, **_kwargs: Any) -> ApiKeyCreds:
        raise AssertionError("L1 fallback should not run when creds are active")

    monkeypatch.setattr(_module, "_credentials_are_active", mock_active)
    monkeypatch.setattr(_module._auth_actions, "create_or_derive_api_key", explode)

    async def run() -> ApiKeyCreds:
        return await _module._bootstrap_credentials(
            config=PRODUCTION_CONFIG,
            signer=_signer(),
            clob=_clob(),
            provided=PROVIDED,
            nonce=0,
            validate=True,
            logger=None,
        )

    assert asyncio.run(run()) is PROVIDED


def test_bootstrap_falls_back_to_l1_when_provided_creds_are_inactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def mock_inactive(**_kwargs: Any) -> bool:
        return False

    async def mock_fresh(_clob: AsyncTransport, _sig: ApiKeyAuthSignature) -> ApiKeyCreds:
        return FRESH

    monkeypatch.setattr(_module, "_credentials_are_active", mock_inactive)
    monkeypatch.setattr(_module._auth_actions, "create_or_derive_api_key", mock_fresh)

    async def run() -> ApiKeyCreds:
        return await _module._bootstrap_credentials(
            config=PRODUCTION_CONFIG,
            signer=_signer(),
            clob=_clob(),
            provided=PROVIDED,
            nonce=0,
            validate=True,
            logger=None,
        )

    assert asyncio.run(run()) is FRESH


def test_bootstrap_does_fresh_l1_when_no_credentials_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_signatures: list[ApiKeyAuthSignature] = []

    async def mock_fresh(_clob: AsyncTransport, sig: ApiKeyAuthSignature) -> ApiKeyCreds:
        seen_signatures.append(sig)
        return FRESH

    async def never_called(**_kwargs: Any) -> bool:
        raise AssertionError("validation should not run when no creds provided")

    monkeypatch.setattr(_module._auth_actions, "create_or_derive_api_key", mock_fresh)
    monkeypatch.setattr(_module, "_credentials_are_active", never_called)

    async def run() -> ApiKeyCreds:
        return await _module._bootstrap_credentials(
            config=PRODUCTION_CONFIG,
            signer=_signer(),
            clob=_clob(),
            provided=None,
            nonce=7,
            validate=True,
            logger=None,
        )

    result = asyncio.run(run())

    assert result is FRESH
    assert len(seen_signatures) == 1
    assert seen_signatures[0].nonce == 7


def test_credentials_are_active_returns_false_on_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def raise_401(_transport: AsyncTransport) -> tuple[str, ...]:
        raise RequestRejectedError("unauthorized", status=401)

    monkeypatch.setattr(_module._auth_actions, "fetch_api_keys", raise_401)

    async def run() -> bool:
        return await _module._credentials_are_active(
            config=PRODUCTION_CONFIG,
            signer=_signer(),
            credentials=PROVIDED,
            logger=None,
        )

    assert asyncio.run(run()) is False


def test_credentials_are_active_returns_false_when_key_not_listed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def returns_other_keys(_transport: AsyncTransport) -> tuple[str, ...]:
        return ("some-other-key",)

    monkeypatch.setattr(_module._auth_actions, "fetch_api_keys", returns_other_keys)

    async def run() -> bool:
        return await _module._credentials_are_active(
            config=PRODUCTION_CONFIG,
            signer=_signer(),
            credentials=PROVIDED,
            logger=None,
        )

    assert asyncio.run(run()) is False


def test_credentials_are_active_propagates_non_401_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def raise_500(_transport: AsyncTransport) -> tuple[str, ...]:
        raise RequestRejectedError("server error", status=500)

    monkeypatch.setattr(_module._auth_actions, "fetch_api_keys", raise_500)

    async def run() -> bool:
        return await _module._credentials_are_active(
            config=PRODUCTION_CONFIG,
            signer=_signer(),
            credentials=PROVIDED,
            logger=None,
        )

    with pytest.raises(RequestRejectedError) as info:
        asyncio.run(run())
    assert info.value.status == 500
