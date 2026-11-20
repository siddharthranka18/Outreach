import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from startup_agent.discovery.direct_ats import DirectAtsDiscoverySource, extract_ats_target
from startup_agent.discovery.public_ats import fetch_public_ats

FIXTURES = Path(__file__).parent / "fixtures"

@pytest.mark.parametrize("platform,url", [
    ("workable", "https://apply.workable.com/studio/j/ABC"),
    ("breezy", "https://studio.breezy.hr/p/abc"),
    ("teamtailor", "https://studio.teamtailor.com/jobs/12"),
    ("bamboohr", "https://studio.bamboohr.com/careers/12"),
    ("personio", "https://studio.jobs.personio.de/job/12"),
])
def test_public_protocol_fixture(platform, url):
    data = json.loads((FIXTURES / "public_ats.json").read_text())
    target = extract_ats_target(url, "Studio", "https://studio.example", "11-50")
    assert target["platform"] == platform
    client = Mock()
    def get(endpoint):
        if platform in {"teamtailor", "personio"}:
            return Mock(text=(FIXTURES / f"{platform}.xml").read_text())
        if endpoint.endswith("/detail"):
            return Mock(**{"json.return_value":data["bamboohr_detail"]})
        if platform == "breezy" and "/p/" in endpoint:
            return Mock(text=(FIXTURES / "breezy_detail.html").read_text())
        return Mock(**{"json.return_value":data[platform]})
    client.get.side_effect = get
    jobs = fetch_public_ats(target, client)
    assert len(jobs) == 1
    assert "India" in jobs[0].location
    assert "Python" in jobs[0].description or "SQL" in jobs[0].description
    assert jobs[0].source_name == platform + ":studio"
    if platform == "workable": assert "Delhi" in jobs[0].location
    if platform == "personio":
        assert not DirectAtsDiscoverySource(http_client=client).fetch_board_jobs(target)

def test_no_slug_inference_from_workable_shortlinks_or_lookalike_hosts():
    assert extract_ats_target("https://apply.workable.com/j/ABC", "Studio", "https://studio.example") is None
    assert extract_ats_target("https://studio.breezy.hr.evil.example/p/a", "Studio", "https://studio.example") is None
    with pytest.raises(ValueError):
        fetch_public_ats({"platform":"bamboohr", "board_token":"../127.0.0.1"}, Mock())
