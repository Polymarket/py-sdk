"""Experimental Perps trading session types.

Experimental: This API may change in a breaking way in any release, including
patch releases.

Open a session with :meth:`polymarket.AsyncSecureClient.open_perps_session`.
"""

from polymarket._internal.perps_session import PerpsSession
from polymarket.models.perps.results import (
    PerpsOrderPlacement,
    PerpsPlacedTpSlOrder,
    PerpsPlacedTpSlOrders,
)

__all__ = [
    "PerpsOrderPlacement",
    "PerpsPlacedTpSlOrder",
    "PerpsPlacedTpSlOrders",
    "PerpsSession",
]
