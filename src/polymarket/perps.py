"""Perps trading session types.

Open a session with :meth:`polymarket.AsyncSecureClient.open_perps_session`.
"""

from polymarket._internal.perps_session import PerpsSession
from polymarket.models.perps.notifications import (
    PerpsNotificationEntry,
    PerpsNotificationsPage,
    PerpsNotificationsPaginator,
)
from polymarket.models.perps.results import (
    PerpsOrderPlacement,
    PerpsPlacedTpSlOrder,
    PerpsPlacedTpSlOrders,
)

__all__ = [
    "PerpsNotificationEntry",
    "PerpsNotificationsPage",
    "PerpsNotificationsPaginator",
    "PerpsOrderPlacement",
    "PerpsPlacedTpSlOrder",
    "PerpsPlacedTpSlOrders",
    "PerpsSession",
]
