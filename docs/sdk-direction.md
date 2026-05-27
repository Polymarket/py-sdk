# SDK Direction

This document records developer-experience decisions that shape the public Polymarket Python SDK API.

## API Principles

- Present one cohesive consumer interface with stable, idiomatic Python objects.
- Design public APIs around developer workflows.
- Keep the default experience simple for scripts, notebooks, CLIs, tests, and bots.
- Preserve feature parity direction with other Polymarket SDKs while adapting API shape to Python ecosystem norms.

## Sync and Async Clients

The default clients are synchronous:

```python
from polymarket import PublicClient

client = PublicClient()
market = client.get_market(id="540816")
```

Async clients use explicit async client classes while retaining the same mental model:

```python
from polymarket import AsyncPublicClient

client = AsyncPublicClient()
market = await client.get_market(id="540816")
```

We evaluated common Python SDKs in trading, exchange, and Web3 ecosystems. The most Pythonic convention is to keep unprefixed clients synchronous and expose async variants with an `Async` prefix, rather than using mode flags or adding separate `_async` methods to every sync client.

The sync and async clients should share request builders, models, auth/signing, serialization, validation, response parsing, and namespace structure. Their implementations should differ at the transport boundary: sync clients use sync transports, async clients use async transports.

Supported workflows should be available on both sync and async clients where practical. Sync implementations should use sync transports rather than wrapping async implementations in `asyncio.run()`.

Clients that own network transports should support explicit cleanup. Synchronous clients should be usable as context managers:

```python
from polymarket import PublicClient

with PublicClient() as client:
    market = client.get_market(id="540816")
```

Async clients should support the corresponding async context-manager pattern:

```python
from polymarket import AsyncPublicClient

async with AsyncPublicClient() as client:
    market = await client.get_market(id="540816")
```

Clients should also expose explicit `close()` methods. Async clients should expose `await client.close()` so callers that do not use `async with` can still release async HTTP sessions, sockets, or other transport resources deterministically.

## Domain Types

The SDK uses lightweight marked types for important domain values where a plain primitive would hide useful meaning in IDEs and type hints.

Generic domain primitives live outside the models package:

```python
from polymarket import EvmAddress, HexString, TransactionHash
```

Model-specific identifiers live with the models and are re-exported for convenience:

```python
from polymarket import ConditionId, EventId, MarketId, OrderId, TokenId
from polymarket.models import MarketId
```

These types are implemented with `typing.NewType`, so returned SDK objects can show meaningful field types without adding runtime wrapper objects. A returned `MarketId` is still usable where a `str` is accepted.

We intentionally do not mark every primitive value. Marked types should be reserved for key identifiers and domain concepts where the type name improves readability or reduces accidental mixups. Public method inputs should remain developer-friendly and may accept plain primitives, while returned models can use marked types to communicate domain meaning.

## String-set enums: Literal for inputs, StrEnum for outputs

The SDK uses two patterns for string-set enums depending on the direction:

- **Inputs** use `typing.Literal`. Users pass plain strings (`time_period="DAY"`). The type drives autocomplete and static checking without forcing users to import an enum class. The type alias is exported (e.g., `BuilderVolumeTimePeriod`) so callers can annotate their own variables when they want to.
- **Outputs** use `enum.StrEnum`. Returned model fields surface the enum so users can compare against named members (`if status is UmaResolutionStatus.DISPUTED`) without typo risk on the right-hand side.

The split is principled: inputs are write-once at the call site and benefit from string ergonomics; outputs are read-many in user logic and benefit from named members.
