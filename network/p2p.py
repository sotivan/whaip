"""
WHAIP – P2P messaging layer (WHP over libp2p)
Sends and receives WHP protocol messages between WHAIP peers.
"""

import logging
from typing import Callable, Awaitable, Optional

logger = logging.getLogger("whaip.network.p2p")

# libp2p protocol ID for WHP
WHP_PROTOCOL = "/whaip/whp/1.0.0"

class P2PNode:
    """
    Wraps a libp2p Host and exposes a simple send/receive API
    for WHP JSON messages between WHAIP peers.
    """

    def __init__(self, config: dict):
        self.config   = config
        self._host    = None   # libp2p Host (set by NetworkBootstrap)
        self._handler: Optional[Callable[[str, dict], Awaitable[None]]] = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def attach(self, host):
        """Attach to an already-started libp2p Host."""
        # TODO: self._host = host
        # TODO: host.set_stream_handler(WHP_PROTOCOL, self._stream_handler)
        pass

    async def stop(self):
        """Detach stream handler."""
        # TODO: remove WHP_PROTOCOL handler from host
        pass

    # ── Incoming messages ──────────────────────────────────────────────────

    def on_message(self, handler: Callable[[str, dict], Awaitable[None]]):
        """Register a coroutine to be called with (peer_id, payload) on receipt."""
        # TODO: self._handler = handler
        pass

    async def _stream_handler(self, stream):
        """Internal: read a WHP message from an incoming libp2p stream."""
        # TODO: read bytes from stream, parse JSON
        # TODO: call self._handler(peer_id, payload)
        pass

    # ── Outgoing messages ──────────────────────────────────────────────────

    async def send(self, peer_id: str, payload: dict):
        """
        Open a stream to `peer_id` and send a WHP JSON payload.
        No-op if host is not attached.
        """
        # TODO: stream = await self._host.new_stream(peer_id, [WHP_PROTOCOL])
        # TODO: serialize payload to JSON bytes, write to stream, close
        pass

    async def broadcast(self, payload: dict, peer_ids: list[str]):
        """Send the same payload to multiple peers concurrently."""
        # TODO: asyncio.gather(*[self.send(pid, payload) for pid in peer_ids])
        pass
