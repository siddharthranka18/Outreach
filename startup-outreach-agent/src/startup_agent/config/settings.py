"""Application settings and configuration loader."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import os
import yaml
from dotenv import load_dotenv


@dataclass(frozen=True)
class SourceConfig:
    """Configuration for an individual discovery source."""

    name: str
    display_name: str
    type: str
    enabled: bool
    description: str
    url: Optional[str] = None


@dataclass(frozen=True)
class Settings:
    """Central application settings."""

    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite:///data/processed/outreach.db"
    base_dir: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent.parent.parent.parent
    )
    sources: List[SourceConfig] = field(default_factory=list)

    @property
    def config_dir(self) -> Path:
        """Path to configuration directory."""
        return self.base_dir / "config"

    @property
    def data_dir(self) -> Path:
        """Path to application data directory."""
        return self.base_dir / "data"

    @property
    def logs_dir(self) -> Path:
        """Path to application logs directory."""
        return self.base_dir / "logs"

    @classmethod
    def load(
        cls,
        base_dir: Optional[Path] = None,
        env_file: Optional[Path] = None,
        sources_file: Optional[Path] = None,
    ) -> "Settings":
        """Load settings from environment variables and sources.yaml.

        Args:
            base_dir: Optional override for the root application directory.
            env_file: Optional override path for the .env file.
            sources_file: Optional override path for sources.yaml.

        Returns:
            Settings: Initialized configuration instance.
        """
        if base_dir is None:
            # Resolves from src/startup_agent/config/settings.py -> repository root
            base_dir = Path(__file__).resolve().parent.parent.parent.parent

        if env_file is None:
            env_file = base_dir / ".env"

        # Load environment variables if .env is present
        if env_file.exists():
            load_dotenv(dotenv_path=env_file)
        else:
            load_dotenv()

        app_env = os.getenv("APP_ENV", "development")
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        database_url = os.getenv("DATABASE_URL", "sqlite:///data/processed/outreach.db")

        # Load sources configuration
        if sources_file is None:
            sources_file = base_dir / "config" / "sources.yaml"

        sources: List[SourceConfig] = []
        if sources_file.exists():
            with open(sources_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                raw_sources = data.get("sources", [])
                for item in raw_sources:
                    sources.append(
                        SourceConfig(
                            name=item.get("name", ""),
                            display_name=item.get("display_name", item.get("name", "")),
                            type=item.get("type", "unknown"),
                            enabled=bool(item.get("enabled", False)),
                            description=item.get("description", ""),
                            url=item.get("url"),
                        )
                    )

        return cls(
            app_env=app_env,
            log_level=log_level,
            database_url=database_url,
            base_dir=base_dir,
            sources=sources,
        )

