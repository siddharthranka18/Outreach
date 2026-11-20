import json
from pathlib import Path
from unittest.mock import Mock
from startup_agent.discovery.hn_hiring import HnHiringDiscoverySource, parse_comment

def test_monthly_top_level_only_and_emails_stay_unverified(tmp_path):
    fixture = json.loads((Path(__file__).parent / "fixtures/hn_hiring.json").read_text())
    client = Mock()
    client.get.side_effect = [Mock(**{"json.return_value":{"hits":fixture["hits"]}}), Mock(**{"json.return_value":fixture["thread"]})]
    path = tmp_path / "leads.json"
    source = HnHiringDiscoverySource({"studio":("studio.example", {"employee_count":"11-50"})}, http_client=client, leads_path=path)
    result = source.discover()
    assert source.fetched_count == 3
    assert len(result.jobs) == 1
    assert result.companies[0].employee_count == "11-50"
    assert "jobs@studio.example" not in result.jobs[0].description
    leads = json.loads(path.read_text())
    assert len(leads)==1
    assert leads[0]['email']=='jobs@studio.example'
    assert leads[0]['evidence_type']=='hn_monthly_hiring'
    assert leads[0]['top_level'] is True and leads[0]['thread_id']=='123'
    unknown = parse_comment(fixture["thread"]["children"][0], {})
    assert unknown[0].employee_count is None

def test_hn_remote_alone_or_restricted_is_not_india_permission():
    for location in ("Remote", "Remote US only", "Remote Europe only", "UK residents"):
        assert parse_comment({"id":1,"author":"a","text":f'Studio | Junior Software Engineer | {location} <a href="https://studio.example">Apply</a>'}, {}) is None
