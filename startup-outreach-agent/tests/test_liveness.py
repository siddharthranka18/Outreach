from datetime import datetime, timezone
from types import SimpleNamespace

import httpx

from startup_agent.discovery.liveness import refresh_liveness
from startup_agent.utils.normalizers import normalize_job_url


def posting(url):
    return SimpleNamespace(job_url=url, normalized_job_url=normalize_job_url(url), status="open",
                           last_liveness_check_at=None, liveness_status="active")


def test_404_is_authoritative_for_greenhouse_but_not_lever():
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        response = httpx.Response(404, request=httpx.Request("GET", url))
        response.raise_for_status()

    greenhouse = posting("https://job-boards.greenhouse.io/studio/jobs/324")
    lever = posting("https://jobs.eu.lever.co/studio/38ebff75-bba1-4762-b031-1074d394ec10")
    unsupported = posting("https://example.com/jobs/123")
    now = datetime(2026, 11, 27, tzinfo=timezone.utc)
    client = SimpleNamespace(get=get)
    options = {"lever_404_authoritative": False}
    assert refresh_liveness([greenhouse, lever, unsupported], options, client=client, now=now) == 2
    assert greenhouse.liveness_status == "expired"
    assert lever.liveness_status == "unverified"
    assert unsupported.last_liveness_check_at is None
    assert calls == [
        "https://boards-api.greenhouse.io/v1/boards/studio/jobs/324",
        "https://api.eu.lever.co/v0/postings/studio/38ebff75-bba1-4762-b031-1074d394ec10",
    ]
    assert refresh_liveness([greenhouse, lever], options, client=client, now=now) == 0


def test_ashby_reuses_one_public_board_snapshot():
    listed = posting("https://jobs.ashbyhq.com/studio/alpha")
    absent = posting("https://jobs.ashbyhq.com/studio/beta")
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return httpx.Response(200, json={"jobs": [{"jobUrl": listed.job_url}]})

    assert refresh_liveness([listed, absent], {}, client=SimpleNamespace(get=get)) == 2
    assert listed.liveness_status == "active"
    assert absent.liveness_status == "unverified"
    assert len(calls) == 1
