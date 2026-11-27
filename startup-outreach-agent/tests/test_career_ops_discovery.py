from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx

from startup_agent.database.models import AtsBoardModel
from startup_agent.discovery.board_tracking import BoardHealth
from startup_agent.discovery.career_ops_importer import import_registry, registry_targets
from startup_agent.discovery.direct_ats import DirectAtsDiscoverySource, extract_ats_target
from startup_agent.discovery.remote_feeds import wwr_programming_entries


def test_workday_cxs_parses_usable_postings_and_bounds_the_detail_fetches():
    calls = []

    def post(url, json_data):
        offset = json_data["offset"]
        assert url == "https://studio.wd1.myworkdayjobs.com/wday/cxs/studio/Careers/jobs"
        calls.append(offset)
        return httpx.Response(200, json={"total": 120, "jobPostings": [
            {"title": "Backend Intern", "externalPath": f"/job/India/Intern_{index}", "locationsText": "India"}
            for index in range(offset, offset + 20)
        ]})

    def get(url, **kwargs):
        assert url.startswith("https://studio.wd1.myworkdayjobs.com/wday/cxs/studio/Careers/job/India/")
        calls.append("detail")
        return httpx.Response(200, json={"jobPostingInfo": {"jobDescription": "<p>Python and FastAPI.</p>"}})

    target = extract_ats_target("https://studio.wd1.myworkdayjobs.com/en-US/Careers", "Studio", "https://studio.example")
    adapter = DirectAtsDiscoverySource(http_client=SimpleNamespace(get=get, post=post), platforms={"workday"})
    jobs = adapter.fetch_board_jobs(target)
    assert len(jobs) == 60
    assert jobs[0].description == "Python and FastAPI."
    assert jobs[0].location == "India"
    assert calls == [0, 20, 40] + ["detail"] * 8


def test_registry_uses_independent_size_evidence_and_rechecks_unknown_sizes(db_session, tmp_path):
    path = tmp_path / "portals.example.yml"
    path.write_text("""
tracked_companies:
  - name: Small Studio
    careers_url: https://careers.small.example/openings
    api: https://api.ashbyhq.com/posting-api/job-board/small
  - name: Unverified Studio
    domain: unknown.example
    careers_url: https://jobs.lever.co/unknown
    employee_count: 9
""", encoding="utf-8")
    evidence = {"small.example": {"company_name": "Small Studio", "employee_count": "11-50"}}
    assert import_registry(db_session, str(path), evidence) == {"eligible": 1, "unknown": 1}
    db_session.flush()
    assert db_session.get(AtsBoardModel, ("lever", "unknown")).size_status == "unknown"
    assert [target["board_token"] for target in registry_targets(db_session, evidence, {"ashby", "lever"})] == ["small"]
    evidence["unknown.example"] = {"company_name": "Unverified Studio", "employee_count": "1-10"}
    assert {target["board_token"] for target in registry_targets(db_session, evidence, {"ashby", "lever"})} == {"small", "unknown"}


def test_board_health_pauses_repeated_failures_and_rechecks_quiet_boards_weekly(db_session):
    today = datetime(2026, 11, 27, tzinfo=timezone.utc)
    failed = {"platform": "greenhouse", "board_token": "gone"}
    quiet = {"platform": "ashby", "board_token": "quiet"}
    for offset in (2, 1, 0):
        health = BoardHealth(db_session, {}, now=today - timedelta(days=offset))
        assert health.allows(failed)
        health.outcome(failed, error=httpx.ReadTimeout("timed out"))
        health.save(db_session)
        db_session.flush()
    health = BoardHealth(db_session, {}, now=today)
    assert not health.allows(failed)
    health = BoardHealth(db_session, {}, now=today - timedelta(days=31))
    health.outcome(quiet, jobs=[])
    health.save(db_session)
    db_session.flush()
    health = BoardHealth(db_session, {}, now=today)
    health.outcome(quiet, jobs=[])
    health.save(db_session)
    db_session.flush()
    assert db_session.get(AtsBoardModel, ("ashby", "quiet")).board_status == "paused_quiet"
    assert not BoardHealth(db_session, {}, now=today + timedelta(days=6)).allows(quiet)
    assert BoardHealth(db_session, {}, now=today + timedelta(days=7)).allows(quiet)


def test_wwr_requires_india_or_unrestricted_worldwide():
    regions = ["USA", "Worldwide except India", "Anywhere in the World", "India, Singapore", "Anywhere in Europe"]
    items = [
        f"<item><title>Studio: Intern</title><region>{region}</region>"
        f"<link>https://weworkremotely.com/remote-jobs/{index}</link></item>"
        for index, region in enumerate(regions)
    ]
    data = "<rss><channel>" + "".join(items) + "</channel></rss>"
    assert [row[-1] for row in wwr_programming_entries(data)] == ["", "", "Worldwide", "India", ""]
