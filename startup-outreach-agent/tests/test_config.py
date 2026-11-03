"""Tests for settings and configuration loading."""

from pathlib import Path
import pytest
from startup_agent.config.settings import Settings, SourceConfig


def test_settings_default_values(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test that default settings are loaded when no .env is present."""
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = Settings.load(base_dir=tmp_path)
    assert settings.app_env == "development"
    assert settings.log_level == "INFO"
    assert settings.database_url == "sqlite:///data/processed/outreach.db"
    assert settings.sources == []


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test that environment variables correctly override defaults."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/outreach")

    settings = Settings.load(base_dir=tmp_path)
    assert settings.app_env == "production"
    assert settings.log_level == "DEBUG"
    assert settings.database_url == "postgresql://user:pass@localhost:5432/outreach"


def test_sources_yaml_loading(tmp_path: Path) -> None:
    """Test that sources are correctly read from a YAML file."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    sources_yaml = config_dir / "sources.yaml"
    sources_yaml.write_text(
        """
version: "1.0"
sources:
  - name: "test_source"
    display_name: "Test Source"
    type: "directory"
    enabled: true
    description: "A test directory"
    url: "https://example.com"
""",
        encoding="utf-8",
    )

    settings = Settings.load(base_dir=tmp_path)
    assert len(settings.sources) == 1
    source = settings.sources[0]
    assert isinstance(source, SourceConfig)
    assert source.name == "test_source"
    assert source.display_name == "Test Source"
    assert source.type == "directory"
    assert source.enabled is True
    assert source.url == "https://example.com"

