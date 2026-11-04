"""Application entry point and CLI for Startup Job Outreach Agent."""

import argparse
import sys
from typing import List, Optional
from sqlalchemy import text
from startup_agent.config.settings import Settings
from startup_agent.database.engine import create_db_engine
from startup_agent.discovery.pipeline import DiscoverySummary, run_discovery_pipeline
from startup_agent.utils.logging_config import setup_logging


def verify_database_connectivity(database_url: str) -> bool:
    """Verify that the database can be reached and queried."""
    engine = create_db_engine(database_url)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar()
        return result == 1


def initialize_app() -> Settings:
    """Bootstrap configuration, logging, and database connectivity."""
    settings = Settings.load()
    logger = setup_logging(log_level=settings.log_level, logs_dir=settings.logs_dir)

    logger.info("Initializing Startup Job Outreach Agent...")
    logger.info("Running in environment: '%s'", settings.app_env)
    logger.info("Active log level: '%s'", settings.log_level)
    logger.info("Database URL: '%s'", settings.database_url)

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


def print_discovery_report(summary: DiscoverySummary) -> None:
    """Pretty-print the discovery execution statistics."""
    print("\n" + "=" * 65)
    print("                STARTUP DISCOVERY RUN REPORT                    ")
    print("=" * 65)
    print(f" Execution Duration      : {summary.duration_seconds:.2f} seconds")
    print(f" Sources Attempted       : {summary.sources_attempted}")
    print(f" Sources Successful      : {summary.sources_successful}")
    if summary.sources_failed:
        print(f" Sources Failed          : {len(summary.sources_failed)}")
        for src_name, error_msg in summary.sources_failed:
            print(f"   * [{src_name}]: {error_msg}")
    else:
        print(" Sources Failed          : 0")
    print("-" * 65)
    print(f" Companies Discovered    : {summary.companies_discovered}")
    print(f"   - New Insertions      : {summary.companies_inserted}")
    print(f"   - Existing Updated    : {summary.companies_updated}")
    print("-" * 65)
    print(f" Advertised Jobs Found   : {summary.jobs_discovered}")
    print(f"   - New Insertions      : {summary.jobs_inserted}")
    print(f"   - Existing Updated    : {summary.jobs_updated}")
    print("=" * 65 + "\n")


def main(argv: Optional[List[str]] = None) -> int:
    """Parse arguments and execute application routine."""
    parser = argparse.ArgumentParser(
        description="Startup Job Outreach Agent - Discovery & Outreach CLI"
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Execute multi-source discovery pipeline to extract and persist companies and jobs.",
    )

    # Use empty list if argv is None to safely handle programmatic calls without reading sys.argv
    cli_args = argv if argv is not None else []
    args = parser.parse_args(cli_args)

    try:
        settings = initialize_app()

        if args.discover:
            print("\n>>> Launching multi-source discovery pipeline...")
            summary = run_discovery_pipeline(settings=settings)
            print_discovery_report(summary)

            if summary.all_failed:
                print("ERROR: All attempted discovery sources failed.", file=sys.stderr)
                return 1
            return 0

        # Default mode: diagnostic status report
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
            print(f"   [{status}] {source.display_name:<25} ({source.type})")
        print("=" * 60)
        print("Use 'python run.py --discover' to execute the discovery pipeline.\n")
        return 0

    except Exception as exc:
        print(f"Initialization or execution failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
