"""Database engine creation and connection lifecycle."""

import sqlite3
from typing import Optional
from sqlalchemy import Engine, create_engine, event
from startup_agent.config.settings import Settings


def _enable_sqlite_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
    """Enforce foreign key constraints on SQLite connections."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()


def create_db_engine(
    database_url: Optional[str] = None,
    echo: bool = False,
) -> Engine:
    """Create a configured SQLAlchemy Engine.

    Args:
        database_url: Connection string. If None, reads from application Settings.
        echo: Whether to log generated SQL queries.

    Returns:
        Engine: Initialized SQLAlchemy engine.
    """
    if database_url is None:
        settings = Settings.load()
        database_url = settings.database_url

    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(
        database_url,
        echo=echo,
        connect_args=connect_args,
        future=True,
    )

    if database_url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)

    return engine

