# Polymarket Python SDK

![Beta](https://img.shields.io/badge/status-beta-yellow)

Official Python SDK for Polymarket.

The SDK gives Python developers one coherent, workflow-oriented interface for building on Polymarket across public data, authenticated account, trading, builder attribution, and wallet workflows.

## Beta Status

The Python SDK is currently in beta. We are working toward a stable public API and will use feedback during the beta period to refine the developer experience.

We welcome bug reports, feature requests, and general feedback through GitHub Issues. Please use the provided issue templates so we can triage reports consistently.

## Installation

```bash
uv add --prerelease allow polymarket-client
```

or:

```bash
pip install --pre polymarket-client
```

## Usage

Synchronous client:

```python
from polymarket import Market, PublicClient

with PublicClient() as client:
    market: Market = client.get_market(url="https://polymarket.com/market/example-market")
```

Asynchronous client:

```python
import asyncio

from polymarket import AsyncPublicClient, Market


async def main() -> None:
    async with AsyncPublicClient() as client:
        market: Market = await client.get_market(
            url="https://polymarket.com/market/example-market"
        )


asyncio.run(main())
```

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

The SDK does not load `.env` files at runtime. The integration test fixture loads `.env` only for tests that request credentials, and existing environment variables take precedence over local `.env` values.

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
