"""Regression tests for integration environment overrides."""

from __future__ import annotations

import json

import pytest
from _environment import load_integration_environment

from polymarket import PRODUCTION
from polymarket._internal.environment import get_environment_config


def test_load_integration_environment_accepts_typescript_fork_shape() -> None:
    environment = load_integration_environment(
        json.dumps(
            {
                "name": "staging",
                "chainId": 80002,
                "rpc": "https://rpc.stage.example",
                "walletDerivation": {
                    "depositWalletFactory": "0x0000000000000000000000000000000000000001"
                },
                "contracts": {
                    "collateralToken": "0x0000000000000000000000000000000000000002",
                    "exchangeV3": "0x0000000000000000000000000000000000000003",
                    "binaryModule": "0x0000000000000000000000000000000000000004",
                    "negRiskModule": "0x0000000000000000000000000000000000000005",
                },
                "clob": {
                    "rest": "https://clob.stage.example",
                    "headers": {},
                    "market": {"ws": "wss://market.stage.example", "headers": {}},
                    "user": {"ws": "wss://user.stage.example", "headers": {}},
                },
                "predictions": {"rest": "https://api.stage.example", "headers": {}},
                "combos": {"ws": "wss://combos.stage.example"},
                "perps": {
                    "rest": "https://perps.stage.example",
                    "ws": "wss://perps.stage.example",
                },
                "rtds": {"ws": "wss://rtds.stage.example"},
                "sports": {"ws": "wss://sports.stage.example"},
                "relayerMaxPolls": 12,
                "relayerPollFrequencyMs": 0,
            }
        )
    )

    config = get_environment_config(environment)
    assert environment.name == "staging"
    assert config.chain_id == 80002
    assert config.rpc_url == "https://rpc.stage.example"
    assert (
        config.wallet_derivation.deposit_wallet_factory
        == "0x0000000000000000000000000000000000000001"
    )
    assert config.collateral_token == "0x0000000000000000000000000000000000000002"
    assert config.exchange_v3 == "0x0000000000000000000000000000000000000003"
    assert config.binary_module == "0x0000000000000000000000000000000000000004"
    assert config.neg_risk_module == "0x0000000000000000000000000000000000000005"
    assert config.clob_url == "https://clob.stage.example"
    assert config.clob_market_ws_url == "wss://market.stage.example"
    assert config.clob_user_ws_url == "wss://user.stage.example"
    assert config.predictions_url == "https://api.stage.example"
    assert config.rfq_quoter_ws_url == "wss://combos.stage.example"
    assert config.perps_url == "https://perps.stage.example"
    assert config.perps_ws_url == "wss://perps.stage.example"
    assert config.rtds_ws_url == "wss://rtds.stage.example"
    assert config.sports_ws_url == "wss://sports.stage.example"
    assert config.relayer_max_polls == 12
    assert config.relayer_poll_frequency_ms == 0


def test_load_integration_environment_defaults_to_production() -> None:
    assert load_integration_environment(None) is PRODUCTION
    assert load_integration_environment("  ") is PRODUCTION


def test_load_integration_environment_rejects_unsupported_headers() -> None:
    with pytest.raises(ValueError, match="headers is not supported"):
        load_integration_environment(
            '{"clob":{"rest":"https://clob.stage.example","headers":{"X-Test":"1"}}}'
        )
