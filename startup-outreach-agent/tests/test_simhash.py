from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from startup_agent.database.models import JobModel
from startup_agent.database.repositories import JobRepository
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.simhash import description_simhash, hamming_distance


DESCRIPTION = (
    "Join our engineering internship. Design reliable Python APIs and develop database schemas. "
    "Write automated tests and document debugging workflows. Collaborate with backend developers on "
    "deployments, monitoring, observability, traces, pull requests, caching, code review and incident response."
)


def test_fingerprints_normalize_markup_punctuation_and_common_footers():
    normalized = description_simhash(DESCRIPTION)
    escaped = description_simhash(f"<p>{DESCRIPTION.upper()}</p><p>Equal opportunity employer. No other terms.</p>")
    assert len(normalized) == 16
    assert hamming_distance(normalized, escaped) == 0
    assert description_simhash("Apply here") is None


def test_two_distinct_relists_collapse_and_set_ghost(db_session, company_repo, monkeypatch):
    company = company_repo.create_company(Company(company_name="Studio", website="https://studio.example",
                                                 source_name="test", source_url="https://studio.example"))
    repo = JobRepository(db_session, {"enabled": True})
    time = datetime(2026, 11, 23, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return time

    monkeypatch.setattr("startup_agent.database.repositories.datetime", Clock)

    def upsert(posting_id, title):
        return repo.upsert_job_with_status(Job(
            company_id=company.id, job_title=title, job_url=f"https://studio.example/jobs/{posting_id}",
            source_name="test", source_job_id=posting_id, description=DESCRIPTION,
        ))

    job, inserted = upsert("1", "Backend Intern")
    assert inserted
    time += timedelta(days=1)
    assert upsert("1", "Backend Intern")[0].repost_count == 0
    assert upsert("2", "Python Intern")[0].repost_count == 1
    assert upsert("3", "Backend Development Intern")[0].repost_count == 1
    time += timedelta(days=1)
    assert upsert("2", "Python Intern")[0].repost_count == 1
    assert upsert("4", "API Intern")[0].id == job.id
    assert job.repost_count == 2
    assert job.is_ghost_job
    assert db_session.scalar(select(func.count()).select_from(JobModel)) == 1
