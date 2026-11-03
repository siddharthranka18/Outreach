"""Database session factories and transaction context management."""

from contextlib import contextmanager
from typing import Generator, Optional
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker
from startup_agent.database.engine import create_db_engine


def create_session_factory(engine: Optional[Engine] = None) -> sessionmaker[Session]:
    """Create a configured sessionmaker bound to the given engine.

    Args:
        engine: SQLAlchemy Engine instance. If None, creates a default engine.

    Returns:
        sessionmaker[Session]: Factory producing new Session instances.
    """
    if engine is None:
        engine = create_db_engine()

    return sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


@contextmanager
def session_scope(
    session_factory: Optional[sessionmaker[Session]] = None,
) -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations.

    Args:
        session_factory: Optional factory to generate session.

    Yields:
        Session: Active SQLAlchemy session.
    """
    if session_factory is None:
        session_factory = create_session_factory()

    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

