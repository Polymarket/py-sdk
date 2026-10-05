# Python Examples

Runnable scripts that demonstrate common SDK workflows. Each is a module under
the `examples` package; run one from the repository root with `uv`:

```bash
uv run python -m examples.list_markets
uv run python -m examples.fetch_market
uv run python -m examples.pagination
uv run python -m examples.market_prices
uv run python -m examples.crypto_twap_stream
uv run python -m examples.stream_realtime_prices
uv run python -m examples.search
uv run python -m examples.list_positions
uv run python -m examples.create_limit_order
uv run python -m examples.create_market_order
```

## Credentials

The read examples (`list_markets`, `fetch_market`, `pagination`,
`market_prices`, `crypto_twap_stream`, `search`) need no credentials.

The remaining examples read environment variables — the same ones the
integration tests use — straight from your shell. Nothing auto-loads a `.env`
here, so either export the variables, or copy the root `.env.example` to `.env`
and load it yourself before running:

```bash
set -a && source .env && set +a
```

Or pass them inline on the command (as shown in each script's header):

- `list_positions` needs `POLYMARKET_DEPOSIT_WALLET` (the wallet to inspect).
  It shows `current_size` in shares, `current_price` in USDC, and `asset_id`.
  Use `client.list_positions(status="CLOSED", user=wallet)` for closed positions.
- `create_limit_order` / `create_market_order` need `POLYMARKET_PRIVATE_KEY`
  and `POLYMARKET_DEPOSIT_WALLET`.
- `stream_realtime_prices` uses the same secure-client credentials to read
  crypto, fixed 60-second TWAP, and equity prices. It prints recent history and
  live updates, then closes its subscriptions. See `.env.example` for setup.

The legacy price specs (`CryptoPricesSpec`, `CryptoPricesChainlinkTwapSpec`, and
`EquityPricesSpec`) are deprecated. For new integrations use `CryptoPriceSpec`,
`CryptoTwapPriceSpec`, and `EquityPriceSpec` with `AsyncSecureClient`. Crypto symbols
must be canonical lowercase USD pairs such as `btcusd`, rather than `btc/usd` or
`btcusdt`. Keep existing legacy subscriptions during your application's migration;
no Python removal date has been scheduled by this change.

New price events use `Decimal` values in the instrument's quote currency and
timezone-aware timestamps. Crypto prices and crypto TWAPs are quoted in USD.
Equity and forex prices retain their quote currency. History
events have `type="subscribe"`; live events have `type="update"`. Sequence numbers
are local to one channel on one connection and reset on reconnection. Subscriptions
spanning multiple connections may interleave sequence values.

The order examples **build and sign** an order locally and print it; they do
**not** submit anything to the exchange.

## Shared helpers

`examples/lib/` holds small helpers shared across scripts: `require_env` for
required environment variables and `find_order_example_market` for locating a
live, order-book-enabled market for the order examples.
