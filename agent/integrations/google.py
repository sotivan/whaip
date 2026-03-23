"""
WHAIP – Google OAuth integration
Provides sign-in with Google for Supabase auth or direct Google API access.
Disabled silently if google_client_id or google_client_secret are empty.
"""

import logging
from typing import Optional
from .base import BaseIntegration

logger = logging.getLogger("whaip.integrations.google")

class GoogleAuthClient(BaseIntegration):

    def __init__(self, config: dict):
        super().__init__(config, required_keys=["google_client_id", "google_client_secret"])
        self._flow        = None   # google_auth_oauthlib.flow.Flow
        self._credentials = None   # google.oauth2.credentials.Credentials
        self._token_cache_path = "~/.whaip/google_token.json"

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def setup(self):
        """Initialize OAuth flow. Loads cached token if available."""
        # TODO: if not self.enabled → return
        # TODO: from google_auth_oauthlib.flow import Flow
        # TODO: build OAuth2 flow with client_id, client_secret, scopes
        # TODO: try to load cached credentials from self._token_cache_path
        pass

    def teardown(self):
        """Persist credentials to disk."""
        # TODO: save self._credentials to self._token_cache_path if valid
        pass

    # ── Auth flow ──────────────────────────────────────────────────────────

    async def authorize(self) -> bool:
        """
        Run the OAuth2 authorization flow (opens browser, waits for callback).
        Returns True on success, False on failure or if disabled.
        """
        # TODO: if not self.enabled → return False
        # TODO: generate authorization URL, open in webview via IPC
        # TODO: wait for redirect with auth code
        # TODO: exchange code for tokens → self._credentials
        # TODO: persist token, return True
        pass

    def is_authorized(self) -> bool:
        """Return True if valid (non-expired) credentials are loaded."""
        # TODO: return self._credentials is not None and not self._credentials.expired
        pass

    async def refresh_token(self):
        """Refresh the access token using the stored refresh token."""
        # TODO: from google.auth.transport.requests import Request
        # TODO: self._credentials.refresh(Request())
        pass

    # ── API helpers ────────────────────────────────────────────────────────

    def get_auth_headers(self) -> Optional[dict]:
        """Return HTTP Authorization headers for Google API calls."""
        # TODO: if not self.is_authorized() → return None
        # TODO: return {"Authorization": f"Bearer {self._credentials.token}"}
        pass
