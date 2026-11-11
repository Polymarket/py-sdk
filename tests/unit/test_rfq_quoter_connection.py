# pyright: reportPrivateUsage=false
"""The RFQ quoter keeps its session across dropped connections."""

import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import cast

import pytest
from _bearer import async_test_session
from eth_account import Account
from eth_account.signers.local import LocalAccount
from websockets.asyncio.server import ServerConnection, serve

from polymarket._internal.rfq import RfqQuoterSession
from polymarket.errors import ConnectionLostError
from polymarket.rfq import RfqExecutionUpdateEvent
from polymarket.types import EvmAddress

Handler = Callable[[ServerConnection], Awaitable[None]]


@asynccontextmanager
async def ws_server(handler: Handler) -> AsyncGenerator[str, None]:
    server = await serve(handler, host="127.0.0.1", port=0)
    try:
        port = next(iter(server.sockets)).getsockname()[1]
        yield f"ws://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()


def _quoter_session(url: str) -> RfqQuoterSession:
    signer = cast(LocalAccount, Account.create())
    return RfqQuoterSession(
        chain_id=137,
        session=async_test_session(),
        exchange=EvmAddress("0x0000000000000000000000000000000000000001"),
        headers=None,
        logger=None,
        signer=signer,
        url=url,
        wallet=EvmAddress(signer.address),
        wallet_type="EOA",
    )


def _execution_update(rfq_id: str) -> str:
    return json.dumps({"type": "RFQ_EXECUTION_UPDATE", "rfq_id": rfq_id, "status": "CONFIRMED"})


def test_dropped_connection_reconnects_and_reauthenticates() -> None:
    auth_frames: list[dict[str, object]] = []

    async def handler(ws: ServerConnection) -> None:
        auth_frames.append(json.loads(await ws.recv()))
        await ws.send(json.dumps({"type": "auth", "success": True}))
        if len(auth_frames) == 1:
            await ws.close(code=1011, reason="restarting")
            return
        await ws.send(_execution_update("rfq-after-reconnect"))
        await ws.wait_closed()

    async def run() -> RfqExecutionUpdateEvent:
        async with ws_server(handler) as url:
            session = await _quoter_session(url).open()
            try:
                event = await asyncio.wait_for(session.__anext__(), timeout=5.0)
            finally:
                await session.close()
            return cast(RfqExecutionUpdateEvent, event)

    event = asyncio.run(run())
    assert event.rfq_id == "rfq-after-reconnect"
    assert len(auth_frames) == 2
    assert all(frame["type"] == "auth" for frame in auth_frames)


def test_policy_close_ends_the_session() -> None:
    connections = 0

    async def handler(ws: ServerConnection) -> None:
        nonlocal connections
        connections += 1
        await ws.recv()
        await ws.send(json.dumps({"type": "auth", "success": True}))
        await ws.close(code=1008, reason="policy violation")

    async def run() -> RfqQuoterSession:
        async with ws_server(handler) as url:
            session = await _quoter_session(url).open()
            with pytest.raises(ConnectionLostError):
                await asyncio.wait_for(session.__anext__(), timeout=5.0)
            await asyncio.sleep(0.5)
            return session

    session = asyncio.run(run())
    assert session.closed
    assert connections == 1
