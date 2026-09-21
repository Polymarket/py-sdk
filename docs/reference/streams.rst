Price Streams
#############

Use ``AsyncSecureClient.subscribe`` with explicit symbols to receive recent
history and live prices. Cryptocurrency pairs are canonical lowercase USD
symbols such as ``btcusd``; TWAPs use a fixed 60-second window. Equity symbols
are trimmed and lowercased.

Crypto prices and crypto TWAPs are quoted in USD. Equity and forex prices use
the instrument's quote currency: ``usdjpy`` is JPY per USD and ``usdcad`` is
CAD per USD.

Prices are exact ``Decimal`` values and timestamps are timezone-aware UTC
``datetime`` values. History events have ``type="subscribe"`` and a sequence
of price points in ``payload.data``. Live events have ``type="update"`` and
``payload.value``. A shared subscription begins with the current local history.

``seq`` is scoped to one channel on one connection and resets on reconnect.
Subscriptions exceeding 64 distinct filters can span multiple connections,
whose sequence values may interleave. It is not a global event identifier.
Use the subscription as an async context manager to release it when finished.

Subscription Specs
==================

.. autoclass:: polymarket.streams.CryptoPriceSpec
   :members:

.. autoclass:: polymarket.streams.CryptoTwapPriceSpec
   :members:

.. autoclass:: polymarket.streams.EquityPriceSpec
   :members:

Events and Payloads
===================

.. automodule:: polymarket.models.price_events
   :members:
   :undoc-members:
   :show-inheritance:
