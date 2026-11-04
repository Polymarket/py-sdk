# Directional collateral return

Directional lines trade as YES/NO markets: YES is ABOVE the line, NO is BELOW.
A wallet holding ABOVE on a lower line and BELOW on a higher line can merge
that pair for 1 pUSD plus YES on each real bucket between the two lines.
Splitting reverses this operation by consuming the pUSD and those bucket YES
positions. Buckets and Void are inventory instruments with no order book.

## Discover, select and merge

Use the synchronous client for scripts, notebooks and bots:

```python
from polymarket import SecureClient

# Use the existing wallet holding the positions and its owner's signing key.
# Supply environment and api_key for your configured network and wallet transport.
with SecureClient.create(
    private_key=private_key,
    wallet=wallet_address,
    environment=environment,
    api_key=api_key,
) as client:
    client.setup_trading_approvals()
    pairs = client.find_directional_pairs()
    if not pairs:
        raise RuntimeError("No mergeable directional pair found")

    selected = pairs[0]  # Inspect candidates before choosing one.
    transaction = client.merge_directional(
        selected.above_position_id,
        selected.below_position_id,
        amount=selected.amount,
    )
    receipt = transaction.wait()
    print(receipt.transaction_hash)

    # Reverse precisely that amount, using the same IDs in either order.
    reverse = client.split_directional(
        selected.below_position_id,
        selected.above_position_id,
        amount=selected.amount,
    )
    reverse.wait()
```

The client is bound to the account wallet. Supply the signer address explicitly
for EOA execution; omitting `wallet` selects the default Deposit Wallet.
Deposit Wallet, Safe and Proxy reuse wallet-batch execution; EOA calls are direct
and require gas. Approval setup already includes pUSD spending and position
operator approval for the Router and waits internally for submitted approvals.

`find_directional_pairs(event_id=...)` optionally limits discovery to an on-chain
event. It scans all pages of this wallet's indexed holdings, includes small
holdings by removing the display dust filter, and reads fresh candidate balances
on chain. Each immutable result has `above_position_id`, `below_position_id`,
`event_id`, `low_line`, `high_line`, `amount` and `expected_pusd`.
Candidates can share inventory: rediscover after each confirmed merge. The
result is a set of alternatives, not an optimal allocation or executable batch plan.
Unindexed holdings cannot be discovered; known IDs can still be executed directly.

`merge_directional(position_id_a, position_id_b, *, amount="max")` and
`split_directional(...)` accept decimal threshold position IDs in either order.
The SDK derives the event and line ordinals and rejects incompatible pairs before
signing. Both IDs must belong to the same event, and ABOVE's line must be lower
than BELOW's line. No separate metadata request or manual decoding is required.

Amounts use integer **six-decimal base units**: `1_000_000` is one pair.
Omitting `amount` or passing `"max"` selects the fresh minimum of the two wings
for a merge. A split is capped by pUSD and every middle-bucket YES balance.
Zero, negative, non-integer, boolean and out-of-uint256 amounts are rejected.
Preparation does not reserve inventory; a later balance change can still cause
a transaction to revert atomically.

If you acquire the wings through orders, wait for on-chain fill settlement
before merging. Order acceptance alone is insufficient. Portfolio and activity
indexing can lag behind confirmation. Position listing quantities are `Decimal`
shares; transaction amounts and pair candidate quantities are integer base units.

## Async applications

`AsyncSecureClient` offers the same method names and keyword arguments, using
native async transport:

```python
pairs = await client.find_directional_pairs()
if pairs:
    selected = pairs[0]
    transaction = await client.merge_directional(
        selected.above_position_id,
        selected.below_position_id,
        amount=selected.amount,
    )
    receipt = await transaction.wait()
```

## Prepare without submitting

Python preparation returns the existing immutable `TransactionCall` object,
ready for `execute_transaction` or custom signing. It reads balances and encodes
an unsigned call; it never signs or submits. There is no signing generator to drive.

```python
call = client.prepare_merge_directional(position_id_a, position_id_b, amount=1_000_000)
print(call.to, call.data, call.value)
# Submit later, after any application review:
transaction = client.execute_transaction(calls=[call])
transaction.wait()
```

`prepare_split_directional` and all event, conversion and threshold operations
have matching preparation methods. Async clients await preparation and execution.
Every prepared call encodes a fixed amount, including when requested with `"max"`.
Prepare again if balances change. Each directional operation is one atomic call.

## Buckets and thresholds

```python
from polymarket import derive_directional_bucket_positions

bucket = derive_directional_bucket_positions(event_id=event_id, bucket_index=2)
client.split_position(condition_id=bucket.condition_id, amount=1_000_000).wait()
client.merge_positions(condition_id=bucket.condition_id, amount=1_000_000).wait()
```

| Intent | Method |
| --- | --- |
| Derive one bucket or Void's YES/NO IDs | `derive_directional_bucket_positions(event_id=..., bucket_index=...)` |
| Derive a line's ABOVE/BELOW IDs | `derive_directional_threshold_positions(event_id=..., line=...)` |
| Inspect an ID locally | `decode_position_id(position_id)` |
| Split/merge one bucket, Void or line YES/NO set | `split_position` / `merge_positions` with `condition_id` |
| Redeem an eligible outcome | `redeem_positions(position_id=...)` |
| Create every bucket YES, including Void | `split_event_positions(event_id=..., amount=...)` |
| Merge that complete set into pUSD | `merge_event_positions(event_id=..., amount="max")` |
| Turn bucket NO into the other buckets' YES | `convert_position(position_id=..., amount="max")` |
| Combine bucket YES into a threshold side | `compose_threshold(event_id=..., line=..., side="above", amount="max")` |
| Return a threshold side to its bucket basket | `decompose_threshold(event_id=..., line=..., side="below", amount="max")` |

`side` accepts plain `"above"` / `"below"` strings or `ThresholdSide` members.
Returned sides and instrument kinds are enums. All identifier derivation is local.
Line indices are ordinal boundaries, not scalar point totals. On-chain event IDs
are bytes29 (zero-padded bytes32 also accepted), distinct from catalog event IDs.
Real buckets have indices `0..B-1`; Void is index `B`. Whole-event sets and BELOW
baskets include Void. ABOVE baskets and directional middle-bucket sets exclude it.

Directional condition-based split/merge/redeem needs no market listing.
Bucket metadata can be resolved through
`client.list_markets(position_ids=[bucket.yes_position_id]).first_page()`.
Unfiltered discovery excludes buckets and Void. Portfolio display still depends
on indexed holdings and their metadata; a successful on-chain merge does not
establish portfolio visibility or a collateral-return PnL policy.

## Activity and validation

Activity feeds model `DIRECTIONAL_MERGE` / `DIRECTIONAL_SPLIT` as event-level rows
with `event_id`, `pairs` and collateral `amount`. `THRESHOLD_COMPOSE` /
`THRESHOLD_DECOMPOSE` carry `condition_id`, `line`, `side` and `shares`, with no
collateral movement. Quantities in activity models are `Decimal`. Missing labels
remain `None`. Filters accept the dedicated activity names; `MERGE` / `SPLIT`
do not include the corresponding directional operations.

Run local verification and the credential-free example:

```sh
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest -m "not integration"
uv build
uv run python -m examples.directional_positions
```

A metered staging test seeds two line complete sets, merges a pair, checks balances
and indexed activity/holdings, reverses it and restores the original inventory.
Use a dedicated wallet with at least 2 pUSD and no positions on the tested lines
or middle bucket, a deployed event with at least three buckets, and an explicit
staging environment/RPC. See `.env.example` for configuration names.

```sh
POLYMARKET_RUN_METERED_TESTS=1 uv run pytest tests/integration/test_directional_live.py -v
```

Missing credentials or metered opt-in skips the test; a skip is not a live pass.
Partial or ambiguous failures may leave inventory; inspect confirmed transactions
before rerunning. These tests do not establish trading/fill settlement. Verify
selector acceptance, sponsorship and wallet policy in staging before release.
Live Python staging execution is unverified without the required configuration.
Directional integration into the collateral-return planning service remains P2.

Parity source: [TypeScript PR #428](https://github.com/Polymarket/ts-sdk/pull/428).
