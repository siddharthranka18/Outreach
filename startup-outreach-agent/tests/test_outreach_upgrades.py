from unittest.mock import Mock

import httpx
import pytest
from bs4 import BeautifulSoup

from startup_agent.config.settings import Settings
from startup_agent.database.repositories import CompanyRepository, JobRepository
from startup_agent.discovery.technical_signals import TechnicalSignalResearch
from startup_agent.matching.profile import CandidateProfile
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.outreach_upgrades import upgrade_cards
from startup_agent.routing import build_outreach_routes


def test_small_senior_backlog_goes_only_to_the_optional_review_track(db_session, tmp_path):
    for name, size in (("Small", "11-50"), ("Large", "51-200")):
        website = f"https://{name.lower()}.example"
        company = CompanyRepository(db_session).upsert_company(Company(
            company_name=name, website=website, employee_count=size,
            source_name="fixture", source_url=website,
        ))
        JobRepository(db_session).upsert_job(Job(
            job_title="Senior Backend Engineer", company_id=company.id, job_url=website + "/jobs/backend",
            location="India", source_name="fixture", employment_type="Full-time",
            description=f"Responsibilities: Design Python and FastAPI services, build integration tests and ship APIs. "
                        f"Apply to jobs@{name.lower()}.example.",
        ))
    settings = Settings(base_dir=tmp_path, outreach_upgrades={
        "enabled": True, "shadow_intern_from_senior_jd": {"enabled": True},
    })
    profile = CandidateProfile.load()
    assert not build_outreach_routes(db_session, settings)
    cards = upgrade_cards(db_session, settings, profile, [], set(), [], [], preview=True)
    assert [c["text"] for c in cards] == ["Shadow Intern @ Small"]
    assert not upgrade_cards(db_session, settings, profile, [], {"small.example"}, [], [], preview=True)
    assert not upgrade_cards(db_session, settings, profile, [], set(), [
        {"url": cards[0]["job_url"], "status": "open", "delivery": "pending",
         "draft": {"recipient": "jobs@small.example"}},
    ], [], preview=True)


@pytest.mark.parametrize("status", [403, 404, None])
def test_github_refusal_or_timeout_does_not_break_enquiry_research(status):
    client = Mock()
    request = httpx.Request("GET", "https://api.github.com/orgs/example/repos")
    client.get.side_effect = (httpx.HTTPStatusError("Not available", request=request, response=httpx.Response(status))
                              if status else httpx.ReadTimeout("Timed out"))
    engine = TechnicalSignalResearch({}, client=client)
    page = BeautifulSoup('<a href="https://github.com/example">GitHub</a>'
                         '<a href="/engineering/pipeline">A look at our indexing pipeline</a>', "html.parser")
    org, signal, _ = engine.inspect([("https://studio.example", page)], "studio.example")
    assert org == "https://github.com/example"
    assert signal["url"] == "https://studio.example/engineering/pipeline"
    assert client.get.call_count == 1
