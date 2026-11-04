"""Tests for discovery adapters and pipeline orchestration with mocked HTTP."""

from unittest.mock import MagicMock
import httpx
import pytest
from sqlalchemy.orm import Session

from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.discovery.direct_ats import DirectAtsDiscoverySource
from startup_agent.discovery.pipeline import DiscoveryPipeline
from startup_agent.discovery.top_startups import TopStartupsDiscoverySource
from startup_agent.discovery.y_combinator import YCombinatorDiscoverySource
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient


MOCK_YC_ALGOLIA_RESPONSE = {
    "hits": [
        {
            "name": "RoboFlow",
            "slug": "roboflow",
            "website": "https://roboflow.com",
            "team_size": 45,
            "stage": "Series A",
            "batch": "Summer 2020",
            "industry": "Artificial Intelligence",
            "all_locations": "Des Moines, IA, USA",
            "isHiring": True,
        },
        {
            # Malformed hit: missing website and slug
            "name": "Anonymous Stealth",
            "team_size": 2,
        },
        {
            "name": "Databricks Partner",
            "slug": "db-partner",
            "website": None,  # Will fallback to YC slug URL
            "team_size": 10,
            "stage": "Seed",
            "batch": "Winter 2023",
            "industry": "Data Infrastructure",
            "isHiring": False,
        },
    ]
}

MOCK_TOP_STARTUPS_HTML = """
<!DOCTYPE html>
<html>
<body>
<div class="col-12 infinite-item">
    <div class="card card-body" id="item-card-filter">
        <a href="https://www.synthetica.ai/?utm_source=topstartups.io" id="startup-website-link">
            <h7>Synthetica AI</h7>
        </a>
        <a href="https://jobs.ashbyhq.com/synthetica/12345" id="startup-website-link">
            <h5 id="job-title">Machine Learning Intern</h5>
        </a>
        <h7><i class="fas fa-map-marker-alt"></i> San Francisco / Remote</h7>
        <h7><i class="fas fa-briefcase"></i> Experience: Not listed</h7>
        <span class="badge" id="company-size-tags">11-50 employees</span>
    </div>
</div>
</body>
</html>
"""

MOCK_ASHBY_JSON = {
    "jobs": [
        {
            "id": "ashby-job-001",
            "title": "Software Engineer Intern",
            "employmentType": "Internship",
            "location": "Remote",
            "jobUrl": "https://jobs.ashbyhq.com/synthetica/ashby-job-001",
            "publishedAt": "2026-10-15T12:00:00.000Z",
            "descriptionPlain": "Build robotics software and foundation models.",
        }
    ]
}


def test_yc_adapter_parsing() -> None:
    """Test that YCombinatorDiscoverySource correctly parses Algolia hits."""
    mock_client = MagicMock(spec=HttpClient)
    # 1st call for AlgoliaOpts regex (return minimal script)
    mock_html_resp = MagicMock(spec=httpx.Response)
    mock_html_resp.text = 'window.AlgoliaOpts = {"app":"TEST_APP","key":"TEST_KEY"};'
    mock_client.get.return_value = mock_html_resp

    # 2nd call for Algolia search POST
    mock_post_resp = MagicMock(spec=httpx.Response)
    mock_post_resp.json.return_value = MOCK_YC_ALGOLIA_RESPONSE
    mock_client.post.return_value = mock_post_resp

    adapter = YCombinatorDiscoverySource(http_client=mock_client, max_companies=10)
    result = adapter.discover()

    assert isinstance(result, DiscoveryResult)
    assert len(result.companies) == 2  # Malformed stealth entry omitted
    assert result.companies[0].company_name == "RoboFlow"
    assert result.companies[0].website == "https://roboflow.com"
    assert result.companies[0].employee_count == "45"
    assert result.companies[0].hiring_status == "Actively Hiring"
    assert result.companies[1].company_name == "Databricks Partner"
    assert "https://www.ycombinator.com/companies/db-partner" in result.companies[1].website


def test_top_startups_adapter_parsing() -> None:
    """Test that TopStartupsDiscoverySource extracts company and linked job."""
    mock_client = MagicMock(spec=HttpClient)
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.text = MOCK_TOP_STARTUPS_HTML
    mock_client.get.return_value = mock_resp

    adapter = TopStartupsDiscoverySource(http_client=mock_client)
    result = adapter.discover()

    assert len(result.companies) == 1
    company = result.companies[0]
    assert company.company_name == "Synthetica AI"
    assert "utm_source" not in company.website
    assert company.employee_count == "11-50 employees"

    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.job_title == "Machine Learning Intern"
    assert job.job_url == "https://jobs.ashbyhq.com/synthetica/12345"
    assert "Remote" in str(job.location)


def test_direct_ats_adapter_parsing() -> None:
    """Test that DirectAtsDiscoverySource extracts jobs via Ashby endpoint."""
    mock_client = MagicMock(spec=HttpClient)
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.json.return_value = MOCK_ASHBY_JSON
    mock_client.get.return_value = mock_resp

    targets = [
        {
            "platform": "ashby",
            "board_token": "synthetica",
            "company_name": "Synthetica AI",
            "website": "https://synthetica.ai",
        }
    ]
    adapter = DirectAtsDiscoverySource(targets=targets, http_client=mock_client)
    result = adapter.discover()

    assert len(result.companies) == 1
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.job_title == "Software Engineer Intern"
    assert job.source_job_id == "ashby-job-001"
    assert job.employment_type == "Internship"


def test_pipeline_orchestration_and_persistence(db_session: Session) -> None:
    """Test end-to-end pipeline execution with database persistence and company ID resolution."""

    class MockAdapter(BaseDiscoverySource):
        def discover(self) -> DiscoveryResult:
            company = Company(
                company_name="Aura Systems",
                website="https://aurasystems.io",
                source_name="mock",
                source_url="https://mock.example/aura",
            )
            job = Job(
                job_title="Robotics Intern",
                job_url="https://aurasystems.io/careers/robotics",
                source_name="mock",
                company_website="https://aurasystems.io",
                company_name="Aura Systems",
            )
            return DiscoveryResult(companies=[company], jobs=[job])

    pipeline = DiscoveryPipeline(
        session=db_session,
        custom_adapters=[MockAdapter(name="mock_source", enabled=True)],
    )
    summary = pipeline.run()

    assert summary.sources_attempted == 1
    assert summary.sources_successful == 1
    assert summary.companies_discovered == 1
    assert summary.companies_inserted == 1
    assert summary.jobs_discovered == 1
    assert summary.jobs_inserted == 1

    # Run again with same data to verify deduplication and update tracking
    summary_2 = pipeline.run()
    assert summary_2.companies_inserted == 0
    assert summary_2.companies_updated == 1
    assert summary_2.jobs_inserted == 0
    assert summary_2.jobs_updated == 1


def test_pipeline_error_isolation(db_session: Session) -> None:
    """Verify that a failing source does not terminate other sources."""

    class FailingAdapter(BaseDiscoverySource):
        def discover(self) -> DiscoveryResult:
            raise httpx.ConnectError("Network unreachable")

    class WorkingAdapter(BaseDiscoverySource):
        def discover(self) -> DiscoveryResult:
            return DiscoveryResult(
                companies=[
                    Company(
                        company_name="Resilient AI",
                        website="https://resilient.ai",
                        source_name="working",
                        source_url="https://resilient.ai",
                    )
                ]
            )

    pipeline = DiscoveryPipeline(
        session=db_session,
        custom_adapters=[
            FailingAdapter(name="failing_source"),
            WorkingAdapter(name="working_source"),
        ],
    )
    summary = pipeline.run()

    assert summary.sources_attempted == 2
    assert summary.sources_successful == 1
    assert len(summary.sources_failed) == 1
    assert summary.sources_failed[0][0] == "failing_source"
    assert summary.companies_discovered == 1
    assert summary.companies_inserted == 1

