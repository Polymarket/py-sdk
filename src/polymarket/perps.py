"""Experimental Perps trading session types.

Experimental: This API may change in a breaking way in any release, including
patch releases.

Open a session with :meth:`polymarket.AsyncSecureClient.open_perps_session`.
"""

from polymarket._internal.perps_session import PerpsSession
from polymarket.models.perps.notifications import (
    PerpsNotificationEntry,
    PerpsNotificationsPage,
    PerpsNotificationsPaginator,
)
from polymarket.models.perps.orders import (
    PerpsCancelOrderErrorCode,
    PerpsCancelOrderRejection,
    PerpsCancelOrderResult,
    PerpsCancelOrderSuccess,
)
from polymarket.models.perps.requests import PerpsCancelRetryOptions
from polymarket.models.perps.results import (
    PerpsOrderPlacement,
    PerpsPlacedTpSlOrder,
    PerpsPlacedTpSlOrders,
)

__all__ = [
    "PerpsNotificationEntry",
    "PerpsNotificationsPage",
    "PerpsNotificationsPaginator",
    "PerpsCancelOrderErrorCode",
    "PerpsCancelOrderRejection",
    "PerpsCancelOrderResult",
    "PerpsCancelOrderSuccess",
    "PerpsCancelRetryOptions",
    "PerpsOrderPlacement",
    "PerpsPlacedTpSlOrder",
    "PerpsPlacedTpSlOrders",
    "PerpsSession",
]
