"""Unknown-frame reporting for realtime streams."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypeAlias

StreamName: TypeAlias = Literal[
    "clob_market",
    "clob_user",
    "perps_market",
    "perps_session",
    "rfq_quoter",
    "rtds",
    "sports",
]
"""Stream surface that received a frame."""


@dataclass(frozen=True, slots=True)
class UnknownFrame:
    """A realtime frame the SDK does not recognize.

    Servers may introduce new frame types ahead of a client release that
    understands them. Streams ignore such frames instead of failing the
    connection and report each one through the ``on_unknown_frame`` callback
    so consumers can observe (for example log) them.
    """

    frame: object
    """The raw frame as received, JSON-decoded but otherwise unvalidated."""

    stream: StreamName
    """The stream surface that received the frame."""


OnUnknownFrame: TypeAlias = Callable[[UnknownFrame], None]
"""Callback invoked for each frame a stream does not recognize.

Unknown frames never close the connection or end active subscriptions;
without a callback they are ignored. The SDK does not log them, so whether
and how to record them is up to the consumer.
"""


def report_unknown_frame(
    callback: OnUnknownFrame | None,
    logger: logging.Logger,
    *,
    frame: object,
    stream: StreamName,
) -> None:
    """Invoke the consumer's unknown-frame callback, isolating its errors."""
    if callback is None:
        return
    try:
        callback(UnknownFrame(frame=frame, stream=stream))
    except Exception:
        logger.exception("on_unknown_frame callback raised")
