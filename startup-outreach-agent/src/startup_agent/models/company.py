"""Company domain model."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Company:
    """Represents a discovered startup company entity."""

    company_name: str
    website: str
    source_name: str
    source_url: str
    employee_count: Optional[str] = None
    industry: Optional[str] = None
    location: Optional[str] = None
    funding_stage: Optional[str] = None
    careers_url: Optional[str] = None
    hiring_status: Optional[str] = None
    discovered_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        """Validate core required attributes."""
        if not self.company_name or not self.company_name.strip():
            raise ValueError("company_name must not be empty")
        if not self.website or not self.website.strip():
            raise ValueError("website must not be empty")

