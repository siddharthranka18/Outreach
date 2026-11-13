from unittest.mock import patch

from bs4 import BeautifulSoup

from startup_agent.email_drafts import EmailDraft
from startup_agent.hosted_delivery import cold_enquiry_cards, hiring_email
from startup_agent.matching.profile import CandidateProfile


LEAD = {
    "name": "Tiny Studio",
    "domain": "tiny.example",
    "source": "https://tiny.example/careers",
    "recipient": "jobs@tiny.example",
    "context": "We build developer tools.",
    "role": "backend",
    "form": None,
}
URL = "https://tiny.example/#outreach-enquiry"


def test_hiring_email_requires_employer_domain_and_recruiting_context():
    page = BeautifulSoup("""
        <p>jobs@another.example</p>
        <p><a href="mailto:sales@tiny.example">Sales</a></p>
        <p>Send your resume to <a href="mailto:alex@tiny.example">Alex</a></p>
    """, "html.parser")
    assert hiring_email(page, "tiny.example") == "alex@tiny.example"
    assert hiring_email(page, "unrelated.example") is None


def test_hosted_enquiry_generates_once_then_reuses_edit(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    profile = CandidateProfile.load()
    generated = EmailDraft(LEAD["recipient"], "Internship enquiry", "First draft", LEAD["source"])
    with patch("startup_agent.hosted_delivery.generate_email_draft", return_value=generated) as draft:
        cards = cold_enquiry_cards([LEAD], profile, set(), [])
        assert cards[0]["draft"]["source_url"] == LEAD["source"]
        assert draft.call_args.args[0].category == "backend"
        assert draft.call_args.kwargs["enquiry_context"] == LEAD["context"]
        saved = {**cards[0]["draft"], "body": "Edited on Telegram"}
        history = [{"url": URL, "status": "open", "delivery": "pending", "draft": saved}]
        cards = cold_enquiry_cards([LEAD], profile, set(), history)
        assert cards[0]["draft"]["body"] == "Edited on Telegram"
        assert cold_enquiry_cards([LEAD], profile, {"tiny.example"}, history) == []
        history[0]["delivery"] = "sent"
        assert cold_enquiry_cards([LEAD], profile, set(), history) == []
        draft.assert_called_once()


def test_hosted_enquiry_shows_form_without_gemini(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    form = "https://tiny.example/careers/general-application"
    cards = cold_enquiry_cards(
        [{**LEAD, "recipient": None, "form": form}], CandidateProfile.load(), set(), [],
    )
    assert cards == [{"job_url": f"{URL}-form", "text": f"Internship enquiry @ Tiny Studio\nGeneral careers form\n{form}"}]
