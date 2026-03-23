"""
WHAIP – Shared page registry
Tracks WHP "pages" (shared browser sessions) that peers can join or broadcast to.
"""

import logging
from typing import Optional

logger = logging.getLogger("whaip.network.pages")

class PageRegistry:
    """
    Maintains a registry of active WHP pages (shared sessions).
    Each page has a unique ID and a list of connected peer IDs.
    """

    def __init__(self, config: dict):
        self.config  = config
        self._pages: dict[str, dict] = {}   # page_id → {url, peers, owner}

    # ── Page lifecycle ─────────────────────────────────────────────────────

    def create_page(self, url: str, owner_peer_id: str) -> str:
        """
        Register a new shared page and return its unique page_id.
        """
        # TODO: generate uuid4 page_id
        # TODO: self._pages[page_id] = {"url": url, "owner": owner_peer_id, "peers": [owner_peer_id]}
        # TODO: return page_id
        pass

    def join_page(self, page_id: str, peer_id: str) -> bool:
        """
        Add a peer to an existing page.
        Returns False if the page does not exist.
        """
        # TODO: if page_id not in self._pages → return False
        # TODO: append peer_id to self._pages[page_id]['peers'] if not already present
        # TODO: return True
        pass

    def leave_page(self, page_id: str, peer_id: str):
        """Remove a peer from a page. Deletes the page if it becomes empty."""
        # TODO: remove peer_id from peers list
        # TODO: if peers empty → del self._pages[page_id]
        pass

    def get_page(self, page_id: str) -> Optional[dict]:
        """Return page metadata dict or None if not found."""
        # TODO: return self._pages.get(page_id)
        pass

    def list_pages(self) -> list[dict]:
        """Return all active pages as a list of metadata dicts."""
        # TODO: return list(self._pages.values())
        pass

    # ── Sync ───────────────────────────────────────────────────────────────

    async def broadcast_navigation(self, page_id: str, url: str, p2p_node):
        """
        Notify all peers in a page that the URL has changed.
        Uses the P2PNode to send a WHP 'navigate' action to each peer.
        """
        # TODO: page = self.get_page(page_id)
        # TODO: payload = {"action": "navigate", "text": url, "reason": "page sync"}
        # TODO: await p2p_node.broadcast(payload, page['peers'])
        pass
