"""Exception types raised by the Polymarket SDK."""


class PolymarketError(Exception):
    """Base class for errors raised by the Polymarket SDK."""


class UserInputError(PolymarketError):
    """Error raised when input fails SDK validation before a request is sent."""


class UnexpectedResponseError(PolymarketError):
    """Error raised when a response does not match the expected shape."""


class TransportError(PolymarketError):
    """Error raised when a network or runtime transport failure occurs."""


class ConnectionLostError(PolymarketError):
    """Error raised when a live connection ends without the SDK requesting it.

    ``code`` is the WebSocket close code (RFC 6455) and ``reason`` the close
    reason provided by the peer, empty when none was sent. Operations in
    flight when the connection was lost have an indeterminate outcome.
    """

    def __init__(self, message: str, *, code: int, reason: str) -> None:
        super().__init__(message)
        self.code = code
        self.reason = reason


class RequestRejectedError(PolymarketError):
    """Error raised when a request receives a non-success status.

    ``code`` is the machine-readable error code from the response body;
    ``None`` when the response does not provide one.

    ``retry_after`` is the server-suggested delay in seconds before retrying,
    taken from the ``Retry-After`` response header or a ``retry_after_seconds``
    field in the response body; ``None`` when the response provides neither.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int,
        code: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.retry_after = retry_after


class AutoCancelDailyLimitError(RequestRejectedError):
    """Error raised when arming auto-cancel is rejected because the account
    reached its daily auto-cancel trigger limit.

    Arming is rejected until the daily counter resets at the next UTC
    midnight; clearing an existing schedule is always allowed.
    """


class RateLimitError(PolymarketError):
    """Error raised when a request is rejected because of rate limits."""


class TimeoutError(PolymarketError):
    """Error raised when a wait operation exceeds its allotted polling time."""


class TransactionFailedError(PolymarketError):
    """Error raised when a submitted transaction reaches a terminal failure state."""


class CancelledSigningError(PolymarketError):
    """Error raised when the user cancels a required wallet signing action."""


class InsufficientLiquidityError(PolymarketError):
    """Error raised when resting liquidity cannot satisfy the requested execution."""


class SigningError(PolymarketError):
    """Error raised when the SDK cannot produce a signature or auth payload."""


class InsufficientAllowanceError(PolymarketError):
    """Error raised when the on-chain allowance is insufficient for the order amount."""
