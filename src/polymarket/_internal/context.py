from __future__ import annotations

from dataclasses import InitVar, dataclass, field

from eth_account.signers.local import LocalAccount

from polymarket._internal.actions.orders.cache import (
    AsyncOrderMetadataCache,
    SyncOrderMetadataCache,
)
from polymarket._internal.environment import EnvironmentConfig, get_environment_config
from polymarket._internal.eoa.rpc import JsonRpcClient, SyncJsonRpcClient
from polymarket._internal.wallet import WalletType
from polymarket.auth import ApiKey
from polymarket.clients._transport import AsyncTransport, SyncTransport
from polymarket.environments import Environment
from polymarket.models.clob import ApiKeyCreds
from polymarket.types import EvmAddress


@dataclass(frozen=True, slots=True, kw_only=True)
class SyncClientContext:
    environment: Environment
    environment_config: EnvironmentConfig = field(init=False, repr=False)
    gamma: SyncTransport
    data: SyncTransport
    rfq: SyncTransport
    clob: SyncTransport
    _resolved_environment_config: InitVar[EnvironmentConfig | None] = None

    def __post_init__(self, _resolved_environment_config: EnvironmentConfig | None) -> None:
        config = _resolved_environment_config or get_environment_config(self.environment)
        object.__setattr__(self, "environment_config", config)


@dataclass(frozen=True, slots=True, kw_only=True)
class SyncSecureClientContext(SyncClientContext):
    signer: LocalAccount
    credentials: ApiKeyCreds
    secure_clob: SyncTransport
    wallet: EvmAddress
    wallet_type: WalletType
    relayer: SyncTransport
    combos: SyncTransport
    api_key: ApiKey | None
    rpc: SyncJsonRpcClient
    order_metadata: SyncOrderMetadataCache


@dataclass(frozen=True, slots=True, kw_only=True)
class AsyncClientContext:
    environment: Environment
    environment_config: EnvironmentConfig = field(init=False, repr=False)
    gamma: AsyncTransport
    data: AsyncTransport
    rfq: AsyncTransport
    clob: AsyncTransport
    perps: AsyncTransport
    _resolved_environment_config: InitVar[EnvironmentConfig | None] = None

    def __post_init__(self, _resolved_environment_config: EnvironmentConfig | None) -> None:
        config = _resolved_environment_config or get_environment_config(self.environment)
        object.__setattr__(self, "environment_config", config)


@dataclass(frozen=True, slots=True, kw_only=True)
class AsyncSecureClientContext(AsyncClientContext):
    signer: LocalAccount
    credentials: ApiKeyCreds
    secure_clob: AsyncTransport
    wallet: EvmAddress
    wallet_type: WalletType
    relayer: AsyncTransport
    combos: AsyncTransport
    api_key: ApiKey | None
    rpc: JsonRpcClient
    order_metadata: AsyncOrderMetadataCache


__all__ = [
    "AsyncClientContext",
    "AsyncSecureClientContext",
    "SyncClientContext",
    "SyncSecureClientContext",
]
