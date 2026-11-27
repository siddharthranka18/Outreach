import json

from startup_agent.config.settings import Settings
from startup_agent.funnel import source_funnel
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.routing import build_outreach_routes


def test_founder_title_is_rescued_only_with_early_career_technical_evidence(
    db_session, company_repo, job_repo, tmp_path,
):
    company = company_repo.create_company(Company(
        company_name="Studio", website="https://studio.example", employee_count="11-50",
        source_name="test", source_url="https://studio.example",
    ))
    descriptions = [
        "This internship is open to B.Tech undergraduates. Build Python and FastAPI services for our customers.",
        "This internship uses Python and FastAPI, but requires 5+ years of software experience.",
        "This internship is open to B.Tech undergraduates. You will use Python.",
    ]
    jobs = [job_repo.create_job(Job(
        company_id=company.id, job_title="Founding Builder", location="India", source_name="test",
        job_url=f"https://studio.example/jobs/{index}", description=description,
    )) for index, description in enumerate(descriptions)]
    settings = Settings(base_dir=tmp_path, career_ops_upgrades={
        "enabled": True, "title_miss_rescue": {"enabled": True, "min_tech_indicators": 2},
    })
    routes = build_outreach_routes(db_session, settings)
    assert [(route.job_id, route.title, route.category) for route in routes] == [
        (jobs[0].id, "Founding Builder", "Backend Intern"),
    ]
    assert jobs[0].rescued_by_content
    assert not jobs[1].rescued_by_content
    assert not jobs[2].rescued_by_content
    source_funnel(db_session, settings, routes=routes)
    counts = json.loads((settings.data_dir / "processed/source_counts.json").read_text())
    assert counts["test"]["title_misses_kept_by_content"] == 1
    assert counts["test"]["ghost_jobs_filtered"] == 0
    assert counts["test"]["expired_by_liveness"] == 0
