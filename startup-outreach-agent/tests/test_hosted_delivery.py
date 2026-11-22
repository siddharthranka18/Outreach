from unittest.mock import patch

from bs4 import BeautifulSoup

from startup_agent.email_drafts import EmailDraft
from startup_agent.hosted_delivery import cold_enquiry_cards, hiring_email, spreadsheet_enquiry_candidates
from startup_agent.config.settings import Settings
import yaml
from startup_agent.matching.profile import CandidateProfile


LEAD = {
    "name": "Tiny Studio",
    "domain": "tiny.example",
    "source": "https://tiny.example/careers",
    "recipient": "jobs@tiny.example",
    "context": "We build developer tools.",
    "role": "backend",
}
URL = "https://tiny.example/#outreach-enquiry"


def test_spreadsheet_enquiries_require_under_200_and_published_local_inbox(db_session, tmp_path):
    settings = Settings(base_dir=tmp_path)
    settings.config_dir.mkdir()
    rows = [
        {"company": domain, "domain": domain, "employee_count": size,
         "recipient": inbox, "source": "https://publisher.example/hiring"}
        for domain, size, inbox in (
            ("tiny.example", "11-50", "jobs@tiny.example"),
            ("boundary.example", "51-200", "jobs@boundary.example"),
            ("unverified.example", "11-50", ""),
            ("mismatch.example", "11-50", "jobs@other.example"),
            ("grown.example", "11-50", "jobs@grown.example"),
        )
    ]
    (settings.config_dir / "spreadsheet_enquiries.yaml").write_text(yaml.safe_dump(rows))
    (settings.config_dir / "company_sizes.yaml").write_text(
        yaml.safe_dump({"grown.example": {"employee_count": "201-500"}}))
    assert [row["domain"] for row in spreadsheet_enquiry_candidates(db_session, settings)] == ["tiny.example"]


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
        assert draft.call_args.args[0].category == "software"
        assert draft.call_args.kwargs["enquiry_context"] == LEAD["context"]
        saved = {**cards[0]["draft"], "body": "Edited on Telegram"}
        history = [{"url": URL, "status": "open", "delivery": "pending", "draft": saved}]
        cards = cold_enquiry_cards([LEAD], profile, set(), history)
        assert cards[0]["draft"]["body"] == "Edited on Telegram"
        assert cold_enquiry_cards([LEAD], profile, {"tiny.example"}, history) == []
        history[0]["delivery"] = "sent"
        assert cold_enquiry_cards([LEAD], profile, set(), history) == []
        draft.assert_called_once()


def test_hosted_enquiry_requires_a_hiring_email(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    with patch("startup_agent.hosted_delivery.generate_email_draft") as draft:
        assert cold_enquiry_cards(
            [{**LEAD, "recipient": None}], CandidateProfile.load(), set(), [],
        ) == []
        draft.assert_not_called()
