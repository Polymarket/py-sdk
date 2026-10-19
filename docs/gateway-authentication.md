# Bearer authentication migration

`SecureClient.create` and `AsyncSecureClient.create` now open bearer sessions.
Their `credentials` property returns `BearerCredentials(access_token, refresh_token)`
instead of `ApiKeyCreds(key, secret, passphrase)`. Both fields are required when
restoring a session. Restoration refreshes once before returning, validating the
pair with the server even when the saved Access Token has not expired. The sync and async clients share request construction and
have the same authentication methods; realtime subscriptions remain async-only.

```python
from dataclasses import asdict
from polymarket import SecureClient

# load_credentials, save_credentials and load_private_key belong to your app.
with SecureClient.create(
    private_key=load_private_key(),
    credentials=load_credentials(),  # saved L2 object or bearer pair
    on_credentials_changed=lambda pair: save_credentials(asdict(pair)),
) as client:
    save_credentials(asdict(client.credentials))
    orders = client.list_open_orders().first_page()
```

Keep existing `private_key` and optional `wallet` configuration. Omitting `wallet`
retains Deposit Wallet resolution, deployment checks and deployment. Authentication
puts the resolved wallet on the challenge. Login signs the server's typed data and
sends only the challenge ID and signature. Signed trading orders are still required.
Perps credentials and sessions remain separate.

To migrate without a new wallet signature, call the public client explicitly:

```python
from dataclasses import asdict
from polymarket import ApiKeyCreds, PublicClient, SecureClient

with PublicClient() as public:
    pair = public.migrate_credentials(
        credentials=ApiKeyCreds.model_validate(load_legacy_credentials()),
        signer=signer_address,
        wallet=wallet_address,  # optional for direct migration
    )

save_credentials(asdict(pair))
with SecureClient.create(
    private_key=load_private_key(), wallet=wallet_address, credentials=pair,
) as client:
    orders = client.list_open_orders().first_page()
```

The public method is `migrate_credentials` (Python's spelling of
`migrateCredentials`). It computes a timestamped HMAC locally; the L2 secret is
never transmitted. A rejected migration raises `RequestRejectedError`, returns no
secure client, and does not invoke the persistence callback. Save migrated
credentials only after successful creation. For a fresh login without creating a
secure client, use `public.login(signer=account, wallet=wallet_address,
verification_token=token)` with an `eth_account` local account.

Refresh happens before Access Token expiry. Timer, HTTP and socket consumers share
one in-flight operation. Refresh adopts the complete returned pair and then invokes
`on_credentials_changed`; sync and async callbacks are supported in both client
modes. Callback exceptions are reported by a redacted warning and do not undo an
accepted refresh or stop subsequent renewal. Callbacks should persist credentials
promptly; a sync client's async callback runs in a dedicated thread, so it must not
use resources bound to the caller's event loop. Irrecoverable refresh failures stop
renewal and surface on the next authenticated operation. Transient refresh failures
have three attempts with bounded backoff.

For ordinary authenticated requests, only `401 expired_access_token` triggers one
HTTP replay, with the same method, body, query and timeout. Unrelated 401s and
replay failures propagate. Canceling one async request does not cancel another
caller's refresh. Every async socket uses only an Access Token. Renewal waits for its protocol acknowledgement; failed
renewals retain the previous accepted deadline and subscriptions. Reconnection uses
the current shared session. The existing combo requester REST workflow remains
available; external sessions do not gain first-party requester socket privileges.

Always close clients, preferably with a context manager. `end_authentication()`
logs out using the active Access Token, cleans up the client, and returns a public
client. It stops renewal before attempting server revocation, using the last
adopted Access Token when it is still usable even if proactive refresh failed.
Logout makes at most three revocation attempts for transient failures. If the
bearer expires locally or logout returns `expired_access_token`, it can recover
credentials once, with at most three refresh attempts. These recovery credentials
are used only for revocation; they do not revive the client or invoke persistence
callbacks. Revocation/refresh failures propagate even though local cleanup always
runs. Logout does not immediately revoke already-issued Access Tokens.
`close()` cleans up local resources without logging out, allowing persisted
credentials to be restored later.

Legacy builder and relayer authorization remains necessary for the workflows that
require it. Public reads and legacy direct transports remain available during the
migration. Authenticated prediction requests use the configured gateway; the
existing builder workflow keeps its required builder authentication. Do not infer
builder identity or gasless quota continuity from `client_id` alone.

Release still requires deployed authentication contracts, same-connection Combos
and realtime price renewal support, external-origin CORS/edge access, and verified
builder identity and gasless quota continuity. Synthetic protocol tests establish
SDK behavior; they are not production end-to-end verification.
