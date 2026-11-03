"""SQLAlchemy 2.x declarative persistence models."""

from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy entities."""
    pass


class CompanyModel(Base):
    """SQLAlchemy persistence model for discovered startups."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    website: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_website: Mapped[str] = mapped_column(
        String(512), nullable=False, unique=True, index=True
    )
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    employee_count: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    funding_stage: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    careers_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    hiring_status: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    jobs: Mapped[List["JobModel"]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<CompanyModel(id={self.id}, name='{self.company_name}', "
            f"website='{self.normalized_website}')>"
        )


class JobModel(Base):
    """SQLAlchemy persistence model for advertised jobs."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_title: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    employment_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    experience_level: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    job_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    normalized_job_url: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_job_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    posted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(50), default="open", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    company: Mapped["CompanyModel"] = relationship(back_populates="jobs")

    __table_args__ = (
        Index("ix_jobs_company_source_job_id", "company_id", "source_name", "source_job_id"),
        Index("ix_jobs_company_normalized_url", "company_id", "normalized_job_url"),
    )

    def __repr__(self) -> str:
        return (
            f"<JobModel(id={self.id}, title='{self.job_title}', "
            f"company_id={self.company_id}, status='{self.status}')>"
        )

