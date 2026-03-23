"""
WHAIP – Network bootstrap
Initialises the P2P node and announces the local peer to the WHP network.
"""

import logging
from typing import Optional

logger = logging.getLogger("whaip.network.bootstrap")

# Well-known WHP bootstrap nodes (placeholder addresses)
BOOTSTRAP_NODES = [
    "/dns4/bootstrap.whaip.io/tcp/4001/p2p/QmPlaceholder1",
    "/dns4/bootstrap2.whaip.io/tcp/4001/p2p/QmPlaceholder2",
]

class NetworkBootstrap:
    """Handles initial peer discovery and announces the local WHAIP node."""

    def __init__(self, config: dict):
        self.config = config
        self._node  = None   # libp2p Host instance

    async def start(self):
        """
        Create a libp2p host, connect to bootstrap nodes, and start listening.
        No-op if network section is missing from config.
        """
        # TODO: import libp2p
        # TODO: generate or load a persistent peer key from ~/.whaip/peer.key
        # TODO: create Host with TCP transport + Noise security + YAMUX mux
        # TODO: connect to each node in BOOTSTRAP_NODES
        # TODO: start mDNS for local peer discovery
        pass

    async def stop(self):
        """Gracefully shut down the libp2p host."""
        # TODO: await self._node.close() if running
        pass

    def get_peer_id(self) -> Optional[str]:
        """Return the local peer ID string, or None if not started."""
        # TODO: return str(self._node.get_id()) if self._node else None
        pass

    def get_multiaddrs(self) -> list[str]:
        """Return the list of multiaddresses this node is reachable on."""
        # TODO: return [str(a) for a in self._node.get_addrs()]
        pass
