# Polymarket Python SDK

Official Python SDK for Polymarket.

The SDK gives Python developers one coherent, workflow-oriented interface for building on Polymarket across public data, authenticated account, trading, builder attribution, and wallet workflows.

## Installation

```bash
uv add polymarket-client
```

or:

```bash
pip install polymarket-client
```

## Usage

Synchronous client:

```python
from polymarket import Market, PublicClient

with PublicClient() as client:
    market: Market = client.get_market(url="https://polymarket.com/event/example-market")
```

Asynchronous client:

```python
import asyncio

from polymarket import AsyncPublicClient, Market


async def main() -> None:
    async with AsyncPublicClient() as client:
        market: Market = await client.get_market(
            url="https://polymarket.com/event/example-market"
        )


asyncio.run(main())
```

Batch position merges:

```python
# Merge regular market positions by condition or market id.
handle = client.merge_multiple_positions(
    positions=[
        {"condition_id": condition_id_1},
        {"market_id": market_id_2, "amount": "max"},
        {"condition_id": condition_id_3, "amount": 500_000},
    ],
)

outcome = handle.wait()

# Or merge combo positions by position id. Do not mix market and combo
# requests in the same batch.
handle = client.merge_multiple_positions(
    positions=[
        {"position_id": combo_position_id_1},
        {"position_id": combo_position_id_2, "amount": "max"},
        {"position_id": combo_position_id_3, "amount": 500_000},
    ],
)

outcome = handle.wait()
```

## API Compatibility

The SDK follows semantic versioning. Although minor releases on the 0.x line
may include breaking changes, we aim to avoid them and, whenever possible,
provide a deprecation path before removing or changing an API. Patch releases
remain backward compatible except for APIs marked experimental, which may
change in any release. All Perps APIs are currently experimental, including
client methods, sessions, stream subscriptions, and models.

## API Design

See [SDK Direction](docs/sdk-direction.md) for public API design principles and developer-experience decisions.

## Development

Install dependencies:

```bash
make sync
```

Run checks:

```bash
make check
```

Build package artifacts:

```bash
make build
```

Build the Mintlify-compatible Sphinx JSON API-reference artifact:

```bash
make api-reference
```

The ZIP is written to `build/api-reference/polymarket-client-sphinx.zip`. The
`API Reference` GitHub Actions workflow can also generate it manually for a
selected branch or commit. Successful package releases attach a versioned copy
to the corresponding GitHub Release.

The `Makefile` is a thin convenience wrapper around `uv`. Running the underlying commands directly is also fine.

## Testing

Unit tests run by default:

```bash
make test
```

Run unit tests in watch mode:

```bash
make test-watch
```

This runs the tests once immediately, then reruns them when Python files change.

Integration tests are opt-in:

```bash
make test-integration
```

Integration tests can load local secrets from a gitignored `.env` copied from `.env.example`:

```bash
cp .env.example .env
```

See `.env.example` for the supported local and CI secret names.

Tests that require credentials should use the `require_env` fixture so they skip when secrets are unavailable:

```python
import pytest


@pytest.mark.integration
def test_authenticated_flow(require_env):
    private_key = require_env("POLYMARKET_PRIVATE_KEY")
    builder_api_key = require_env("POLYMARKET_BUILDER_API_KEY")

    assert private_key
    assert builder_api_key
```

The SDK does not load `.env` files at runtime. Integration fixtures load `.env` for test configuration and credentials, and existing environment variables take precedence over local `.env` values.

Tests that place orders, spend funds, or mutate live state must also use `@pytest.mark.metered`. Metered tests are skipped unless `POLYMARKET_RUN_METERED_TESTS=1` is set:

```python
import pytest


@pytest.mark.integration
@pytest.mark.metered
def test_order_lifecycle(require_env):
    private_key = require_env("POLYMARKET_PRIVATE_KEY")

    assert private_key
```

```bash
POLYMARKET_RUN_METERED_TESTS=1 make test-integration
```

## Contributing

We welcome bug reports, feature requests, and feedback through GitHub Issues.
See [CONTRIBUTING.md](CONTRIBUTING.md) before proposing code changes.
