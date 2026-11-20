from pathlib import Path
from bs4 import BeautifulSoup
import pytest
from startup_agent.hosted_delivery import hiring_email, verified_contact, contact_pages
from startup_agent.hosted_delivery import enquiry_candidates
from startup_agent.config.settings import Settings
from startup_agent.models.company import Company
from startup_agent.database.repositories import CompanyRepository
from startup_agent.matching.profile import CandidateProfile

def test_current_page_evidence_plain_named_and_footer():
    page = BeautifulSoup((Path(__file__).parent / "fixtures/employer_contact.html").read_text(), "html.parser")
    assert hiring_email(page, "studio.example") == "alex@studio.example"
    assert verified_contact([("https://studio.example/team",page)], "studio.example",
        hn_leads=[{"domain":"studio.example","email":"alex@studio.example","verified":False}]) == ("alex@studio.example","https://studio.example/team")
    empty = BeautifulSoup('<p>Our team: alex@studio.example</p>', 'html.parser')
    assert verified_contact([("https://studio.example/team",empty)], "studio.example",
        hn_leads=[{"domain":"studio.example","email":"alex@studio.example","verified":False}]) is None

@pytest.mark.parametrize("size,allowed", [("2-10",True),("11-20",True),("20",True),("1-10",False),("11-50",True),("51-200",False),("20+",False),(None,False)])
def test_generic_inboxes_are_opt_in_and_whole_band_2_to_50(size, allowed):
    page = BeautifulSoup('<p>Send your resume to <a href="mailto:hello@studio.example">hello@studio.example</a></p>', 'html.parser')
    assert hiring_email(page, "studio.example", employee_count=size) is None
    assert bool(hiring_email(page, "studio.example", allow_generic=True, employee_count=size)) == allowed

def test_page_scan_is_five_and_employer_only():
    pages = contact_pages("https://board.example/company", "studio.example")
    assert len(pages) == 5
    assert all(p.startswith("https://studio.example") for p in pages)
    assert set(pages) == {"https://studio.example"+p for p in ("/careers","","/contact","/about","/team")}
    assert hiring_email(BeautifulSoup('<p>hr@studio.example people@studio.example jobs@outsider.example</p>', 'html.parser'), "studio.example") is None

def test_enquiry_uses_current_contact_page_without_sending(db_session, tmp_path, monkeypatch):
    CompanyRepository(db_session).upsert_company(Company(company_name="Studio",website="https://studio.example",
        source_name="vc_test",source_url="https://board.example/company", employee_count="11-50",
        careers_url="https://studio.example/careers"))
    monkeypatch.setattr("startup_agent.hosted_delivery.gallery_leads", lambda client,**kwargs: [])
    monkeypatch.setattr("startup_agent.hosted_delivery.funded_employers", lambda reviewed: [])
    visited = []
    def fetch(url, domain, client):
        visited.append(url)
        text = '<p>Send your resume to alex@studio.example</p>' if url.endswith('/about') else '<p>Developer tools</p>'
        return url, BeautifulSoup(text, 'html.parser')
    monkeypatch.setattr("startup_agent.hosted_delivery.employer_page", fetch)
    result = enquiry_candidates(db_session, Settings(base_dir=tmp_path), CandidateProfile.load())
    assert len(visited) == 5
    assert len(result) == 1
    assert result[0]["recipient"] == "alex@studio.example"
    assert result[0]["source"] == "https://studio.example/about"
