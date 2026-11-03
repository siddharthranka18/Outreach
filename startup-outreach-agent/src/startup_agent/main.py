"""Application entry point and initialization logic for Startup Job Outreach Agent."""

import sys
from sqlalchemy import text
from startup_agent.config.settings import Settings
from startup_agent.database.engine import create_db_engine
from startup_agent.utils.logging_config import setup_logging


def verify_database_connectivity(database_url: str) -> bool:
    """Verify that the database can be reached and queried.

    Args:
        database_url: Target database connection string.

    Returns:
        bool: True if connection succeeded.
    """
    engine = create_db_engine(database_url)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar()
        return result == 1


def initialize_app() -> Settings:
    """Bootstrap configuration, logging, and database connectivity.

    Returns:
        Settings: Loaded and validated application settings.
    """
    settings = Settings.load()
    logger = setup_logging(log_level=settings.log_level, logs_dir=settings.logs_dir)

    logger.info("Initializing Startup Job Outreach Agent...")
    logger.info("Running in environment: '%s'", settings.app_env)
    logger.info("Active log level: '%s'", settings.log_level)
    logger.info("Database URL: '%s'", settings.database_url)

    # Verify database connection
    try:
        if verify_database_connectivity(settings.database_url):
            logger.info("Database connectivity verified successfully.")
    except Exception as exc:
        logger.error("Database connection check failed: %s", exc)
        raise

    enabled_sources = [s.display_name for s in settings.sources if s.enabled]
    logger.info(
        "Configured sources (%d total, %d enabled): %s",
        len(settings.sources),
        len(enabled_sources),
        ", ".join(enabled_sources) if enabled_sources else "None",
    )
    return settings


def main() -> int:
    """Run the initialization workflow.

    Returns:
        int: Process exit code (0 for success, non-zero for failure).
    """
    try:
        settings = initialize_app()
        print("\n" + "=" * 60)
        print("   STARTUP JOB OUTREACH AGENT - FOUNDATION & DB READY")
        print("=" * 60)
        print(f" Environment   : {settings.app_env}")
        print(f" Log Level     : {settings.log_level}")
        print(f" Database URL  : {settings.database_url}")
        print(f" Base Directory: {settings.base_dir}")
        print(f" Configured Sources ({len(settings.sources)}):")
        for source in settings.sources:
            status = "ENABLED " if source.enabled else "DISABLED"
            print(f"   [{status}] {source.display_name:<22} ({source.type})")
        print("=" * 60)
        print("Database connected. Persistence layer ready for Prompt 3.\n")
        return 0
    except Exception as exc:
        print(f"Initialization failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
