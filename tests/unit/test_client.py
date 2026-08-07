# pyright: reportPrivateUsage=false
import asyncio
import inspect
from typing import cast

import pytest

from polymarket import (
    ApiKeyCreds,
    AsyncPublicClient,
    AsyncSecureClient,
    PublicClient,
    SecureClient,
)
from polymarket._internal.context import AsyncSecureClientContext
from polymarket._internal.environment import get_environment_config
from polymarket.errors import UserInputError

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
SIGNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
PRIVATE_KEY_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_CREDS = ApiKeyCreds(key="test-key", passphrase="test-passphrase", secret="dGVzdA==")


def test_client_uses_production_by_default() -> None:
    client = PublicClient()

    assert client.environment.name == "production"


def test_async_client_uses_production_by_default() -> None:
    client = AsyncPublicClient()

    assert client.environment.name == "production"


def test_public_client_supports_context_manager() -> None:
    with PublicClient() as client:
        assert client.environment.name == "production"


def test_async_public_client_supports_context_manager() -> None:
    async def run() -> None:
        async with AsyncPublicClient() as client:
            assert client.environment.name == "production"

    asyncio.run(run())


def test_secure_client_factory_uses_production_by_default() -> None:
    client = SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    )
    try:
        assert client.environment.name == "production"
    finally:
        client.close()


def test_secure_client_factory_signature_hides_test_validation_switch() -> None:
    assert "validate_credentials" not in inspect.signature(SecureClient.create).parameters
    assert "validate_credentials" not in inspect.signature(AsyncSecureClient.create).parameters


def test_secure_client_requires_factory() -> None:
    from polymarket._internal.context import SyncSecureClientContext

    with pytest.raises(RuntimeError, match="SecureClient.create"):
        SecureClient(ctx=cast(SyncSecureClientContext, object()))


def test_secure_client_supports_context_manager() -> None:
    with SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        assert client.environment.name == "production"


def test_async_secure_client_factory_uses_production_by_default() -> None:
    async def run() -> None:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            assert client.environment.name == "production"
        finally:
            await client.close()

    asyncio.run(run())


def test_async_secure_client_requires_factory() -> None:
    with pytest.raises(RuntimeError, match="AsyncSecureClient.create"):
        AsyncSecureClient(ctx=cast(AsyncSecureClientContext, object()))


def test_async_secure_client_supports_context_manager() -> None:
    async def run() -> None:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        async with client:
            assert client.environment.name == "production"

    asyncio.run(run())


def test_secure_client_exposes_signer_wallet() -> None:
    with SecureClient._create(
        private_key=PRIVATE_KEY,
        wallet=SIGNER_ADDRESS,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        assert client.wallet == PRIVATE_KEY_ADDRESS


def test_async_secure_client_exposes_signer_wallet() -> None:
    async def run() -> None:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            wallet=SIGNER_ADDRESS,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            assert client.wallet == PRIVATE_KEY_ADDRESS
        finally:
            await client.close()

    asyncio.run(run())


def test_secure_client_invalid_key_raises_user_input_error() -> None:
    with pytest.raises(UserInputError, match="Invalid private_key"):
        SecureClient.create(private_key="not-a-valid-key", wallet=SIGNER_ADDRESS)


def test_secure_client_wallet_defaults_to_beacon_deposit_wallet_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eth_account import Account

    import polymarket.clients.secure as secure_module
    from polymarket._internal.wallet import (
        derive_beacon_deposit_wallet_address,
        derive_uups_deposit_wallet_address,
    )
    from polymarket.environments import PRODUCTION
    from polymarket.models.clob.relayer import RelayerTransactionType

    signer = Account.from_key(PRIVATE_KEY)
    legacy_wallet = derive_uups_deposit_wallet_address(
        signer.address, get_environment_config(PRODUCTION).wallet_derivation
    )
    expected = derive_beacon_deposit_wallet_address(
        signer.address, get_environment_config(PRODUCTION).wallet_derivation
    )

    def fake_fetch_deployed_sync(
        *args: object, address: str, type: RelayerTransactionType | None
    ) -> bool:
        assert address == legacy_wallet
        assert type == RelayerTransactionType.WALLET
        return False

    monkeypatch.setattr(secure_module, "fetch_deployed_sync", fake_fetch_deployed_sync)

    with SecureClient._create(
        private_key=PRIVATE_KEY,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        assert client.wallet_type == "DEPOSIT_WALLET"
        assert str(client.wallet) == expected


def test_secure_client_wallet_defaults_to_existing_legacy_deposit_wallet_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eth_account import Account

    import polymarket.clients.secure as secure_module
    from polymarket._internal.wallet import derive_uups_deposit_wallet_address
    from polymarket.environments import PRODUCTION
    from polymarket.models.clob.relayer import RelayerTransactionType

    signer = Account.from_key(PRIVATE_KEY)
    expected = derive_uups_deposit_wallet_address(
        signer.address, get_environment_config(PRODUCTION).wallet_derivation
    )

    def fake_fetch_deployed_sync(
        *args: object, address: str, type: RelayerTransactionType | None
    ) -> bool:
        assert address == expected
        assert type == RelayerTransactionType.WALLET
        return True

    monkeypatch.setattr(secure_module, "fetch_deployed_sync", fake_fetch_deployed_sync)

    with SecureClient._create(
        private_key=PRIVATE_KEY,
        credentials=FAKE_CREDS,
        validate_credentials=False,
    ) as client:
        assert client.wallet_type == "DEPOSIT_WALLET"
        assert str(client.wallet) == expected


def test_async_secure_client_invalid_key_raises_user_input_error() -> None:
    async def run() -> None:
        with pytest.raises(UserInputError, match="Invalid private_key"):
            await AsyncSecureClient.create(private_key="not-a-valid-key", wallet=SIGNER_ADDRESS)

    asyncio.run(run())


def test_async_secure_client_wallet_defaults_to_beacon_deposit_wallet_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eth_account import Account

    import polymarket.clients.async_secure as async_secure_module
    from polymarket._internal.wallet import (
        derive_beacon_deposit_wallet_address,
        derive_uups_deposit_wallet_address,
    )
    from polymarket.environments import PRODUCTION
    from polymarket.models.clob.relayer import RelayerTransactionType

    signer = Account.from_key(PRIVATE_KEY)
    legacy_wallet = derive_uups_deposit_wallet_address(
        signer.address, get_environment_config(PRODUCTION).wallet_derivation
    )
    expected = derive_beacon_deposit_wallet_address(
        signer.address, get_environment_config(PRODUCTION).wallet_derivation
    )

    async def fake_fetch_deployed(
        *args: object, address: str, type: RelayerTransactionType | None
    ) -> bool:
        assert address == legacy_wallet
        assert type == RelayerTransactionType.WALLET
        return False

    monkeypatch.setattr(async_secure_module, "fetch_deployed", fake_fetch_deployed)

    async def run() -> str:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            assert client.wallet_type == "DEPOSIT_WALLET"
            return str(client.wallet)
        finally:
            await client.close()

    assert asyncio.run(run()) == expected


def test_async_secure_client_wallet_defaults_to_existing_legacy_deposit_wallet_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eth_account import Account

    import polymarket.clients.async_secure as async_secure_module
    from polymarket._internal.wallet import derive_uups_deposit_wallet_address
    from polymarket.environments import PRODUCTION
    from polymarket.models.clob.relayer import RelayerTransactionType

    signer = Account.from_key(PRIVATE_KEY)
    expected = derive_uups_deposit_wallet_address(
        signer.address, get_environment_config(PRODUCTION).wallet_derivation
    )

    async def fake_fetch_deployed(
        *args: object, address: str, type: RelayerTransactionType | None
    ) -> bool:
        assert address == expected
        assert type == RelayerTransactionType.WALLET
        return True

    monkeypatch.setattr(async_secure_module, "fetch_deployed", fake_fetch_deployed)

    async def run() -> str:
        client = await AsyncSecureClient._create(
            private_key=PRIVATE_KEY,
            credentials=FAKE_CREDS,
            validate_credentials=False,
        )
        try:
            assert client.wallet_type == "DEPOSIT_WALLET"
            return str(client.wallet)
        finally:
            await client.close()

    assert asyncio.run(run()) == expected
