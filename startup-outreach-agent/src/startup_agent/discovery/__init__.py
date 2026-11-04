"""Discovery foundation, adapters, and pipeline orchestration."""

from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.discovery.direct_ats import DirectAtsDiscoverySource
from startup_agent.discovery.pipeline import DiscoveryPipeline, DiscoverySummary, run_discovery_pipeline
from startup_agent.discovery.top_startups import TopStartupsDiscoverySource
from startup_agent.discovery.y_combinator import YCombinatorDiscoverySource

__all__ = [
    "BaseDiscoverySource",
    "DiscoveryResult",
    "YCombinatorDiscoverySource",
    "TopStartupsDiscoverySource",
    "DirectAtsDiscoverySource",
    "DiscoveryPipeline",
    "DiscoverySummary",
    "run_discovery_pipeline",
]
