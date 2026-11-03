"""Tests for application initialization and discovery base contract."""

from pathlib import Path
from typing import List
import pytest
from startup_agent.config.settings import Settings
from startup_agent.discovery.base import BaseDiscoverySource
from startup_agent.main import initialize_app, main
from startup_agent.models.company import Company


def test_initialize_app_returns_settings() -> None:
    """Test that initialize_app loads settings and configures logging cleanly."""
    settings = initialize_app()
    assert isinstance(settings, Settings)
    assert len(settings.sources) >= 3


def test_main_exit_code() -> None:
    """Test that main() executes without error and returns 0."""
    exit_code = main()
    assert exit_code == 0


def test_discovery_base_contract() -> None:
    """Test that concrete classes must implement the discover method."""

    class IncompleteSource(BaseDiscoverySource):
        pass

    with pytest.raises(TypeError):
        IncompleteSource(name="incomplete")  # type: ignore[abstract]

    class MockSource(BaseDiscoverySource):
        def discover(self) -> List[Company]:
            return [
                Company(
                    company_name="Mock Corp",
                    website="https://mock.example",
                    source_name=self.name,
                    source_url="https://mock.example/dir",
                )
            ]

    source = MockSource(name="mock_source", enabled=True)
    assert source.is_enabled() is True
    discovered = source.discover()
    assert len(discovered) == 1
    assert discovered[0].company_name == "Mock Corp"

