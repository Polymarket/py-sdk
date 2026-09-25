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
``PaginationLimitError`` before sending a request. Request failures still
propagate normally.

Eager exports require an explicit ``limit``. ``limit=None`` collects all
accessible rows, but a depth-limited result is not known to be complete.
Pandas exports set ``df.attrs["polymarket_limit_reached"] = True`` and
Arrow exports set schema metadata ``b"polymarket_limit_reached": b"true"``.
They also retain the conservative ``polymarket_truncated`` marker: it can
mean rows were omitted by the caller's count limit or that completeness
could not be established at the depth limit. Converting a depth-limited
``Page`` directly preserves these same markers. Polars has no stable
per-frame metadata; depth-limited exports emit a ``UserWarning`` instead.

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
