# Python Examples

Runnable scripts that demonstrate common SDK workflows. Each is a module under
the `examples` package; run one from the repository root with `uv`:

```bash
uv run python -m examples.list_markets
uv run python -m examples.fetch_market
uv run python -m examples.pagination
uv run python -m examples.market_prices
uv run python -m examples.crypto_twap_stream
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
- `create_limit_order` / `create_market_order` need `POLYMARKET_PRIVATE_KEY`
  and `POLYMARKET_DEPOSIT_WALLET`.

The order examples **build and sign** an order locally and print it; they do
**not** submit anything to the exchange.

## Shared helpers

`examples/lib/` holds small helpers shared across scripts: `require_env` for
required environment variables and `find_order_example_market` for locating a
live, order-book-enabled market for the order examples.
