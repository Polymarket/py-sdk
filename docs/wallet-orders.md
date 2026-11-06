# Wallet-wide orders

An authenticated Deposit Wallet owner or non-revoked session signer can list
live orders across the wallet, including orders placed by other signers.
Only the wallet owner can cancel orders across the wallet.

```python
for page in client.list_wallet_open_orders(session_keys=[session_address]):
    for order in page.items:
        print(order.id, order.signer_address, order.owner)

cancellation = client.cancel_wallet_orders(order_ids=[order_id])
print(cancellation.canceled, cancellation.not_canceled)

client.cancel_wallet_orders(all=True)
```

`list_wallet_open_orders` returns `Paginator[WalletOpenOrder]`. Optional
`market`, `asset_id`, and `session_keys` filters select orders. At most 50 signer
addresses can be selected. A short or empty page can continue; iteration stops
only when the server's continuation cursor is empty. Page size is controlled
by the server.

`WalletOpenOrder.owner` is an API-key identifier when disclosed, or `None` when
withheld. `signer_address` identifies the owner or session signer that placed
the order. Prices and sizes are `Decimal` values. Timestamps are timezone-aware
`datetime` values. `expires_at` is `None` when the order has no expiration.

Supply either 1–1,000 canonical order hashes through `order_ids`, or explicitly
choose `all=True`. The method returns the existing `CancelOrdersResponse`:
successful IDs in `canceled`, and unsuccessful IDs with reasons in
`not_canceled`. It does not split requests or retry cancellations automatically.
Read wallet orders after an uncertain outcome before deciding whether to retry.
Existing cancellation methods keep their API-key scope.

The async clients use the same methods and models:

```python
async for order in async_client.list_wallet_open_orders().iter_items():
    print(order.id, order.signer_address)
await async_client.cancel_wallet_orders(all=True)
```

The server must deploy and enable wallet-wide cancellation before it is
available. An unavailable endpoint's rejection is preserved; the SDK does not
fall back to another endpoint. Read-only-key-only authentication is outside
this change.
