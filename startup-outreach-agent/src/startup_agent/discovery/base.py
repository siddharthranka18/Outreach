"""Base discovery interface for startup sources."""

from abc import ABC, abstractmethod
from typing import List
from startup_agent.models.company import Company


class BaseDiscoverySource(ABC):
    """Abstract base class defining the contract for future source discovery adapters."""

    def __init__(self, name: str, enabled: bool = True) -> None:
        """Initialize the discovery source.

        Args:
            name: Identifier for the source adapter.
            enabled: Whether this source is active.
        """
        self.name = name
        self.enabled = enabled

    @abstractmethod
    def discover(self) -> List[Company]:
        """Execute discovery logic to find and return companies.

        Returns:
            List[Company]: Discovered and normalized Company instances.

        Raises:
            NotImplementedError: Must be implemented by concrete adapters.
        """
        raise NotImplementedError

    def is_enabled(self) -> bool:
        """Check if the source adapter is enabled."""
        return self.enabled

