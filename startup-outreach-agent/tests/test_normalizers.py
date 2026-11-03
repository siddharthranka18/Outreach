"""Tests for normalization utilities."""

import pytest
from startup_agent.utils.normalizers import (
    normalize_job_url,
    normalize_name,
    normalize_website,
)


def test_normalize_website_variations() -> None:
    """Test normalizing various website URL formats to canonical domain."""
    assert normalize_website("https://www.example.com/") == "example.com"
    assert normalize_website("http://example.com:80") == "example.com"
    assert normalize_website("https://example.com:443") == "example.com"
    assert normalize_website("www.acme.ai/about/") == "acme.ai/about"
    assert normalize_website("subdomain.company.org") == "subdomain.company.org"


def test_normalize_website_invalid() -> None:
    """Test that invalid website strings raise ValueError."""
    with pytest.raises(ValueError, match="must not be empty"):
        normalize_website("   ")
    with pytest.raises(ValueError, match="Invalid website URL"):
        normalize_website("http://")


def test_normalize_job_url_strips_tracking() -> None:
    """Test that tracking query parameters are cleanly stripped from job URLs."""
    raw_url = (
        "https://www.example.com/careers/job123/"
        "?utm_source=linkedin&utm_medium=cpc&ref=aggregator&keep_param=true#apply-section"
    )
    normalized = normalize_job_url(raw_url)
    assert "utm_source" not in normalized
    assert "utm_medium" not in normalized
    assert "ref" not in normalized
    assert "keep_param=true" in normalized
    assert "#apply-section" not in normalized
    assert normalized == "https://example.com/careers/job123?keep_param=true"


def test_normalize_job_url_invalid() -> None:
    """Test that empty or malformed job URLs raise ValueError."""
    with pytest.raises(ValueError, match="must not be empty"):
        normalize_job_url("")


def test_normalize_name() -> None:
    """Test company and job title normalization."""
    assert normalize_name("  Acme Robotics, Inc.  ") == "acme robotics"
    assert normalize_name("DeepMind Technologies Ltd") == "deepmind technologies"
    assert normalize_name("  Senior   Software   Engineer  ") == "senior software engineer"
    assert normalize_name("") == ""

