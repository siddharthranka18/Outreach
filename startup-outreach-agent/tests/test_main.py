"""Tests for application initialization and discovery base contract."""

from pathlib import Path
from typing import List
import pytest
from startup_agent.config.settings import Settings
from startup_agent.discovery.base import BaseDiscoverySource
from startup_agent.discovery.pipeline import DiscoverySummary
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


def test_hosted_daily_leaves_shortlist_and_funnel_to_delivery(monkeypatch, isolated_engine):
    settings = Settings(career_ops_upgrades={"enabled": True})
    deadlines = {}

    def discover(*, settings, deadline):
        deadlines["discovery"] = deadline
        return DiscoverySummary(sources_attempted=1, sources_successful=1)

    def publish(session, settings, *, enquiries_only, deadline):
        deadlines["delivery"] = deadline
        return 0

    def unexpected_funnel(*args, **kwargs):
        pytest.fail("Hosted delivery should calculate the funnel once, after ranking.")

    monkeypatch.setattr("startup_agent.main.initialize_app", lambda: settings)
    monkeypatch.setattr("startup_agent.main.create_db_engine", lambda url: isolated_engine)
    monkeypatch.setattr("startup_agent.main.run_discovery_pipeline", discover)
    monkeypatch.setattr("startup_agent.main.publish_hosted_shortlist", publish)
    monkeypatch.setattr("startup_agent.main.source_funnel", unexpected_funnel)
    assert main(["--hosted-daily"]) == 0
    assert deadlines["delivery"] - deadlines["discovery"] == 440


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

