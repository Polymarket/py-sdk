# Perps Builder Codes

## Implementation plan

Port the final session-oriented API from Polymarket/ts-sdk#370, adapting names,
values, and lifecycle to the Python SDK's existing conventions.

1. Add typed builder status, attribution, approvals, receipts, earnings snapshots,
   and summaries. Use Decimal for rates and amounts and datetime for timestamps.
   Preserve builder terms on orders and expose builder_fee and total_fee on fills,
   including backward-compatible values for older responses.
2. Configure immutable builder attribution only on open_perps_session. Inherit
   terms for new orders and TP/SL legs; distinguish omitted per-order settings
   from explicit None opt-out. Preserve existing untagged signed payloads.
3. Add session.approve_builder_fee with optional builder, max_fee_rate, and
   approval_version. Resolve terms from the session and versions from saved
   approvals, including revoked records. The owner signs consent; the session
   reads account state. Do not automatically resubmit failed consent.
4. Add public builder-status lookup, session approval reads, snapshot-preserving
   earnings pagination and summary, and opt-in builder-fill subscriptions with
   independent handles and explicit reconnect reconciliation signals.
5. Extend representative model, serialization, signing, lifecycle, and public
   type-contract tests. Keep synthetic failures controlled; do not run live
   trading or approval mutations. Document runnable async consumer workflows.
6. Run uv-based lint, formatting, typing, tests, and package build. Perform a
   read-only adversarial SDK review of the complete diff, report findings in
   chat, fix actionable findings, rerun affected checks, and mark both PRs ready.

## Intended workflow

```python
from decimal import Decimal
from polymarket.models.perps import PerpsBuilderAttribution

# client is an initialized AsyncSecureClient.
async with await client.open_perps_session(
    builder_attribution=PerpsBuilderAttribution(
        address=builder_address,
        fee_rate=Decimal("0.0005"),
    ),
) as session:
    await session.approve_builder_fee()
```

Attribution is an order default, not fee consent. Approval uses the owner's
signer. Defaults are not stored in delegated credentials; provide them again
when resuming. Perps APIs are experimental and may change in any release.
