"""Job domain model."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from startup_agent.utils.normalizers import normalize_job_url, normalize_name


@dataclass
class Job:
    """Represents an advertised job posting linked to a company."""

    company_id: int
    job_title: str
    job_url: str
    source_name: str
    id: Optional[int] = None
    description: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    experience_level: Optional[str] = None
    source_job_id: Optional[str] = None
    posted_at: Optional[datetime] = None
    first_seen_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_seen_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    status: str = "open"
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        """Validate required fields."""
        if not self.job_title or not self.job_title.strip():
            raise ValueError("job_title must not be empty")
        if not self.job_url or not self.job_url.strip():
            raise ValueError("job_url must not be empty")
        if not self.source_name or not self.source_name.strip():
            raise ValueError("source_name must not be empty")

    @property
    def normalized_title(self) -> str:
        """Return canonical lowercase job title."""
        return normalize_name(self.job_title)

    @property
    def normalized_job_url(self) -> str:
        """Return canonical tracking-stripped job URL."""
        return normalize_job_url(self.job_url)

