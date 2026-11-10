import json
from unittest.mock import patch

import httpx
import pytest

from startup_agent.email_drafts import generate_llm_email_draft
from startup_agent.matching.profile import CandidateProfile
from startup_agent.routing import OutreachRoute


def test_llm_preview_sends_selected_project_but_keeps_contact_local(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    profile = CandidateProfile.load()
    route = OutreachRoute(
        company="Tiny Studio", action="Review email candidate",
        title="Full Stack Developer Intern", contact="jobs@tiny.example",
        url="https://tiny.example/jobs/full-stack",
        matching_skills=("React",),
    )
    response = httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps({
        "subject": "Full Stack Developer Internship",
        "body": "I built KarigarFlow using React and would love to bring that experience to your team.",
    })}]}}]})
    with patch("startup_agent.email_drafts.httpx.post", return_value=response) as post:
        draft = generate_llm_email_draft(route, profile)

    facts = post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
    assert "KarigarFlow" in facts
    assert "SehatSaathi" not in facts
    assert route.contact not in facts
    assert profile.name not in facts
    assert route.contact in draft
    assert "KarigarFlow" in draft


def test_gemini_quota_failure_does_not_retry(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    route = OutreachRoute(company="Tiny Studio", action="Apply link", title="Backend Intern")
    with patch("startup_agent.email_drafts.httpx.post", return_value=httpx.Response(429)) as post:
        with pytest.raises(RuntimeError, match="rate limit or quota reached"):
            generate_llm_email_draft(route, CandidateProfile.load())
    post.assert_called_once()
