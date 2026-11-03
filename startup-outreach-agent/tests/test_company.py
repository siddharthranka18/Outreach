"""Tests for the Company domain model."""

from datetime import datetime, timezone
import pytest
from startup_agent.models.company import Company


def test_company_creation_minimal() -> None:
    """Test creating a company with minimal required fields."""
    company = Company(
        company_name="Acme Robotics",
        website="https://acmerobotics.example",
        source_name="y_combinator",
        source_url="https://ycombinator.com/companies/acme",
    )
    assert company.company_name == "Acme Robotics"
    assert company.website == "https://acmerobotics.example"
    assert company.source_name == "y_combinator"
    assert company.source_url == "https://ycombinator.com/companies/acme"
    assert company.employee_count is None
    assert company.industry is None
    assert company.location is None
    assert company.funding_stage is None
    assert company.careers_url is None
    assert company.hiring_status is None
    assert isinstance(company.discovered_at, datetime)
    assert company.discovered_at.tzinfo == timezone.utc


def test_company_creation_full() -> None:
    """Test creating a company with all optional fields provided."""
    company = Company(
        company_name="Cognitive AI",
        website="https://cognitive.ai",
        source_name="top_startups",
        source_url="https://topstartups.io/company/cognitive",
        employee_count="11-50",
        industry="Artificial Intelligence",
        location="San Francisco, CA",
        funding_stage="Seed",
        careers_url="https://cognitive.ai/careers",
        hiring_status="Actively Hiring",
    )
    assert company.employee_count == "11-50"
    assert company.industry == "Artificial Intelligence"
    assert company.location == "San Francisco, CA"
    assert company.funding_stage == "Seed"
    assert company.careers_url == "https://cognitive.ai/careers"
    assert company.hiring_status == "Actively Hiring"


def test_company_invalid_name() -> None:
    """Test that empty company name raises ValueError."""
    with pytest.raises(ValueError, match="company_name must not be empty"):
        Company(
            company_name="   ",
            website="https://example.com",
            source_name="test",
            source_url="https://example.com/source",
        )


def test_company_invalid_website() -> None:
    """Test that empty website raises ValueError."""
    with pytest.raises(ValueError, match="website must not be empty"):
        Company(
            company_name="Valid Corp",
            website="",
            source_name="test",
            source_url="https://example.com/source",
        )

