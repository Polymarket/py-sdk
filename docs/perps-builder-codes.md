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

## Order defaults and overrides

Orders inherit the session's immutable attribution. Pass another
`PerpsBuilderAttribution` to override it or `builder_attribution=None` to opt out.
Omitting the keyword and explicitly passing `None` have different meanings.
The same choice applies to generated TP/SL exits and position TP/SL placements.
For batches, set `builder_attribution` on each `PerpsOrderRequest`.

```python
await session.place_order(
    instrument_id=instrument_id, side="BUY", quantity="0.01", time_in_force="ioc"
)
await session.place_order(
    instrument_id=instrument_id, side="BUY", quantity="0.01", time_in_force="ioc",
    builder_attribution=None,
)
```

Approval accepts optional keyword overrides for `builder`, `max_fee_rate`, and
`approval_version`. An omitted version is the saved version plus one (initially
1), including when an earlier approval was revoked. Explicit versions skip the
read. `max_fee_rate="0"` revokes consent for new orders. Failed submissions are
not automatically signed or submitted again. A session without configured
attribution must provide explicit `builder` and `max_fee_rate`.

## Reporting and live receipts

`AsyncPublicClient.fetch_perps_builder_status(address=...)` and the equivalent
`AsyncSecureClient` method report builder availability. Approval reads,
`list_builder_earnings`, and `fetch_builder_earnings_summary` belong to the
session and report on its authenticated account, independent of order defaults.

```python
page = await session.list_builder_earnings().first_page()
snapshot = page.snapshot
assert snapshot is not None
summary = await session.fetch_builder_earnings_summary(
    start=snapshot.start, end=snapshot.end, as_of_sequence=snapshot.as_of_sequence
)
```

Every fetched earnings page retains its reporting window and cutoff, including
empty pages. Pagination can be iterated repeatedly; `from_cursor` resumes the
cursor's original snapshot. `from_cursor(None)` ends iteration. Windows are at
most 90 days; omitted bounds use the server's seven-day default. The summary's
active approval count reflects current consent independently of its cutoff.

```python
async with await session.subscribe_builder_fills() as receipts:
    async for event in receipts:
        if event.type == "resync":
            # Reconcile using list_builder_earnings and deduplicate by earning_id.
            continue
        for receipt in event.payload:
            print(receipt.earning_id, receipt.builder_fee)
```

Each handle closes independently. The final close unsubscribes the channel;
closing the session terminates all its handles. There is no initial snapshot.
Reconnects and locally dropped frames signal reconciliation; sparse engine
sequence numbers alone do not imply missing receipts. Reconciliation and
receipt deduplication remain application responsibilities.

Orders and acknowledgements expose saved `builder` terms. Fills expose
`builder_fee` and `total_fee`, while `fee` remains the exchange fee. Older fills
without builder fields report zero builder fee and an exact derived total.
