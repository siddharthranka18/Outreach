import json
from unittest.mock import patch

import httpx
import pytest

from startup_agent.email_drafts import generate_email_draft, generate_llm_email_draft
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


def test_enquiry_uses_whole_profile_and_adds_resume_note_and_links(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    profile = CandidateProfile.load()
    route = OutreachRoute(company="Tiny Studio", action="Internship enquiry",
                          title="Full Stack Intern", category="full_stack",
                          contact="jobs@tiny.example", matching_skills=("React",))
    response = httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {
        "parts": [{"text": json.dumps({"subject": "Internship enquiry", "body":
            "I'm a CSE student looking for software internships across backend, full-stack and AI work. "
            "I've worked with Python, Node.js, React and LLM tools. Would your team have a suitable opportunity?"})}]
    }}]})
    with patch("startup_agent.email_drafts.httpx.post", return_value=response) as post:
        draft = generate_email_draft(route, profile, enquiry_context="We build developer tools.")
    request = post.call_args.kwargs["json"]
    facts = json.loads(request["contents"][0]["parts"][0]["text"])
    assert facts["role"] == "Software / CSE-related internship enquiry"
    assert "approved_evidence" not in facts
    assert "matched_resume_skills" not in facts
    assert "Node.js" in facts["verified_skills"]["frameworks"]
    assert "React.js" in facts["verified_skills"]["frameworks"]
    assert "LangChain" in facts["verified_skills"]["ai_ml"]
    assert "not an application for a specific role" in request["systemInstruction"]["parts"][0]["text"]
    assert draft.subject == "Software internship enquiry"
    assert "attached my resume" in draft.body
    assert draft.body.endswith(
        "GitHub: https://github.com/siddharthranka18\n"
        "LinkedIn: https://www.linkedin.com/in/siddharth-ranka/"
    )
    assert len(draft.body) < 3000
