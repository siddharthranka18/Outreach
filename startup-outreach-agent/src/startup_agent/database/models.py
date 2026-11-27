"""SQLAlchemy 2.x declarative persistence models."""

from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import (
    Boolean,
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
    ats_boards: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_researched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    research_status: Mapped[Optional[str]] = mapped_column(String(30))
    research_contact: Mapped[Optional[str]] = mapped_column(Text)
    github_org_url: Mapped[Optional[str]] = mapped_column(Text)
    top_technical_contact_json: Mapped[Optional[str]] = mapped_column(Text)

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
    missing_ats_polls: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    canonical_job_key: Mapped[Optional[str]] = mapped_column(String(24), index=True)
    last_verified_open_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    description_simhash: Mapped[Optional[str]] = mapped_column(Text, index=True)
    repost_count: Mapped[Optional[int]] = mapped_column(Integer, server_default="0")
    is_ghost_job: Mapped[Optional[bool]] = mapped_column(Boolean, server_default="0")
    trust_score: Mapped[Optional[int]] = mapped_column(Integer)
    trust_flags_json: Mapped[Optional[str]] = mapped_column(Text)
    liveness_status: Mapped[Optional[str]] = mapped_column(Text, server_default="active")
    last_liveness_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rescued_by_content: Mapped[Optional[bool]] = mapped_column(Boolean, server_default="0")

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


class JobRelistModel(Base):
    """Record distinct repost identities and the first day each was observed."""

    __tablename__ = "job_relists"

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    identity: Mapped[str] = mapped_column(Text, primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AtsBoardModel(Base):
    """An imported public board or an observed board with polling history."""

    __tablename__ = "ats_boards"

    platform: Mapped[str] = mapped_column(Text, primary_key=True)
    board_token: Mapped[str] = mapped_column(Text, primary_key=True)
    company_name: Mapped[Optional[str]] = mapped_column(Text)
    website: Mapped[Optional[str]] = mapped_column(Text)
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    size_status: Mapped[Optional[str]] = mapped_column(Text)
    consecutive_failures: Mapped[Optional[int]] = mapped_column(Integer, server_default="0")
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    board_status: Mapped[Optional[str]] = mapped_column(Text, server_default="active")
    last_new_job_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    posting_keys_json: Mapped[Optional[str]] = mapped_column(Text)


class EmailDraftModel(Base):
    """Saved text and recipient for an individual job's outreach review."""

    __tablename__ = "email_drafts"

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    recipient: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    subject: Mapped[str] = mapped_column(String(150), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    listing_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    gmail_test_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    gmail_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    outreach_mode: Mapped[Optional[str]] = mapped_column(Text, server_default="standard_enquiry")
    attach_resume: Mapped[Optional[bool]] = mapped_column(Boolean, server_default="1")
    signal_json: Mapped[Optional[str]] = mapped_column(Text)

