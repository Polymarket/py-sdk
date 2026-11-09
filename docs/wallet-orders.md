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

client.cancel_all_wallet_orders()
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

Supply 1–1,000 canonical order hashes to `cancel_wallet_orders(order_ids=...)`,
or use `cancel_all_wallet_orders()` to cancel every live order across the wallet.
Both methods return the existing `CancelOrdersResponse`:
successful IDs in `canceled`, and unsuccessful IDs with reasons in
`not_canceled`. It does not split requests or retry cancellations automatically.
Read wallet orders after an uncertain outcome before deciding whether to retry.
Existing cancellation methods keep their API-key scope.

The async clients use the same methods and models:

```python
async for order in async_client.list_wallet_open_orders().iter_items():
    print(order.id, order.signer_address)
await async_client.cancel_all_wallet_orders()
```

The server must deploy and enable wallet-wide cancellation before it is
available. An unavailable endpoint's rejection is preserved; the SDK does not
fall back to another endpoint. Read-only-key-only authentication is outside
this change.

## Session-key authentication

Session-key authorization and revocation require the Deposit Wallet owner's
signature and a `BuilderApiKey` or `RelayerApiKey` supplied through `api_key`.
Ordinary account credentials authenticate trading and session-key listing;
they do not authorize or revoke session keys on their own.

Use the wallet owner's EOA address with a relayer key:

```python
from polymarket import RelayerApiKey, SecureClient, SessionKeyKnownScope

with SecureClient.create(
    private_key=owner_private_key,
    wallet=deposit_wallet,
    api_key=RelayerApiKey(key=relayer_key, address=owner_address),
) as owner:
    authorization = owner.authorize_session_key(
        address=session_address,
        scopes=(SessionKeyKnownScope.CLOB,),
    )
    print(authorization.session_key, authorization.transaction)
    owner.revoke_session_key(address=session_address)
```

The key's `address` must identify the wallet owner's EOA. The application
generates and protects the session private key. Authorization returns the
existing `AuthorizeSessionKeyResult` after transaction confirmation and active-key
registry readiness. Revocation returns `None` after registry removal makes the
key unusable; its transaction and order sweep may still be pending.

For builder credentials, use the same methods with this client configuration:

```python
from polymarket import BuilderApiKey, SecureClient

with SecureClient.create(
    private_key=owner_private_key,
    wallet=deposit_wallet,
    api_key=BuilderApiKey(
        key=builder_key,
        secret=builder_secret,
        passphrase=builder_passphrase,
    ),
) as owner:
    authorization = owner.authorize_session_key(address=session_address)
```

`AsyncSecureClient` accepts the same `api_key` values; await its authorization
and revocation methods. Scope and expiry defaults and return models are unchanged.
The selected environment must deploy and enable registration with the supplied
credential type. Authentication failures from older deployments are preserved.
