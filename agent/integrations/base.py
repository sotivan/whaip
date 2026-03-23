"""
WHAIP – Base integration class
All integrations inherit from this to get consistent enable/disable semantics.
"""

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger("whaip.integrations")

class BaseIntegration(ABC):
    """
    Abstract base for optional third-party integrations.
    Subclasses are expected to:
      - set self.enabled = True in setup() if the required API key is present
      - silently no-op all public methods when self.enabled is False
    """

    def __init__(self, config: dict, required_keys: list[str]):
        self.config  = config
        self.enabled = all(config.get(k, "").strip() for k in required_keys)
        if not self.enabled:
            logger.info(
                "%s disabled (missing keys: %s)",
                self.__class__.__name__,
                [k for k in required_keys if not config.get(k, "").strip()],
            )

    @abstractmethod
    def setup(self):
        """Initialize the integration client. Called once at startup."""
        pass

    @abstractmethod
    def teardown(self):
        """Release resources. Called on clean shutdown."""
        pass
