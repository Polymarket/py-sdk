"""Integration-test environment configuration."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import cast

from polymarket import PRODUCTION, Environment
from polymarket._internal.environment import PRODUCTION_CONFIG, create_environment

INTEGRATION_ENVIRONMENT_CONFIG_ENV_VAR = "POLYMARKET_INTEGRATION_ENVIRONMENT_CONFIG"

_ROOT_KEYS = {
    "name",
    "chainId",
    "rpc",
    "walletDerivation",
    "contracts",
    "clob",
    "bridge",
    "relayer",
    "gamma",
    "data",
    "combos",
    "perps",
    "rtds",
    "sports",
    "relayerMaxPolls",
    "relayerPollFrequencyMs",
}
_WALLET_DERIVATION_FIELDS = {
    "proxyFactory": "proxy_factory",
    "proxyImplementation": "proxy_implementation",
    "safeFactory": "safe_factory",
    "safeInitCodeHash": "safe_init_code_hash",
    "depositWalletFactory": "deposit_wallet_factory",
    "depositWalletImplementation": "deposit_wallet_implementation",
    "depositWalletBeacon": "deposit_wallet_beacon",
}
_CONTRACT_FIELDS = {
    "collateralToken": "collateral_token",
    "conditionalTokens": "conditional_tokens",
    "negRiskAdapter": "neg_risk_adapter",
    "collateralAdapter": "collateral_adapter",
    "negRiskCollateralAdapter": "neg_risk_collateral_adapter",
    "standardExchange": "standard_exchange",
    "negRiskExchange": "neg_risk_exchange",
    "exchangeV3": "exchange_v3",
    "protocolV2Router": "protocol_v2_router",
    "binaryModule": "binary_module",
    "negRiskModule": "neg_risk_module",
    "combinatorialModule": "combinatorial_module",
    "positionManager": "position_manager",
    "autoRedeemOperator": "auto_redeem_operator",
    "safeMultisend": "safe_multisend",
    "relayHub": "relay_hub",
    "perpsDepositContract": "perps_deposit_contract",
}


def load_integration_environment(raw_config: str | None) -> Environment:
    """Fork production using the TypeScript integration fixture's JSON shape."""
    if raw_config is None or not raw_config.strip():
        return PRODUCTION

    try:
        decoded = json.loads(raw_config)
    except json.JSONDecodeError as error:
        raise ValueError("must contain a valid JSON object") from error
    fork = _require_object(decoded, path="environment config")
    _reject_unknown_keys(fork, allowed=_ROOT_KEYS, path="environment config")

    config = PRODUCTION_CONFIG
    config_updates: dict[str, object] = {}

    if "chainId" in fork:
        config_updates["chain_id"] = _require_positive_int(fork["chainId"], path="chainId")
    if "rpc" in fork:
        config_updates["rpc_url"] = _require_string(fork["rpc"], path="rpc")
    if "relayerMaxPolls" in fork:
        config_updates["relayer_max_polls"] = _require_positive_int(
            fork["relayerMaxPolls"], path="relayerMaxPolls"
        )
    if "relayerPollFrequencyMs" in fork:
        config_updates["relayer_poll_frequency_ms"] = _require_non_negative_int(
            fork["relayerPollFrequencyMs"], path="relayerPollFrequencyMs"
        )

    wallet_derivation = _optional_object(fork, "walletDerivation")
    if wallet_derivation is not None:
        _reject_unknown_keys(
            wallet_derivation,
            allowed=set(_WALLET_DERIVATION_FIELDS),
            path="walletDerivation",
        )
        wallet_updates = {
            python_name: _require_string(
                wallet_derivation[json_name], path=f"walletDerivation.{json_name}"
            )
            for json_name, python_name in _WALLET_DERIVATION_FIELDS.items()
            if json_name in wallet_derivation
        }
        config_updates["wallet_derivation"] = replace(
            config.wallet_derivation,
            **wallet_updates,
        )

    contracts = _optional_object(fork, "contracts")
    if contracts is not None:
        _reject_unknown_keys(contracts, allowed=set(_CONTRACT_FIELDS), path="contracts")
        config_updates.update(
            {
                python_name: _require_string(contracts[json_name], path=f"contracts.{json_name}")
                for json_name, python_name in _CONTRACT_FIELDS.items()
                if json_name in contracts
            }
        )

    clob = _optional_object(fork, "clob")
    if clob is not None:
        _reject_unknown_keys(clob, allowed={"rest", "headers", "market", "user"}, path="clob")
        _require_empty_headers(clob, path="clob")
        _copy_string(clob, "rest", config_updates, "clob_url", path="clob.rest")
        market = _optional_object(clob, "market", parent_path="clob")
        if market is not None:
            _reject_unknown_keys(market, allowed={"ws", "headers"}, path="clob.market")
            _require_empty_headers(market, path="clob.market")
            _copy_string(
                market,
                "ws",
                config_updates,
                "clob_market_ws_url",
                path="clob.market.ws",
            )
        user = _optional_object(clob, "user", parent_path="clob")
        if user is not None:
            _reject_unknown_keys(user, allowed={"ws", "headers"}, path="clob.user")
            _require_empty_headers(user, path="clob.user")
            _copy_string(
                user,
                "ws",
                config_updates,
                "clob_user_ws_url",
                path="clob.user.ws",
            )

    for json_name, python_name in (
        ("relayer", "relayer_url"),
        ("gamma", "gamma_url"),
        ("data", "data_url"),
    ):
        endpoint = _optional_object(fork, json_name)
        if endpoint is None:
            continue
        _reject_unknown_keys(endpoint, allowed={"rest", "headers"}, path=json_name)
        _require_empty_headers(endpoint, path=json_name)
        _copy_string(endpoint, "rest", config_updates, python_name, path=f"{json_name}.rest")

    combos = _optional_object(fork, "combos")
    if combos is not None:
        _reject_unknown_keys(
            combos,
            allowed={"rest", "ws", "headers", "builderGateway", "collateralReturn"},
            path="combos",
        )
        _require_empty_headers(combos, path="combos")
        _copy_string(combos, "rest", config_updates, "rfq_url", path="combos.rest")
        _copy_string(combos, "ws", config_updates, "rfq_quoter_ws_url", path="combos.ws")
        for nested_name, python_name in (
            ("builderGateway", "builder_gateway_url"),
            ("collateralReturn", "collateral_return_url"),
        ):
            endpoint = _optional_object(combos, nested_name, parent_path="combos")
            if endpoint is None:
                continue
            path = f"combos.{nested_name}"
            _reject_unknown_keys(endpoint, allowed={"rest", "headers"}, path=path)
            _require_empty_headers(endpoint, path=path)
            _copy_string(endpoint, "rest", config_updates, python_name, path=f"{path}.rest")

    perps = _optional_object(fork, "perps")
    if perps is not None:
        _reject_unknown_keys(perps, allowed={"rest", "ws", "headers"}, path="perps")
        _require_empty_headers(perps, path="perps")
        _copy_string(perps, "rest", config_updates, "perps_url", path="perps.rest")
        _copy_string(perps, "ws", config_updates, "perps_ws_url", path="perps.ws")

    for json_name, python_name in (("rtds", "rtds_ws_url"), ("sports", "sports_ws_url")):
        endpoint = _optional_object(fork, json_name)
        if endpoint is None:
            continue
        _reject_unknown_keys(endpoint, allowed={"ws", "headers"}, path=json_name)
        _require_empty_headers(endpoint, path=json_name)
        _copy_string(endpoint, "ws", config_updates, python_name, path=f"{json_name}.ws")

    bridge = _optional_object(fork, "bridge")
    if bridge is not None:
        _reject_unknown_keys(bridge, allowed={"rest", "headers"}, path="bridge")
        _require_empty_headers(bridge, path="bridge")
        if "rest" in bridge:
            _require_string(bridge["rest"], path="bridge.rest")

    name = PRODUCTION.name
    if "name" in fork:
        name = _require_string(fork["name"], path="name")
    return create_environment(name=name, config=replace(config, **config_updates))


def _require_object(value: object, *, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    mapping = cast(Mapping[object, object], value)
    if any(not isinstance(key, str) for key in mapping):
        raise ValueError(f"{path} keys must be strings")
    return cast(dict[str, object], value)


def _optional_object(
    parent: Mapping[str, object],
    key: str,
    *,
    parent_path: str = "environment config",
) -> dict[str, object] | None:
    if key not in parent:
        return None
    return _require_object(parent[key], path=f"{parent_path}.{key}")


def _reject_unknown_keys(
    value: Mapping[str, object],
    *,
    allowed: set[str],
    path: str,
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{path} contains unsupported keys: {', '.join(unknown)}")


def _require_string(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value.strip()


def _require_positive_int(value: object, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{path} must be a positive integer")
    return value


def _require_non_negative_int(value: object, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{path} must be a non-negative integer")
    return value


def _copy_string(
    source: Mapping[str, object],
    source_name: str,
    target: dict[str, object],
    target_name: str,
    *,
    path: str,
) -> None:
    if source_name in source:
        target[target_name] = _require_string(source[source_name], path=path)


def _require_empty_headers(endpoint: Mapping[str, object], *, path: str) -> None:
    if "headers" not in endpoint:
        return
    headers = _require_object(endpoint["headers"], path=f"{path}.headers")
    if headers:
        raise ValueError(
            f"{path}.headers is not supported by Python integration transports; "
            "only an empty object is accepted"
        )


__all__ = [
    "INTEGRATION_ENVIRONMENT_CONFIG_ENV_VAR",
    "load_integration_environment",
]
