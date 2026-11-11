from unittest.mock import patch

import pytest

from startup_agent.database.repositories import CompanyRepository, JobRepository
from startup_agent.database.models import EmailDraftModel
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.telegram import (
    _employer_signature, _gmail_test_signature, _record_employer_email, _record_gmail_test, _record_job_action,
    _save_email_edit,
    poll_job_actions,
)


def test_review_processes_pending_actions_before_posting(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    events = []
    update = {"update_id": 42, "callback_query": {"id": "tap", "data": "job:skipped:1"}}
    with (
        patch("startup_agent.telegram._request", side_effect=[
            {"result": [update]}, {"ok": True}, {"result": []}, KeyboardInterrupt,
        ]) as request,
        patch("startup_agent.telegram._record_job_action",
              side_effect=lambda *args: events.append("skip") or "Skipped"),
        pytest.raises(KeyboardInterrupt),
    ):
        poll_job_actions(None, after_pending=lambda: events.append("post"))
    assert events == ["skip", "post"]
    assert request.call_args_list[-1].args[1]["timeout"] == 10


@pytest.mark.parametrize("self_test", [True, False])
def test_gmail_approval_sends_exactly_once(session_factory, monkeypatch, self_test):
    address = "owner@gmail.com"
    monkeypatch.setenv("GMAIL_ADDRESS", address)
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "test-app-password")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:test-token")
    resume = ("resume.pdf", b"%PDF-test")
    monkeypatch.setattr("startup_agent.telegram.load_resume", lambda: resume)
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
        prefix = "gmail-test" if self_test else "gmail-send"
        signature = _gmail_test_signature(draft, address) if self_test else _employer_signature(draft, address, resume)
        callback_data = f"{prefix}:{job.id}:{signature}"
        job_id = job.id
    callback = {
        "message": {"chat": {"id": 123, "type": "private"}},
        "from": {"id": 123}, "data": callback_data,
    }
    handler = _record_gmail_test if self_test else _record_employer_email
    sender = "send_gmail_self_test" if self_test else "send_gmail"
    with patch(f"startup_agent.telegram.{sender}") as send:
        if not self_test:
            edit = {
                "chat": {"id": 123, "type": "private"}, "from": {"id": 123},
                "text": "Updated subject\nUpdated body",
                "reply_to_message": {"from": {"is_bot": True}, "text": f"Edit email #{job_id} ({signature})"},
            }
            with patch("startup_agent.telegram.send_employer_email_card") as card:
                _save_email_edit(edit, 123, session_factory)
                assert card.call_args.args[0].body == "Updated body"
            assert "changed" in handler(callback, 123, session_factory)
            send.assert_not_called()
            with session_factory() as session:
                updated = session.get(EmailDraftModel, job_id)
                callback["data"] = f"gmail-send:{job_id}:{_employer_signature(updated, address, resume)}"
        assert handler(callback, 123, session_factory).startswith("Gmail accepted")
        assert "already handled" in handler(callback, 123, session_factory)
    if self_test:
        send.assert_called_once_with(address, "test-app-password", "[Test] Backend internship", "Hello hiring team")
    else:
        send.assert_called_once_with(
            address, "test-app-password", "jobs@tiny.example", "Updated subject", "Updated body", resume=resume,
        )


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
