import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from startup_agent.discovery.portfolio import PortfolioDiscoverySource, parse_consider, size_band, export_suggestions
from startup_agent.matching.startup_filter import StartupEligibilityFilter, StartupEligibilityStatus

FIXTURE = Path(__file__).parent / "fixtures/consider.json"

def test_consider_retains_evidence_and_rejects_restricted_and_senior():
    result = parse_consider(json.loads(FIXTURE.read_text()), "vc_test", "https://board.example")
    assert len(result.jobs) == 1
    assert result.companies[0].employee_count == "11-50"
    assert result.companies[0].funding_stage == "Seed"
    assert result.jobs[0].job_url == "https://studio.example/careers/intern"
    data = json.loads(FIXTURE.read_text())
    row = data["jobs"][0]["jobs"][0]
    row["locations"] = ["Bengaluru"]
    row["normalizedLocations"] = [{"value":"Bengaluru, Karnataka, India"}]
    assert len(parse_consider(data, "vc_test", "https://board.example").jobs) == 1
    assert size_band("201-500 employees") == "201-500"
    assert size_band("1K-5K") is None
    assert size_band("200-11") is None
    assert StartupEligibilityFilter(200, False).evaluate(size_band("51-250 employees")).status != StartupEligibilityStatus.ELIGIBLE

def test_consider_bounded_and_no_token_in_persisted_data(tmp_path):
    client = Mock()
    client.get.return_value.text = 'window.serverInitialData = {"board":{"id":"test"},"csrfToken":"temporary"};'
    client.post.return_value.json.return_value = json.loads(FIXTURE.read_text())
    result = PortfolioDiscoverySource("vc_test", "https://board.example", {"provider":"consider"}, http_client=client).discover()
    assert client.post.call_count == 1
    path = tmp_path / "suggested.yaml"
    export_suggestions(result.companies, path)
    assert "review_required: true" in path.read_text()
    assert "temporary" not in path.read_text()
    with pytest.raises(ValueError): export_suggestions(result.companies, tmp_path / "company_sizes.yaml")

def test_getro_unverified_cannot_silently_return_success():
    with pytest.raises(ValueError):
        PortfolioDiscoverySource("vc_blocked", "https://board.example", {"provider":"getro"}).discover()

def test_later_page_failure_preserves_companies_and_board_links():
    import httpx
    data=json.loads(FIXTURE.read_text())
    data['meta']={'sequence':'next'}
    data['jobs'][0]['jobs'].append({'title':'Senior Software Engineer','locations':['India'],
        'applyUrl':'https://jobs.ashbyhq.com/studio/123'})
    client=Mock()
    client.get.return_value.text='window.serverInitialData = {"board":{"id":"test"},"csrfToken":"temporary"};'
    client.post.return_value.json.side_effect=[data,httpx.ReadTimeout('fixture timeout')]
    source=PortfolioDiscoverySource('vc_test','https://board.example',{'provider':'consider','max_pages':5},http_client=client)
    result=source.discover()
    assert len(result.companies)==1 and len(result.jobs)==1
    assert 'https://jobs.ashbyhq.com/studio/123' in result.companies[0].ats_urls
    assert source.partial_error=='ReadTimeout'
