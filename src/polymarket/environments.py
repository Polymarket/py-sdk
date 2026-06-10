"""Polymarket environment configuration."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class WalletDerivation:
    proxy_factory: str
    proxy_implementation: str
    safe_factory: str
    safe_init_code_hash: str
    deposit_wallet_factory: str
    deposit_wallet_implementation: str
    deposit_wallet_beacon: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Environment:
    name: str
    chain_id: int
    wallet_derivation: WalletDerivation
    collateral_token: str
    conditional_tokens: str
    neg_risk_adapter: str
    collateral_adapter: str
    neg_risk_collateral_adapter: str
    standard_exchange: str
    neg_risk_exchange: str
    auto_redeem_operator: str
    safe_multisend: str
    relay_hub: str
    clob_url: str
    clob_market_ws_url: str
    clob_user_ws_url: str
    relayer_url: str
    gamma_url: str
    data_url: str
    rfq_url: str
    rtds_ws_url: str
    sports_ws_url: str
    rpc_url: str
    exchange_v3: str = "0xe3333700cA9d93003F00f0F71f8515005F6c00Aa"
    protocol_v2_router: str = "0x12121212006e4CD160D18e3f00711DA5c3372600"
    combinatorial_module: str = "0x30000034706c7d8e12009dab006be20000c031a8"
    position_manager: str = "0x006F54F7f9A22e0000CC2AB60031000000ae9fEF"
    rfq_quoter_ws_url: str = "wss://combos-rfq-gateway-quoter.polymarket.sh/ws/rfq"
    rfq_quoter_ws_headers: dict[str, str] | None = None
    relayer_max_polls: int = 100
    relayer_poll_frequency_ms: int = 2000


PRODUCTION = Environment(
    name="production",
    chain_id=137,
    wallet_derivation=WalletDerivation(
        proxy_factory="0xaB45c5A4B0c941a2F231C04C3f49182e1A254052",
        proxy_implementation="0x44e999d5c2F66Ef0861317f9A4805AC2e90aEB4f",
        safe_factory="0xaacFeEa03eb1561C4e67d661e40682Bd20E3541b",
        safe_init_code_hash="0x2bce2127ff07fb632d16c8347c4ebf501f4841168bed00d9e6ef715ddb6fcecf",
        deposit_wallet_factory="0x00000000000Fb5C9ADea0298D729A0CB3823Cc07",
        deposit_wallet_implementation="0x58CA52ebe0DadfdF531Cde7062e76746de4Db1eB",
        deposit_wallet_beacon="0x7A18EDfe055488A3128f01F563e5B479D92ffc3a",
    ),
    collateral_token="0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB",
    conditional_tokens="0x4D97DCd97eC945f40cF65F87097ACe5EA0476045",
    neg_risk_adapter="0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296",
    collateral_adapter="0xAdA100Db00Ca00073811820692005400218FcE1f",
    neg_risk_collateral_adapter="0xadA2005600Dec949baf300f4C6120000bDB6eAab",
    standard_exchange="0xE111180000d2663C0091e4f400237545B87B996B",
    neg_risk_exchange="0xe2222d279d744050d28e00520010520000310F59",
    auto_redeem_operator="0xF3cFb6a6eBFeB51876289Eb235719EB1C65252B0",
    safe_multisend="0xA238CBeb142c10Ef7Ad8442C6D1f9E89e07e7761",
    relay_hub="0xD216153c06E857cD7f72665E0aF1d7D82172F494",
    clob_url="https://clob.polymarket.com",
    clob_market_ws_url="wss://ws-subscriptions-clob.polymarket.com/ws/market",
    clob_user_ws_url="wss://ws-subscriptions-clob.polymarket.com/ws/user",
    relayer_url="https://relayer-v2.polymarket.com",
    gamma_url="https://gamma-api.polymarket.com",
    data_url="https://data-api.polymarket.com",
    rfq_url="https://combos-rfq-api.polymarket.sh",
    rtds_ws_url="wss://ws-live-data.polymarket.com",
    sports_ws_url="wss://sports-api.polymarket.com/ws",
    rpc_url="https://polygon.drpc.org",
)

__all__ = ["Environment", "PRODUCTION", "WalletDerivation"]
