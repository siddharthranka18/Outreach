"""Tests for database persistence, repositories, relationships, and deduplication."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from startup_agent.database.models import CompanyModel, JobModel
from startup_agent.database.repositories import CompanyRepository, JobRepository
from startup_agent.database.session import session_scope
from startup_agent.models.company import Company
from startup_agent.models.job import Job


def test_company_persistence_basic(company_repo: CompanyRepository) -> None:
    """Test creating and retrieving a company record."""
    company = Company(
        company_name="Apex Robotics",
        website="https://www.apexrobotics.io/",
        source_name="y_combinator",
        source_url="https://ycombinator.com/companies/apex",
        employee_count="11-50",
        industry="Robotics",
    )
    created = company_repo.create_company(company)
    assert created.id is not None
    assert created.company_name == "Apex Robotics"
    assert created.normalized_website == "apexrobotics.io"

    fetched_by_id = company_repo.get_company_by_id(created.id)
    assert fetched_by_id is not None
    assert fetched_by_id.company_name == "Apex Robotics"

    fetched_by_web = company_repo.get_company_by_website("http://apexrobotics.io")
    assert fetched_by_web is not None
    assert fetched_by_web.id == created.id


def test_job_persistence_and_relationship(
    company_repo: CompanyRepository,
    job_repo: JobRepository,
    db_session: Session,
) -> None:
    """Test job creation, foreign key linkage, and relationship population."""
    company = company_repo.create_company(
        Company(
            company_name="Neural Path",
            website="https://neuralpath.ai",
            source_name="top_startups",
            source_url="https://topstartups.io/neuralpath",
        )
    )

    job = Job(
        company_id=company.id,
        job_title="Software Engineering Intern",
        job_url="https://neuralpath.ai/careers/swe-intern?utm_source=gh",
        source_name="direct_career_page",
        location="Remote",
        employment_type="Internship",
    )
    created_job = job_repo.create_job(job)
    assert created_job.id is not None
    assert created_job.company_id == company.id
    assert created_job.normalized_job_url == "https://neuralpath.ai/careers/swe-intern"

    # Test relationship traversal
    jobs_for_company = job_repo.get_jobs_by_company(company.id)
    assert len(jobs_for_company) == 1
    assert jobs_for_company[0].job_title == "Software Engineering Intern"
    assert jobs_for_company[0].company.company_name == "Neural Path"


def test_sqlite_foreign_key_enforcement(
    job_repo: JobRepository,
    db_session: Session,
) -> None:
    """Verify that SQLite foreign key constraints prevent orphan jobs."""
    invalid_job = Job(
        company_id=999999,  # Non-existent company
        job_title="Ghost Job",
        job_url="https://example.com/ghost",
        source_name="test",
    )
    with pytest.raises(IntegrityError):
        job_repo.create_job(invalid_job)
        db_session.flush()
    db_session.rollback()


def test_company_upsert_deduplication(company_repo: CompanyRepository) -> None:
    """Test that upsert prevents duplicate companies and updates existing records."""
    c1 = Company(
        company_name="CloudScale",
        website="https://www.cloudscale.io/",
        source_name="yc",
        source_url="https://yc.com/cloudscale",
        industry="Cloud",
    )
    saved1 = company_repo.upsert_company(c1)

    # Second entry from another source with same normalized website
    c2 = Company(
        company_name="CloudScale Systems",
        website="http://cloudscale.io",
        source_name="top_startups",
        source_url="https://topstartups.io/cloudscale",
        employee_count="51-100",
    )
    saved2 = company_repo.upsert_company(c2)

    assert saved1.id == saved2.id
    all_companies = company_repo.list_companies()
    assert len(all_companies) == 1
    # Industry from c1 was preserved, employee_count from c2 was added
    assert saved2.industry == "Cloud"
    assert saved2.employee_count == "51-100"


def test_company_upsert_preserves_non_null_values(company_repo: CompanyRepository) -> None:
    """Test that existing fields are NEVER overwritten by null or empty values."""
    original = Company(
        company_name="Quantum Byte",
        website="https://quantumbyte.com",
        source_name="yc",
        source_url="https://yc.com/qb",
        employee_count="11-50",
        industry="Quantum Computing",
        funding_stage="Series A",
        location="Boston, MA",
    )
    company_repo.create_company(original)

    # Incoming update has None for employee_count and funding_stage
    incoming = Company(
        company_name="Quantum Byte Inc",
        website="https://quantumbyte.com/",
        source_name="top_startups",
        source_url="https://topstartups.io/qb",
        employee_count=None,
        industry="Quantum Software",  # updated
        funding_stage=None,
        location="Boston, MA",
    )
    updated = company_repo.upsert_company(incoming)

    # Original fields must remain intact
    assert updated.employee_count == "11-50"
    assert updated.funding_stage == "Series A"
    assert updated.industry == "Quantum Software"


def test_company_upsert_does_not_replace_official_site_with_ats(
    company_repo: CompanyRepository,
) -> None:
    """A secondary job source may add careers data without degrading identity."""
    company_repo.create_company(
        Company(
            company_name="Weekday",
            website="https://weekday.works",
            source_name="yc",
            source_url="https://example.com/weekday",
            employee_count="38",
        )
    )

    updated = company_repo.upsert_company(
        Company(
            company_name="Weekday",
            website="https://jobs.lever.co/weekdayworks",
            source_name="andhra_startup_map",
            source_url="https://www.andhrastartupmap.in/jobs",
            careers_url="https://jobs.lever.co/weekdayworks",
        )
    )

    assert updated.website == "https://weekday.works"
    assert updated.normalized_website == "weekday.works"
    assert updated.employee_count == "38"
    assert updated.careers_url == "https://jobs.lever.co/weekdayworks"


def test_job_upsert_deduplication(
    company_repo: CompanyRepository,
    job_repo: JobRepository,
) -> None:
    """Test job upsert deduplication via source_job_id and normalized URL."""
    company = company_repo.create_company(
        Company(
            company_name="Vision Corp",
            website="https://visioncorp.ai",
            source_name="test",
            source_url="https://test.com/vision",
        )
    )

    j1 = Job(
        company_id=company.id,
        job_title="ML Intern",
        job_url="https://boards.greenhouse.io/vision/jobs/12345?gh_src=test",
        source_name="greenhouse",
        source_job_id="12345",
        description="Initial description",
    )
    job_repo.upsert_job(j1)

    # Same job re-scraped with slight URL variation and new description
    j2 = Job(
        company_id=company.id,
        job_title="Machine Learning Intern",
        job_url="https://boards.greenhouse.io/vision/jobs/12345?ref=another",
        source_name="greenhouse",
        source_job_id="12345",
        description="Updated comprehensive description",
    )
    updated_job = job_repo.upsert_job(j2)

    jobs = job_repo.get_jobs_by_company(company.id)
    assert len(jobs) == 1
    assert jobs[0].id == updated_job.id
    assert jobs[0].description == "Updated comprehensive description"


def test_session_lifecycle(session_factory: sessionmaker[Session]) -> None:
    """Test session_scope commit and rollback behavior."""
    # Successful commit
    with session_scope(session_factory) as session:
        repo = CompanyRepository(session)
        repo.create_company(
            Company(
                company_name="Commit Test Corp",
                website="https://committest.com",
                source_name="test",
                source_url="https://test.com",
            )
        )

    with session_scope(session_factory) as session:
        repo = CompanyRepository(session)
        assert repo.get_company_by_website("committest.com") is not None

    # Rollback on exception
    with pytest.raises(RuntimeError):
        with session_scope(session_factory) as session:
            repo = CompanyRepository(session)
            repo.create_company(
                Company(
                    company_name="Rollback Test Corp",
                    website="https://rollbacktest.com",
                    source_name="test",
                    source_url="https://test.com",
                )
            )
            raise RuntimeError("Simulated failure")

    with session_scope(session_factory) as session:
        repo = CompanyRepository(session)
        assert repo.get_company_by_website("rollbacktest.com") is None
