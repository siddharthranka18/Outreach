from unittest.mock import patch

import pytest

from startup_agent.database.repositories import CompanyRepository, JobRepository
from startup_agent.database.models import EmailDraftModel
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.telegram import _gmail_test_signature, _record_gmail_test, _record_job_action


def test_gmail_approval_sends_only_to_self_once(session_factory, monkeypatch):
    address = "owner@gmail.com"
    monkeypatch.setenv("GMAIL_ADDRESS", address)
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "test-app-password")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test-token")
    with session_factory.begin() as session:
        company = CompanyRepository(session).create_company(Company(
            company_name="Tiny AI", website="https://tiny.example",
            source_name="test", source_url="https://tiny.example",
        ))
        job = JobRepository(session).create_job(Job(
            company_id=company.id, job_title="Backend Intern", source_name="test",
            job_url="https://tiny.example/jobs/backend",
        ))
        draft = EmailDraftModel(
            job_id=job.id, recipient="jobs@tiny.example", subject="Backend internship",
            body="Hello hiring team", listing_url=job.job_url,
        )
        session.add(draft)
        callback_data = f"gmail-test:{job.id}:{_gmail_test_signature(draft, address)}"
    callback = {
        "message": {"chat": {"id": 123, "type": "private"}},
        "from": {"id": 123}, "data": callback_data,
    }
    with patch("startup_agent.telegram.send_gmail_self_test") as send:
        assert _record_gmail_test(callback, 123, session_factory) == "Gmail accepted the test email."
        assert "already handled" in _record_gmail_test(callback, 123, session_factory)
    send.assert_called_once_with(address, "test-app-password", "[Test] Backend internship", "Hello hiring team")


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
