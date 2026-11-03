"""Pytest fixtures for isolated database testing."""

from typing import Generator
import pytest
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from startup_agent.database.engine import _enable_sqlite_foreign_keys
from startup_agent.database.models import Base
from startup_agent.database.repositories import CompanyRepository, JobRepository


@pytest.fixture(scope="function")
def isolated_engine() -> Generator[Engine, None, None]:
    """Provide an isolated, in-memory SQLite database engine for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    event.listen(engine, "connect", _enable_sqlite_foreign_keys)

    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(scope="function")
def session_factory(isolated_engine: Engine) -> sessionmaker[Session]:
    """Provide a session factory bound to the isolated test database."""
    return sessionmaker(
        bind=isolated_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


@pytest.fixture(scope="function")
def db_session(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """Provide an isolated transactional database session."""
    session = session_factory()
    try:
        yield session
        if session.is_active:
            try:
                session.commit()
            except Exception:
                session.rollback()
    finally:
        session.close()


@pytest.fixture(scope="function")
def company_repo(db_session: Session) -> CompanyRepository:
    """Provide an initialized CompanyRepository."""
    return CompanyRepository(session=db_session)


@pytest.fixture(scope="function")
def job_repo(db_session: Session) -> JobRepository:
    """Provide an initialized JobRepository."""
    return JobRepository(session=db_session)
