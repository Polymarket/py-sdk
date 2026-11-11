Clients
#######

The synchronous clients are the default interface for request and response
workflows. Async clients provide equivalent async methods and the realtime
features that require persistent connections.

Pagination limits
-----------------

List methods return a paginator. Iterate over its pages when you need to
check completeness, or use ``iter_items()`` to flatten the returned rows.
When a supported pagination depth prevents checking for another page,
the final accessible full page has ``limit_reached=True``. Automatic page
and item iteration then stop normally. ``has_more`` and ``next_cursor``
are preserved: the flag means completeness is unknown, not that additional
rows definitely exist. Explicitly resuming an over-limit cursor raises
``PaginationLimitError`` before sending a request. Automatic iteration raises
``UnexpectedResponseError`` if a response reports more items without a next
cursor or repeats a cursor already requested in that walk, after yielding the
pages fetched so far. Request failures still propagate normally.

Eager exports require an explicit ``limit``. ``limit=None`` collects all
accessible rows, but a depth-limited result is not known to be complete.
Pandas exports set ``df.attrs["polymarket_limit_reached"] = True`` and
Arrow exports set schema metadata ``b"polymarket_limit_reached": b"true"``.
They also retain the conservative ``polymarket_truncated`` marker: it can
mean rows were omitted by the caller's count limit or that completeness
could not be established at the depth limit. Converting a depth-limited
``Page`` directly preserves these same markers. Polars has no stable
per-frame metadata; depth-limited exports emit a ``UserWarning`` instead.

Sessions
--------

A secure client authenticates with a session. ``SecureClient.create`` signs in
with the private key, or restores saved credentials without a new wallet
signature. Saved ``BearerCredentials`` restore the session they belong to, and
saved ``ApiKeyCreds`` are exchanged for a new session.

Save ``client.credentials`` after creation, and every pair passed to
``on_credentials_changed``, to restore the session later. Both tokens are
secrets. The client renews its session before the access token expires, also
while it is idle. Call ``refresh_credentials()`` to renew on your own schedule.

Saved credentials stop working after ``end_authentication()`` or when the
session expires without renewal. Creating a client from them then raises
``RequestRejectedError`` instead of signing in again:

.. code-block:: python

   from polymarket import BearerCredentials, RequestRejectedError, SecureClient


   def connect(private_key: str, saved: BearerCredentials | None) -> SecureClient:
       try:
           return SecureClient.create(
               private_key=private_key,
               credentials=saved,
               on_credentials_changed=save_credentials,
           )
       except RequestRejectedError:
           if saved is None:
               raise
           return SecureClient.create(
               private_key=private_key, on_credentials_changed=save_credentials
           )

.. autoclass:: polymarket.BearerCredentials

Platform API Keys
-----------------

A Platform API Key identifies your application. Pass it as ``platform_api_key``
on a server: sign-in, credential exchanges, and account and market requests
carry it, and the sessions it opens stay bound to your application. Session
renewal, ``end_authentication()``, order heartbeats, Perps, and realtime
connections use their own authentication only.

.. code-block:: python

   import os

   from polymarket import PlatformApiKey, SecureClient

   client = SecureClient.create(
       private_key=private_key,
       platform_api_key=PlatformApiKey(os.environ["POLYMARKET_PLATFORM_API_KEY"]),
   )

Keep the key on the server. To sign in browsers or other untrusted clients,
serve them challenges from a server route with
``PublicClient.create_platform_challenge``: check that the caller may sign in as
the requested signer, then return the challenge unchanged. The caller signs it
and completes sign-in itself.

A Platform API Key does not authorize gasless wallet operations. Those still
need a builder or relayer key passed as ``api_key``.

.. autoclass:: polymarket.PlatformApiKey

PublicClient
------------

.. autoclass:: polymarket.PublicClient
   :members:
   :undoc-members:
   :member-order: bysource

SecureClient
------------

.. autoclass:: polymarket.SecureClient
   :members:
   :undoc-members:
   :member-order: bysource

AsyncPublicClient
-----------------

.. autoclass:: polymarket.AsyncPublicClient
   :members:
   :undoc-members:
   :member-order: bysource

AsyncSecureClient
-----------------

.. autoclass:: polymarket.AsyncSecureClient
   :members:
   :undoc-members:
   :member-order: bysource
