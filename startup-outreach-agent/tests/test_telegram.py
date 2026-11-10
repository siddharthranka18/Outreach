import pytest

from startup_agent.database.repositories import CompanyRepository, JobRepository
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.telegram import _record_job_action


@pytest.mark.parametrize("action, confirmation", [
    ("skipped", "Skipped"),
    ("applied", "Marked applied"),
])
def test_telegram_action_survives_rediscovery(session_factory, action, confirmation):
    with session_factory.begin() as session:
        company = CompanyRepository(session).create_company(Company(
            company_name="Tiny AI", website="https://tiny.example",
            source_name="test", source_url="https://tiny.example",
        ))
        posting = Job(
            company_id=company.id, job_title="Backend Intern", source_name="test",
            job_url="https://tiny.example/jobs/backend",
        )
        job_id = JobRepository(session).create_job(posting).id

    callback = {
        "message": {"chat": {"id": 123, "type": "private"}},
        "from": {"id": 456},
        "data": f"job:{action}:{job_id}",
    }
    assert _record_job_action(callback, 123, session_factory) == "This action is unavailable in this chat."
    callback["from"]["id"] = 123
    assert _record_job_action(callback, 123, session_factory) == confirmation
    assert _record_job_action(callback, 123, session_factory) == "Already handled or unavailable."

    with session_factory.begin() as session:
        assert JobRepository(session).upsert_job(posting).status == action
