"""Company domain model."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from startup_agent.utils.normalizers import normalize_name, normalize_website


@dataclass
class Company:
    """Represents a discovered startup company entity."""

    company_name: str
    website: str
    source_name: str
    source_url: str
    id: Optional[int] = None
    employee_count: Optional[str] = None
    industry: Optional[str] = None
    location: Optional[str] = None
    funding_stage: Optional[str] = None
    careers_url: Optional[str] = None
    hiring_status: Optional[str] = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_verified_at: Optional[datetime] = None
    discovered_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        """Validate core required attributes."""
        if not self.company_name or not self.company_name.strip():
            raise ValueError("company_name must not be empty")
        if not self.website or not self.website.strip():
            raise ValueError("website must not be empty")

    @property
    def normalized_name(self) -> str:
        """Return the canonical lowercase name."""
        return normalize_name(self.company_name)

    @property
    def normalized_website(self) -> str:
        """Return the canonical normalized website domain/path."""
        return normalize_website(self.website)
