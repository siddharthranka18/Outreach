"""Base discovery interface and result container for startup sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Union
from startup_agent.models.company import Company
from startup_agent.models.job import Job


@dataclass
class DiscoveryResult:
    """Standard container holding entities collected during a discovery execution."""

    companies: List[Company] = field(default_factory=list)
    jobs: List[Job] = field(default_factory=list)


class BaseDiscoverySource(ABC):
    """Abstract base class defining the contract for startup and job discovery adapters."""

    def __init__(self, name: str, enabled: bool = True) -> None:
        """Initialize discovery adapter.

        Args:
            name: Unique identifier for the source adapter.
            enabled: Whether this source is active for execution.
        """
        self.name = name
        self.enabled = enabled

    @abstractmethod
    def discover(self) -> Union[DiscoveryResult, List[Company]]:
        """Execute discovery logic to extract companies and/or jobs.

        Returns:
            Union[DiscoveryResult, List[Company]]: Extracted entities.

        Raises:
            NotImplementedError: Must be implemented by concrete adapters.
        """
        raise NotImplementedError

    def is_enabled(self) -> bool:
        """Check if the source adapter is enabled."""
        return self.enabled
