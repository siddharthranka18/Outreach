"""Tests for discovery adapters and pipeline orchestration with mocked HTTP."""

from unittest.mock import MagicMock
import httpx
import pytest
from sqlalchemy.orm import Session

from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.discovery.andhra_startup_map import AndhraStartupMapDiscoverySource
from startup_agent.discovery.direct_ats import DirectAtsDiscoverySource, extract_ats_target
from startup_agent.discovery.pipeline import DiscoveryPipeline
from startup_agent.discovery.top_startups import TopStartupsDiscoverySource
from startup_agent.discovery.wellfound import WellfoundDiscoverySource
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

MOCK_WELLFOUND_HTML = """
<html><body>
<div class="mb-6 w-full rounded border bg-white">
  <div data-testid="startup-header">
    <a href="/company/tiny-india"><h2>Tiny India</h2></a>
    <span>11-50 Employees</span>
  </div>
  <div class="min-h-[50px] items-end">
    <a href="/jobs/123-backend-engineer-intern">Backend Engineer Intern</a>
    <span>Internship</span><span>Remote only • India</span><span>0 years of exp</span>
  </div>
  <div class="min-h-[50px] items-end">
    <a href="/jobs/456-senior-engineer">Senior Engineer</a>
    <span>Full-time</span><span>Remote only • India</span><span>7 years of exp</span>
  </div>
</div>
<div class="mb-6 w-full rounded border bg-white">
  <div data-testid="startup-header">
    <a href="/company/large-corp"><h2>Large Corp</h2></a>
    <span>201-500 Employees</span>
  </div>
  <div class="min-h-[50px] items-end">
    <a href="/jobs/789-software-intern">Software Intern</a>
    <span>Internship</span><span>India</span>
  </div>
</div>
</body></html>
"""

MOCK_WELLFOUND_JOB_HTML = """
<html><body>
<script type="application/ld+json">
{
  "@context": "http://schema.org/",
  "@type": "JobPosting",
  "title": "Backend Engineer Intern",
  "employmentType": "FULL_TIME",
  "hiringOrganization": {
    "@type": "Organization",
    "name": "Tiny India",
    "sameAs": "https://tiny.example"
  },
  "description": "<p>Build Python FastAPI services using PostgreSQL and Docker.</p>",
  "datePosted": "2026-11-05T09:43:19Z",
  "jobLocationType": "TELECOMMUTE",
  "applicantLocationRequirements": [{"@type": "Country", "name": "India"}],
  "experienceRequirements": {
    "@type": "OccupationalExperienceRequirements",
    "monthsOfExperience": 0
  }
}
</script>
</body></html>
"""

MOCK_ANDHRA_STARTUP_MAP_HTML = """
<html><body>
<div class="flex flex-col justify-between rounded-2xl border">
  <div>
    <div><img alt="Tiny AI" src="https://www.google.com/s2/favicons?domain=tiny.ai&amp;sz=64"/>
      <span class="font-bold">Tiny AI</span><span>Internship</span>
    </div>
    <h3><a href="/jobs/role/role-123">Backend Software Engineer Intern</a></h3>
    <div class="mt-2 text-xs"><span>Remote in India</span></div>
    <span>Engineering &amp; AI</span>
  </div>
  <a href="https://jobs.lever.co/tiny-ai/abc-123">Apply on Portal</a>
</div>
<div class="flex flex-col justify-between rounded-2xl border">
  <div><img alt="Hardware Co" src="https://www.google.com/s2/favicons?domain=hardware.example&amp;sz=64"/>
    <span class="font-bold">Hardware Co</span><span>Internship</span>
    <h3><a href="/jobs/role/role-456">Mechanical Engineer Intern</a></h3>
  </div>
  <a href="https://example.com/mechanical">Apply on Portal</a>
</div>
</body></html>
"""


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

    adapter = YCombinatorDiscoverySource(
        http_client=mock_client, max_companies=10, include_jobs=False
    )
    result = adapter.discover()

    assert isinstance(result, DiscoveryResult)
    assert len(result.companies) == 2  # Malformed stealth entry omitted
    assert result.companies[0].company_name == "RoboFlow"
    assert result.companies[0].website == "https://roboflow.com"
    assert result.companies[0].employee_count == "45"
    assert result.companies[0].hiring_status == "Actively Hiring"
    assert result.companies[1].company_name == "Databricks Partner"
    assert "https://www.ycombinator.com/companies/db-partner" in result.companies[1].website
    request_params = [
        call.kwargs["json_data"]["params"] for call in mock_client.post.call_args_list
    ]
    assert all("team_size%3C%3D200" in params for params in request_params)
    assert any("regions%3AIndia" in params for params in request_params)
    assert any("regions%3AFully+Remote" in params for params in request_params)


def test_yc_adapter_discovers_early_career_jobs() -> None:
    """YC company pages contribute internship records with full descriptions."""
    mock_client = MagicMock(spec=HttpClient)
    directory_response = MagicMock(spec=httpx.Response)
    directory_response.text = 'window.AlgoliaOpts = {"app":"TEST_APP","key":"TEST_KEY"};'

    jobs_response = MagicMock(spec=httpx.Response)
    jobs_response.text = """
    <html><body>
      <div class="flex flex-col">
        <div><a href="/companies/tiny-ai/jobs/job123-software-engineer-intern">Software Engineer Intern</a></div>
        <span>Remote</span><span>$2K monthly</span><span>Any</span>
      </div>
      <div class="flex flex-col">
        <div><a href="/companies/tiny-ai/jobs/job999-senior-engineer">Senior Engineer</a></div>
        <span>Remote</span><span>5+ years</span>
      </div>
    </body></html>
    """

    detail_response = MagicMock(spec=httpx.Response)
    detail_response.text = """
    <html><head><meta name="description" content="Build Python FastAPI services and AI agents as a software engineering intern."></head></html>
    """

    mock_client.get.side_effect = [directory_response, jobs_response, detail_response]
    algolia_response = MagicMock(spec=httpx.Response)
    algolia_response.json.return_value = {
        "hits": [
            {
                "name": "Tiny AI",
                "slug": "tiny-ai",
                "website": "https://tiny.ai",
                "team_size": 8,
                "stage": "Seed",
                "batch": "W26",
                "industry": "Artificial Intelligence",
                "all_locations": "Remote",
                "isHiring": True,
            }
        ]
    }
    mock_client.post.return_value = algolia_response

    result = YCombinatorDiscoverySource(
        http_client=mock_client, max_companies=10
    ).discover()

    assert len(result.companies) == 1
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.job_title == "Software Engineer Intern"
    assert job.location == "Remote"
    assert job.employment_type == "Internship"
    assert "FastAPI" in str(job.description)
    assert job.source_job_id == "job123"


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


def test_wellfound_adapter_filters_for_small_early_career_startups() -> None:
    """Wellfound contributes only size-verified early-career startup listings."""
    mock_client = MagicMock(spec=HttpClient)
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.text = MOCK_WELLFOUND_HTML
    detail_response = MagicMock(spec=httpx.Response)
    detail_response.text = MOCK_WELLFOUND_JOB_HTML
    mock_client.get.side_effect = [mock_response, detail_response]

    result = WellfoundDiscoverySource(
        http_client=mock_client,
        max_pages=1,
    ).discover()

    assert len(result.companies) == 1
    assert result.companies[0].company_name == "Tiny India"
    assert result.companies[0].employee_count == "11-50"
    assert result.companies[0].website == "https://tiny.example"
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.job_title == "Backend Engineer Intern"
    assert job.job_url == "https://wellfound.com/jobs/123-backend-engineer-intern"
    assert job.location == "Remote / India"
    assert job.experience_level == "0 years of exp"
    assert "FastAPI" in str(job.description)
    assert job.company_website == "https://tiny.example"
    assert job.source_job_id == "123"


def test_wellfound_location_parser_ignores_remote_in_job_title() -> None:
    """A title containing Remote does not get mixed into location metadata."""
    mock_client = MagicMock(spec=HttpClient)
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.text = MOCK_WELLFOUND_HTML.replace(
        "Backend Engineer Intern",
        "Remote Backend Engineer Intern",
    )
    detail_response = MagicMock(spec=httpx.Response)
    detail_response.text = "<html></html>"
    mock_client.get.side_effect = [mock_response, detail_response]

    result = WellfoundDiscoverySource(http_client=mock_client, max_pages=1).discover()

    assert result.jobs[0].location == "Remote only • India"


def test_andhra_startup_map_parses_verified_technical_roles() -> None:
    """The niche India board contributes direct links but excludes unrelated roles."""
    mock_client = MagicMock(spec=HttpClient)
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.text = MOCK_ANDHRA_STARTUP_MAP_HTML
    mock_client.get.return_value = mock_response

    result = AndhraStartupMapDiscoverySource(http_client=mock_client).discover()

    assert len(result.companies) == 1
    assert result.companies[0].company_name == "Tiny AI"
    assert result.companies[0].website == "https://tiny.ai"
    assert result.companies[0].employee_count is None
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job.job_title == "Backend Software Engineer Intern"
    assert job.job_url == "https://jobs.lever.co/tiny-ai/abc-123"
    assert job.location == "Remote in India"
    assert job.source_job_id == "role-123"


def test_andhra_startup_map_keeps_company_specific_ats_board() -> None:
    """Generic ATS hosts do not collapse multiple employers into one company."""
    html = MOCK_ANDHRA_STARTUP_MAP_HTML.replace(
        "domain=tiny.ai",
        "domain=jobs.lever.co",
    )
    mock_client = MagicMock(spec=HttpClient)
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.text = html
    mock_client.get.return_value = mock_response

    result = AndhraStartupMapDiscoverySource(http_client=mock_client).discover()

    assert result.companies[0].website == "https://jobs.lever.co/tiny-ai"


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


def test_extract_ats_target_from_public_job_urls() -> None:
    """Recognized public job URLs are converted to normalized ATS board targets."""
    ashby = extract_ats_target(
        "https://jobs.ashbyhq.com/synthetica/12345",
        "Synthetica AI",
        "https://synthetica.ai",
        "11-50",
    )
    greenhouse = extract_ats_target(
        "https://boards.greenhouse.io/roboticsco/jobs/123",
        "Robotics Co",
        "https://robotics.example",
    )
    lever = extract_ats_target(
        "https://jobs.lever.co/tinydata/abc-123",
        "Tiny Data",
        "https://tinydata.example",
    )

    assert ashby and (ashby["platform"], ashby["board_token"]) == ("ashby", "synthetica")
    assert greenhouse and (greenhouse["platform"], greenhouse["board_token"]) == ("greenhouse", "roboticsco")
    assert lever and (lever["platform"], lever["board_token"]) == ("lever", "tinydata")
    assert extract_ats_target(
        "https://example.com/careers/1", "Example", "https://example.com"
    ) is None


def test_pipeline_auto_expands_small_startup_ats_board(db_session: Session) -> None:
    """A small-startup ATS link expands into complete, description-rich job records."""

    class ListingAdapter(BaseDiscoverySource):
        def discover(self) -> DiscoveryResult:
            return DiscoveryResult(
                companies=[
                    Company(
                        company_name="Synthetica AI",
                        website="https://synthetica.ai",
                        source_name="listing",
                        source_url="https://listing.example",
                        employee_count="11-50",
                    )
                ],
                jobs=[
                    Job(
                        job_title="Machine Learning Intern",
                        job_url="https://jobs.ashbyhq.com/synthetica/seed-job",
                        source_name="listing",
                        company_name="Synthetica AI",
                        company_website="https://synthetica.ai",
                    )
                ],
            )

    mock_client = MagicMock(spec=HttpClient)
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.json.return_value = MOCK_ASHBY_JSON
    mock_client.get.return_value = mock_response

    summary = DiscoveryPipeline(
        session=db_session,
        custom_adapters=[ListingAdapter(name="listing")],
        ats_http_client=mock_client,
    ).run()

    assert summary.ats_boards_expanded == 1
    assert summary.ats_jobs_enriched == 1
    assert summary.jobs_inserted == 2
    requested_url = mock_client.get.call_args.args[0]
    assert requested_url.endswith("/synthetica")


def test_pipeline_reuses_existing_company_size_for_ats_expansion(
    db_session: Session,
) -> None:
    """A niche board can inherit size evidence collected by an earlier source."""
    from startup_agent.database.repositories import CompanyRepository

    CompanyRepository(db_session).create_company(
        Company(
            company_name="Weekday",
            website="https://weekday.works",
            source_name="yc",
            source_url="https://example.com/weekday",
            employee_count="38",
        )
    )

    class NicheBoardAdapter(BaseDiscoverySource):
        def discover(self) -> DiscoveryResult:
            return DiscoveryResult(
                companies=[
                    Company(
                        company_name="Weekday",
                        website="https://jobs.lever.co/weekdayworks",
                        source_name="niche_board",
                        source_url="https://niche.example",
                    )
                ],
                jobs=[
                    Job(
                        job_title="Software Engineer Intern",
                        job_url="https://jobs.lever.co/weekdayworks/job-123",
                        source_name="niche_board",
                        company_name="Weekday",
                        company_website="https://jobs.lever.co/weekdayworks",
                    )
                ],
            )

    mock_client = MagicMock(spec=HttpClient)
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.json.return_value = []
    mock_client.get.return_value = mock_response

    summary = DiscoveryPipeline(
        session=db_session,
        custom_adapters=[NicheBoardAdapter(name="niche")],
        ats_http_client=mock_client,
    ).run()

    assert summary.ats_boards_expanded == 1
    assert "/weekdayworks?" in mock_client.get.call_args.args[0]


def test_pipeline_does_not_expand_large_company_board(db_session: Session) -> None:
    """ATS expansion avoids spending requests on companies outside the size target."""

    class LargeCompanyAdapter(BaseDiscoverySource):
        def discover(self) -> DiscoveryResult:
            return DiscoveryResult(
                companies=[
                    Company(
                        company_name="Large Corp",
                        website="https://large.example",
                        source_name="listing",
                        source_url="https://listing.example",
                        employee_count="1001-5000",
                    )
                ],
                jobs=[
                    Job(
                        job_title="Software Intern",
                        job_url="https://boards.greenhouse.io/large/jobs/123",
                        source_name="listing",
                        company_name="Large Corp",
                        company_website="https://large.example",
                    )
                ],
            )

    mock_client = MagicMock(spec=HttpClient)
    summary = DiscoveryPipeline(
        session=db_session,
        custom_adapters=[LargeCompanyAdapter(name="listing")],
        ats_http_client=mock_client,
    ).run()

    assert summary.ats_boards_expanded == 0
    mock_client.get.assert_not_called()


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

